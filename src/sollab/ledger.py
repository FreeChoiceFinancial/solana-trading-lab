"""Cash-collateral paper ledger.

Long and short both lock the position notional in cash and pay the open fee
immediately. A short sale does not increase spendable cash. This is not a
broker borrow, a margin loan, or a perpetual swap: there is no funding
payment and no liquidation engine.

Realized P&L is booked only on a full close and subtracts the open fee and
the close fee. Unrealized P&L is the open position's price result at the
mark minus the open fee. Equity is starting cash plus realized plus unrealized.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

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
        starting_cash: Decimal = Decimal("300"),
        max_notional: Decimal = Decimal("10"),
        min_notional: Decimal = Decimal("1"),
        fee_rate: Decimal = Decimal("0.006"),
        slippage_bps: Decimal = Decimal("5"),
    ) -> None:
        for name, value in (
            ("starting_cash", starting_cash),
            ("max_notional", max_notional),
            ("min_notional", min_notional),
            ("fee_rate", fee_rate),
            ("slippage_bps", slippage_bps),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be Decimal")
        if starting_cash < 0 or max_notional <= 0 or min_notional <= 0:
            raise ValueError("cash and notionals must be positive")
        if min_notional > max_notional or fee_rate < 0 or slippage_bps < 0:
            raise ValueError("invalid cost or size parameters")
        self.starting_cash = q(starting_cash)
        self.max_notional = q(max_notional)
        self.min_notional = q(min_notional)
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.cash_free = self.starting_cash
        self.locked_notional = Decimal("0")
        self.realized_pnl = Decimal("0")
        self.position: Position | None = None
        self.closed_positions: list[Position] = []
        self.events: list[LedgerEvent] = []
        self.last_mark: Decimal | None = None
        self.last_ts: datetime | None = None
        self._next_position_id = 1

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
    ) -> FillResult:
        if direction not in {"long", "short"}:
            return self._reject(symbol, direction, "open", requested_notional, mark_price, ts, INVALID_DIRECTION)
        if self.position is not None:
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
        )
        self._next_position_id += 1
        self.position = position
        self.cash_free = q(self.cash_free + cash_delta)
        self.locked_notional = q(self.locked_notional + notional)
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

    def close_position(self, symbol: str, direction: str, mark_price: Decimal, ts: datetime) -> FillResult:
        if self.position is None:
            return self._reject(symbol, direction, "close", None, mark_price, ts, NO_OPEN_POSITION)
        if self.position.symbol != symbol:
            return self._reject(symbol, direction, "close", None, mark_price, ts, SYMBOL_MISMATCH)
        if self.position.direction != direction:
            return self._reject(symbol, direction, "close", None, mark_price, ts, DIRECTION_MISMATCH)
        if self.last_ts is not None and ts < self.last_ts:
            return self._reject(symbol, direction, "close", None, mark_price, ts, TIME_GOES_BACKWARDS)

        position = self.position
        fill_price = self._slip(mark_price, direction, "close")
        exit_notional = q(position.quantity * fill_price)
        exit_fee = q(exit_notional * self.fee_rate)
        if direction == "long":
            price_pnl = (fill_price - position.entry_fill) * position.quantity
        else:
            price_pnl = (position.entry_fill - fill_price) * position.quantity
        price_pnl = q(price_pnl)
        realized = q(price_pnl - position.entry_fee - exit_fee)
        cash_delta = q(self.locked_notional + price_pnl - exit_fee)
        holding = int((ts - position.opened_at).total_seconds())
        if holding < 0:
            return self._reject(symbol, direction, "close", None, mark_price, ts, TIME_GOES_BACKWARDS)

        self.cash_free = q(self.cash_free + cash_delta)
        self.locked_notional = Decimal("0")
        self.realized_pnl = q(self.realized_pnl + realized)
        position.closed_at = ts
        position.exit_mark = mark_price
        position.exit_fill = fill_price
        position.exit_notional = exit_notional
        position.exit_fee = exit_fee
        position.realized_pnl = realized
        position.holding_seconds = holding
        position.status = "closed"
        self.closed_positions.append(position)
        self.position = None
        self.last_mark = None
        self.last_ts = ts
        self._invariant()
        unrealized, equity = self.snapshot(None)
        self.events.append(
            self._event(ts, "close", symbol, direction, cash_delta, exit_fee, "close_position", position.id, unrealized)
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
        )

    def snapshot(self, mark_for_position: Decimal | None) -> tuple[Decimal, Decimal]:
        """Return unrealized P&L and equity. A mark updates the open position's last mark."""
        if self.position is None:
            equity = q(self.starting_cash + self.realized_pnl)
            return Decimal("0"), equity
        mark = self.last_mark if mark_for_position is None else mark_for_position
        if mark is None:
            raise RuntimeError("open position has no mark")
        if mark_for_position is not None:
            self.last_mark = mark_for_position
        unrealized = self.unrealized(mark)
        equity = q(self.starting_cash + self.realized_pnl + unrealized)
        return unrealized, equity

    def unrealized(self, mark: Decimal) -> Decimal:
        if self.position is None:
            return Decimal("0")
        if self.position.direction == "long":
            gross = (mark - self.position.entry_fill) * self.position.quantity
        else:
            gross = (self.position.entry_fill - mark) * self.position.quantity
        return q(gross - self.position.entry_fee)

    def balance_equity(self, mark: Decimal | None) -> Decimal:
        """Equity reconstructed from cash, locked collateral, and price P&L."""
        if self.position is None:
            return q(self.cash_free)
        if mark is None:
            mark = self.last_mark
        if mark is None:
            raise RuntimeError("open position has no mark")
        if self.position.direction == "long":
            price_pnl = (mark - self.position.entry_fill) * self.position.quantity
        else:
            price_pnl = (self.position.entry_fill - mark) * self.position.quantity
        return q(self.cash_free + self.locked_notional + price_pnl)

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
        if self.position is not None and self.last_mark is not None:
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
            note=None,
        )
