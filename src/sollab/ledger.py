"""Cash-collateral paper ledger.

Long and short both lock the position notional in cash and pay the open fee
immediately. A short sale does not increase spendable cash. This is not a
margin loan or a liquidation engine. The default borrow rate is zero, so
crypto and pump.fun books do not pay borrow. A caller can set borrow_apr
for a short that must rent the asset. That accrual is on entry notional,
actual/365, and is not a live borrow quote.

One open position is allowed in each market (crypto_spot, pumpfun, stocks,
metals). Markets share one cash balance. Stocks is reserved: the slot
exists, and no strategy in this repo sends stock orders.

Realized P&L is booked only on a full close and subtracts the open fee,
the close fee, and any accrued short borrow. Unrealized P&L is the open
position's price result at the mark minus the open fee and accrued borrow.
Equity is starting cash plus realized plus unrealized.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from sollab.constants import MARKET_CRYPTO, MARKETS, STARTING_CASH

MONEY = Decimal("0.00000001")
QTY = Decimal("0.00000001")

NOTIONAL_EXCEEDS_LIMIT = "notional_exceeds_limit"
INSUFFICIENT_CASH = "insufficient_cash"
POSITION_ALREADY_OPEN = "position_already_open"
NO_OPEN_POSITION = "no_open_position"
SYMBOL_MISMATCH = "symbol_mismatch"
DIRECTION_MISMATCH = "direction_mismatch"
TIME_GOES_BACKWARDS = "time_goes_backwards"
INVALID_DIRECTION = "invalid_direction"
INVALID_MARKET = "invalid_market"


def q(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass
class Position:
    id: int
    symbol: str
    direction: str
    quantity: Decimal
    entry_mark: Decimal
    entry_fill: Decimal
    entry_notional: Decimal
    entry_fee: Decimal
    opened_at: datetime
    closed_at: datetime | None = None
    exit_mark: Decimal | None = None
    exit_fill: Decimal | None = None
    exit_notional: Decimal | None = None
    exit_fee: Decimal | None = None
    realized_pnl: Decimal | None = None
    holding_seconds: int | None = None
    status: str = "open"
    market: str = MARKET_CRYPTO
    borrow_fee: Decimal = Decimal("0")


@dataclass(frozen=True)
class LedgerEvent:
    ts: datetime
    event: str
    symbol: str | None
    direction: str | None
    cash_free: Decimal
    locked_notional: Decimal
    cash_delta: Decimal
    fee: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    position_id: int | None
    note: str | None


@dataclass(frozen=True)
class FillResult:
    status: str
    rejection_reason: str | None
    symbol: str
    direction: str
    intent: str
    requested_notional: Decimal | None
    mark_price: Decimal | None
    fill_price: Decimal | None
    quantity: Decimal | None
    notional: Decimal | None
    fee: Decimal | None
    fee_rate: Decimal
    slippage_bps: Decimal
    cash_free: Decimal
    locked_notional: Decimal
    realized_pnl: Decimal
    trade_realized_pnl: Decimal | None
    unrealized_pnl: Decimal
    equity: Decimal
    position_id: int | None
    holding_seconds: int | None
    note: str | None


class PaperLedger:
    def __init__(
        self,
        starting_cash: Decimal = STARTING_CASH,
        max_notional: Decimal = Decimal("10"),
        min_notional: Decimal = Decimal("1"),
        fee_rate: Decimal = Decimal("0.006"),
        slippage_bps: Decimal = Decimal("5"),
        borrow_apr: Decimal = Decimal("0"),
    ) -> None:
        for name, value in (
            ("starting_cash", starting_cash),
            ("max_notional", max_notional),
            ("min_notional", min_notional),
            ("fee_rate", fee_rate),
            ("slippage_bps", slippage_bps),
            ("borrow_apr", borrow_apr),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be Decimal")
        if starting_cash < 0 or max_notional <= 0 or min_notional <= 0:
            raise ValueError("cash and notionals must be positive")
        if min_notional > max_notional or fee_rate < 0 or slippage_bps < 0 or borrow_apr < 0:
            raise ValueError("invalid cost or size parameters")
        self.starting_cash = q(starting_cash)
        self.max_notional = q(max_notional)
        self.min_notional = q(min_notional)
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.borrow_apr = borrow_apr
        self.cash_free = self.starting_cash
        self.locked_notional = Decimal("0")
        self.realized_pnl = Decimal("0")
        self.positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []
        self.events: list[LedgerEvent] = []
        self.last_marks: dict[str, Decimal] = {}
        self.last_mark: Decimal | None = None
        self.last_ts: datetime | None = None
        self._next_position_id = 1

    @property
    def position(self) -> Position | None:
        """The only open position, or the crypto_spot position when several markets are open."""
        if not self.positions:
            return None
        if len(self.positions) == 1:
            return next(iter(self.positions.values()))
        for market in MARKETS:
            if market in self.positions:
                return self.positions[market]
        return next(iter(self.positions.values()))

    def seed(self, ts: datetime) -> LedgerEvent:
        if self.events:
            raise RuntimeError("ledger already seeded")
        self.last_ts = ts
        event = self._event(ts, "seed", None, None, self.starting_cash, Decimal("0"), "paper_starting_cash")
        self.events.append(event)
        return event

    def open_position(
        self,
        symbol: str,
        direction: str,
        mark_price: Decimal,
        ts: datetime,
        requested_notional: Decimal,
        market: str = MARKET_CRYPTO,
    ) -> FillResult:
        if market not in MARKETS:
            return self._reject(
                symbol, direction, "open", requested_notional, mark_price, ts, INVALID_MARKET
            )
        if direction not in {"long", "short"}:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INVALID_DIRECTION)
        if market in self.positions:
            return self._reject(
                symbol, direction, "open", requested_notional, mark_price, ts, POSITION_ALREADY_OPEN
            )
        if self.last_ts is not None and ts < self.last_ts:
            return self._reject(
                symbol, direction, "open", requested_notional, mark_price, ts, TIME_GOES_BACKWARDS
            )
        if requested_notional > self.max_notional:
            return self._reject(
                symbol, direction, "open", requested_notional, mark_price, ts, NOTIONAL_EXCEEDS_LIMIT
            )
        affordable = (self.cash_free / (Decimal(1) + self.fee_rate)).quantize(MONEY, rounding=ROUND_DOWN)
        notional_target = min(requested_notional, affordable)
        if notional_target < self.min_notional:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INSUFFICIENT_CASH)

        fill_price = self._slip(mark_price, direction, "open")
        if fill_price <= 0:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INSUFFICIENT_CASH)
        quantity = (notional_target / fill_price).quantize(QTY, rounding=ROUND_DOWN)
        if quantity <= 0:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INSUFFICIENT_CASH)
        notional = q(quantity * fill_price)
        if notional > self.max_notional:
            return self._reject(
                symbol, direction, "open", requested_notional, mark_price, ts, NOTIONAL_EXCEEDS_LIMIT
            )
        if notional < self.min_notional:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INSUFFICIENT_CASH)
        fee = q(notional * self.fee_rate)
        cash_delta = q(-(notional + fee))
        if self.cash_free + cash_delta < 0:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INSUFFICIENT_CASH)

        position = Position(
            id=self._next_position_id,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_mark=mark_price,
            entry_fill=fill_price,
            entry_notional=notional,
            entry_fee=fee,
            opened_at=ts,
            market=market,
        )
        self._next_position_id += 1
        self.positions[market] = position
        self.cash_free = q(self.cash_free + cash_delta)
        self.locked_notional = q(self.locked_notional + notional)
        self.last_marks[market] = mark_price
        self.last_mark = mark_price
        self.last_ts = ts
        self._invariant()
        unrealized, equity = self.snapshot(mark_price)
        self.events.append(
            self._event(ts, "open", symbol, direction, cash_delta, fee, "open_position", position.id, unrealized)
        )
        return self._filled(
            symbol,
            direction,
            "open",
            requested_notional,
            mark_price,
            fill_price,
            quantity,
            notional,
            fee,
            position.id,
            None,
            unrealized,
            equity,
            None,
        )

    def close_position(
        self,
        symbol: str,
        direction: str,
        mark_price: Decimal,
        ts: datetime,
        market: str = MARKET_CRYPTO,
    ) -> FillResult:
        if market not in MARKETS:
            return self._reject(symbol, direction, "close", None, mark_price, ts, INVALID_MARKET)
        position = self.positions.get(market)
        if position is None:
            return self._reject(symbol, direction, "close", None, mark_price, ts, NO_OPEN_POSITION)
        if position.symbol != symbol:
            return self._reject(symbol, direction, "close", None, mark_price, ts, SYMBOL_MISMATCH)
        if position.direction != direction:
            return self._reject(symbol, direction, "close", None, mark_price, ts, DIRECTION_MISMATCH)
        if self.last_ts is not None and ts < self.last_ts:
            return self._reject(symbol, direction, "close", None, mark_price, ts, TIME_GOES_BACKWARDS)

        fill_price = self._slip(mark_price, direction, "close")
        exit_notional = q(position.quantity * fill_price)
        exit_fee = q(exit_notional * self.fee_rate)
        borrow = self.accrued_borrow(position, ts)
        if direction == "long":
            price_pnl = (fill_price - position.entry_fill) * position.quantity
        else:
            price_pnl = (position.entry_fill - fill_price) * position.quantity
        price_pnl = q(price_pnl)
        realized = q(price_pnl - position.entry_fee - exit_fee - borrow)
        cash_delta = q(position.entry_notional + price_pnl - exit_fee - borrow)
        holding = int((ts - position.opened_at).total_seconds())
        if holding < 0:
            return self._reject(symbol, direction, "close", None, mark_price, ts, TIME_GOES_BACKWARDS)

        self.cash_free = q(self.cash_free + cash_delta)
        self.locked_notional = q(self.locked_notional - position.entry_notional)
        self.realized_pnl = q(self.realized_pnl + realized)
        position.closed_at = ts
        position.exit_mark = mark_price
        position.exit_fill = fill_price
        position.exit_notional = exit_notional
        position.exit_fee = exit_fee
        position.realized_pnl = realized
        position.borrow_fee = borrow
        position.holding_seconds = holding
        position.status = "closed"
        self.closed_positions.append(position)
        del self.positions[market]
        self.last_marks.pop(market, None)
        self.last_mark = self.last_marks.get(self.position.market) if self.position is not None else None
        self.last_ts = ts
        self._invariant()
        unrealized, equity = self.snapshot(None)
        close_note = "close_position" if borrow == 0 else f"close_position borrow_fee={borrow}"
        self.events.append(
            self._event(
                ts,
                "close",
                symbol,
                direction,
                cash_delta,
                q(exit_fee + borrow),
                close_note,
                position.id,
                unrealized,
            )
        )
        return self._filled(
            symbol,
            direction,
            "close",
            None,
            mark_price,
            fill_price,
            position.quantity,
            exit_notional,
            exit_fee,
            position.id,
            holding,
            unrealized,
            equity,
            realized,
            close_note,
        )

    def snapshot(
        self,
        mark_for_position: Decimal | None,
        marks: dict[str, Decimal] | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Return unrealized P&L and equity. A mark updates that position's last mark."""
        if marks:
            for market, mark in marks.items():
                if market in self.positions:
                    self.last_marks[market] = mark
            if self.position is not None and self.position.market in self.last_marks:
                self.last_mark = self.last_marks[self.position.market]
        elif mark_for_position is not None and self.position is not None:
            self.last_marks[self.position.market] = mark_for_position
            self.last_mark = mark_for_position
        if not self.positions:
            equity = q(self.starting_cash + self.realized_pnl)
            return Decimal("0"), equity
        if mark_for_position is not None and not marks:
            unrealized = self.unrealized(mark_for_position)
        else:
            unrealized = self._unrealized_all()
        equity = q(self.starting_cash + self.realized_pnl + unrealized)
        return unrealized, equity

    def unrealized(self, mark: Decimal) -> Decimal:
        if not self.positions:
            return Decimal("0")
        focus = self.position
        total = Decimal("0")
        for market, position in self.positions.items():
            if focus is not None and position.id == focus.id:
                total += self._position_unrealized(position, mark)
            else:
                total += self._position_unrealized(position, self.last_marks[market])
        return q(total)

    def _unrealized_all(self) -> Decimal:
        if not self.positions:
            return Decimal("0")
        total = Decimal("0")
        for market, position in self.positions.items():
            mark = self.last_marks.get(market)
            if mark is None:
                raise RuntimeError(f"open {market} position has no mark")
            total += self._position_unrealized(position, mark)
        return q(total)

    def accrued_borrow(self, position: Position, as_of: datetime) -> Decimal:
        """Short borrow on entry notional, actual/365. Longs and a zero APR pay nothing."""
        if self.borrow_apr <= 0 or position.direction != "short":
            return Decimal("0")
        seconds = int((as_of - position.opened_at).total_seconds())
        if seconds <= 0:
            return Decimal("0")
        year = Decimal(365 * 24 * 60 * 60)
        return q(position.entry_notional * self.borrow_apr * Decimal(seconds) / year)

    def mark(self, market: str, mark: Decimal, ts: datetime) -> tuple[Decimal, Decimal]:
        """Advance the clock and the open mark. Does not trade."""
        if self.last_ts is not None and ts < self.last_ts:
            raise ValueError("mark time goes backwards")
        if market in self.positions:
            self.last_marks[market] = mark
            self.last_mark = mark
        self.last_ts = ts
        return self.snapshot(mark if market in self.positions else None)

    def _position_unrealized(self, position: Position, mark: Decimal) -> Decimal:
        as_of = self.last_ts or position.opened_at
        return q(self._gross(position, mark) - position.entry_fee - self.accrued_borrow(position, as_of))

    def _gross(self, position: Position, mark: Decimal) -> Decimal:
        if position.direction == "long":
            return (mark - position.entry_fill) * position.quantity
        return (position.entry_fill - mark) * position.quantity

    def balance_equity(self, mark: Decimal | None) -> Decimal:
        """Equity reconstructed from cash, locked collateral, and price P&L."""
        if not self.positions:
            return q(self.cash_free)
        if mark is not None and self.position is not None:
            self.last_marks[self.position.market] = mark
        price_pnl = Decimal("0")
        for market, position in self.positions.items():
            current = self.last_marks.get(market)
            if current is None:
                raise RuntimeError(f"open {market} position has no mark")
            price_pnl += self._gross(position, current)
        as_of = self.last_ts
        borrow = Decimal("0")
        if as_of is not None:
            for position in self.positions.values():
                borrow += self.accrued_borrow(position, as_of)
        return q(self.cash_free + self.locked_notional + price_pnl - borrow)

    def _slip(self, mark: Decimal, direction: str, intent: str) -> Decimal:
        slip = self.slippage_bps / Decimal(10000)
        adverse_up = (direction == "long" and intent == "open") or (direction == "short" and intent == "close")
        factor = Decimal(1) + slip if adverse_up else Decimal(1) - slip
        return q(mark * factor)

    def _invariant(self) -> None:
        if self.cash_free < 0 or self.locked_notional < 0:
            raise RuntimeError(
                f"cash invariant broken cash_free={self.cash_free} locked={self.locked_notional}"
            )

    def _event(
        self,
        ts: datetime,
        event: str,
        symbol: str | None,
        direction: str | None,
        cash_delta: Decimal,
        fee: Decimal,
        note: str,
        position_id: int | None = None,
        unrealized: Decimal = Decimal("0"),
    ) -> LedgerEvent:
        equity = q(self.starting_cash + self.realized_pnl + unrealized)
        return LedgerEvent(
            ts=ts,
            event=event,
            symbol=symbol,
            direction=direction,
            cash_free=self.cash_free,
            locked_notional=self.locked_notional,
            cash_delta=q(cash_delta),
            fee=q(fee),
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            equity=equity,
            position_id=position_id,
            note=note,
        )

    def _reject(
        self,
        symbol: str,
        direction: str,
        intent: str,
        requested_notional: Decimal | None,
        mark_price: Decimal | None,
        ts: datetime,
        reason: str,
    ) -> FillResult:
        del ts
        unrealized, equity = (Decimal("0"), q(self.starting_cash + self.realized_pnl))
        if self.positions and all(market in self.last_marks for market in self.positions):
            unrealized, equity = self.snapshot(None)
        return FillResult(
            status="rejected",
            rejection_reason=reason,
            symbol=symbol,
            direction=direction,
            intent=intent,
            requested_notional=requested_notional,
            mark_price=mark_price,
            fill_price=None,
            quantity=None,
            notional=None,
            fee=None,
            fee_rate=self.fee_rate,
            slippage_bps=self.slippage_bps,
            cash_free=self.cash_free,
            locked_notional=self.locked_notional,
            realized_pnl=self.realized_pnl,
            trade_realized_pnl=None,
            unrealized_pnl=unrealized,
            equity=equity,
            position_id=self.position.id if self.position else None,
            holding_seconds=None,
            note=None,
        )

    def _filled(
        self,
        symbol: str,
        direction: str,
        intent: str,
        requested_notional: Decimal | None,
        mark_price: Decimal,
        fill_price: Decimal,
        quantity: Decimal,
        notional: Decimal,
        fee: Decimal,
        position_id: int,
        holding_seconds: int | None,
        unrealized: Decimal,
        equity: Decimal,
        trade_realized: Decimal | None,
        note: str | None = None,
    ) -> FillResult:
        return FillResult(
            status="filled",
            rejection_reason=None,
            symbol=symbol,
            direction=direction,
            intent=intent,
            requested_notional=requested_notional,
            mark_price=mark_price,
            fill_price=fill_price,
            quantity=quantity,
            notional=notional,
            fee=fee,
            fee_rate=self.fee_rate,
            slippage_bps=self.slippage_bps,
            cash_free=self.cash_free,
            locked_notional=self.locked_notional,
            realized_pnl=self.realized_pnl,
            trade_realized_pnl=trade_realized,
            unrealized_pnl=unrealized,
            equity=equity,
            position_id=position_id,
            holding_seconds=holding_seconds,
            note=note,
        )
