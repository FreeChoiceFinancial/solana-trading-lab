"""Hourly simple-moving-average crossover.

The signal uses only closes at or before the bar being judged. It does not
look at later bars. A crossover is a change versus the previous bar, so a
trend that is already in force does not fire again.
"""

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sollab.constants import (
    FAST_WINDOW,
    FEE_RATE,
    MAX_NOTIONAL,
    MIN_NOTIONAL,
    SLIPPAGE_BPS,
    SLOW_WINDOW,
    SOURCE_PREFERENCE,
    STARTING_CASH,
    STRATEGY_ID,
    STRATEGY_NAME,
    STRATEGY_VERSION,
    SYMBOLS,
)

INSUFFICIENT_HISTORY = "insufficient_history"
NO_CROSSOVER = "no_crossover"
ALREADY_LONG = "already_long"
ALREADY_SHORT = "already_short"
BLOCKED_BY_OPEN_POSITION = "blocked_by_open_position"


@dataclass(frozen=True)
class StrategyParams:
    strategy_id: str = STRATEGY_ID
    version: str = STRATEGY_VERSION
    name: str = STRATEGY_NAME
    fast_window: int = FAST_WINDOW
    slow_window: int = SLOW_WINDOW
    symbols: tuple[str, ...] = SYMBOLS
    source_preference: tuple[str, ...] = SOURCE_PREFERENCE
    starting_cash: Decimal = STARTING_CASH
    max_notional: Decimal = MAX_NOTIONAL
    min_notional: Decimal = MIN_NOTIONAL
    fee_rate: Decimal = FEE_RATE
    slippage_bps: Decimal = SLIPPAGE_BPS

    def __post_init__(self) -> None:
        if self.fast_window < 1 or self.slow_window <= self.fast_window:
            raise ValueError("require 1 <= fast_window < slow_window")
        for field in ("starting_cash", "max_notional", "min_notional", "fee_rate", "slippage_bps"):
            if not isinstance(getattr(self, field), Decimal):
                raise TypeError(f"{field} must be Decimal")
        if self.fee_rate < 0 or self.slippage_bps < 0:
            raise ValueError("fee_rate and slippage_bps must be non-negative")
        if self.max_notional <= 0 or self.min_notional <= 0:
            raise ValueError("notionals must be positive")
        if self.min_notional > self.max_notional:
            raise ValueError("min_notional exceeds max_notional")
        if self.starting_cash < self.min_notional:
            raise ValueError("starting_cash is below min_notional")
        if not self.symbols:
            raise ValueError("at least one symbol is required")


def parameters_json(params: StrategyParams) -> str:
    payload = {
        "fast_window": params.fast_window,
        "slow_window": params.slow_window,
        "symbols": list(params.symbols),
        "source_preference": list(params.source_preference),
        "starting_cash": format(params.starting_cash, "f"),
        "max_notional": format(params.max_notional, "f"),
        "min_notional": format(params.min_notional, "f"),
        "fee_rate": format(params.fee_rate, "f"),
        "slippage_bps": format(params.slippage_bps, "f"),
        "timeframe": "1h",
        "fill_assumption": "same_bar_close",
        "same_bar_reversal": False,
        "position_mode": "one_position_cash_collateral",
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def rules_text(params: StrategyParams) -> str:
    fee_pct = format((params.fee_rate * Decimal(100)).normalize(), "f")
    return "\n".join(
        [
            f"{params.name} {params.strategy_id} {params.version}. Paper trading only.",
            "",
            "Data",
            "- Closed hourly candles from the first source in "
            f"{', '.join(params.source_preference)} that has stored 1h rows for that symbol.",
            "- Spot prints are stored for evidence and are not used in the signal.",
            "- Candle sources are never mixed inside one average.",
            "- Windows count stored closes. Missing hours are not interpolated.",
            "",
            "Signal, judged at the close of candle t using closes through t",
            f"- Fast SMA window is {params.fast_window}. Slow SMA window is {params.slow_window}.",
            "- Bullish crossover: fast SMA was less than or equal to slow SMA on t-1, and fast SMA is above slow SMA on t.",
            "- Bearish crossover: fast SMA was greater than or equal to slow SMA on t-1, and fast SMA is below slow SMA on t.",
            f"- Fewer than {params.slow_window + 1} closes: rejection {INSUFFICIENT_HISTORY}.",
            f"- No new cross: rejection {NO_CROSSOVER}. A trend that is already in place does not re-enter.",
            "",
            "Position rules. One open position for the whole portfolio. Within one candle timestamp, "
            "every symbol is judged against the position that was already open at the start of that timestamp. "
            "A close does not free the slot for another symbol until a later timestamp. Symbol priority is "
            + ", ".join(params.symbols)
            + ".",
            "- Flat and bullish: open a long.",
            "- Flat and bearish: open a short.",
            f"- Already long the same symbol and bullish: rejection {ALREADY_LONG}.",
            f"- Already short the same symbol and bearish: rejection {ALREADY_SHORT}.",
            "- Long the same symbol and bearish: close the long. Do not open a short on that same bar.",
            "- Short the same symbol and bullish: close the short. Do not open a long on that same bar.",
            f"- A signal on a symbol other than the open position: rejection {BLOCKED_BY_OPEN_POSITION}.",
            "  The other symbol does not close the position. The open symbol must get its own opposite crossover.",
            "",
            "Sizing and costs",
            f"- Starting paper cash is {params.starting_cash} USD.",
            f"- Position notional is at most {params.max_notional} USD and at least {params.min_notional} USD.",
            "- Both long and short lock that notional as cash collateral. A short does not increase cash.",
            f"- Taker fee is {fee_pct}% of fill notional on the open and again on the close.",
            f"- Slippage is {params.slippage_bps} bps and is applied against the paper account.",
            "- The fill price is that same candle's close after slippage. This is a same-bar close fill.",
            "- Realized P&L is recorded only when the position closes and subtracts both fees.",
            "- Unrealized P&L while the position is open is the mark-to-close price result minus the open fee.",
            "- Holding period is the exit candle timestamp minus the entry candle timestamp, in seconds.",
            "",
            "Ledger rejection reasons, when a signal wants a trade and the account cannot take it:",
            "notional_exceeds_limit, insufficient_cash, position_already_open, no_open_position,",
            "symbol_mismatch, direction_mismatch, time_goes_backwards, invalid_direction.",
            "",
            "This replay is not a forecast, not a live order, and not investment advice.",
        ]
    )


@dataclass(frozen=True)
class OpenView:
    symbol: str
    direction: str


@dataclass(frozen=True)
class Decision:
    signal: str
    action: str
    rejection_reason: str | None
    note: str | None
    fast_sma: Decimal | None
    slow_sma: Decimal | None
    prev_fast_sma: Decimal | None
    prev_slow_sma: Decimal | None


def sma(closes: list[Decimal], end_inclusive: int, window: int) -> Decimal:
    if window < 1 or end_inclusive - window + 1 < 0 or end_inclusive >= len(closes):
        raise ValueError("SMA window is outside the series")
    total = sum(closes[end_inclusive - window + 1 : end_inclusive + 1], Decimal(0))
    return total / Decimal(window)


def _store_sma(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def evaluate(closes: list[Decimal], fast_window: int, slow_window: int) -> Decision:
    """Evaluate the latest close. Earlier closes are context, later closes are ignored."""
    if fast_window < 1 or slow_window <= fast_window:
        raise ValueError("require 1 <= fast_window < slow_window")
    if len(closes) < slow_window + 1:
        return Decision("none", "reject", INSUFFICIENT_HISTORY, None, None, None, None, None)
    end = len(closes) - 1
    prev_fast = sma(closes, end - 1, fast_window)
    prev_slow = sma(closes, end - 1, slow_window)
    curr_fast = sma(closes, end, fast_window)
    curr_slow = sma(closes, end, slow_window)
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        signal = "bullish_crossover"
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        signal = "bearish_crossover"
    else:
        signal = "none"
    stored = Decision(
        signal,
        "pending",
        None if signal != "none" else NO_CROSSOVER,
        None,
        _store_sma(curr_fast),
        _store_sma(curr_slow),
        _store_sma(prev_fast),
        _store_sma(prev_slow),
    )
    if signal == "none":
        return Decision(
            "none",
            "reject",
            NO_CROSSOVER,
            None,
            stored.fast_sma,
            stored.slow_sma,
            stored.prev_fast_sma,
            stored.prev_slow_sma,
        )
    return stored


def decide(signal: Decision, position: OpenView | None, symbol: str) -> Decision:
    """Turn a bar signal into one action. Never reverse on the same bar."""
    if signal.action == "reject":
        return signal
    if signal.signal == "bullish_crossover":
        if position is None:
            action, reason, note = "open_long", None, None
        elif position.symbol == symbol and position.direction == "long":
            action, reason, note = "reject", ALREADY_LONG, None
        elif position.symbol == symbol and position.direction == "short":
            action, reason, note = "close_short", None, "reversal_not_taken_same_bar"
        else:
            action, reason, note = "reject", BLOCKED_BY_OPEN_POSITION, None
    elif signal.signal == "bearish_crossover":
        if position is None:
            action, reason, note = "open_short", None, None
        elif position.symbol == symbol and position.direction == "short":
            action, reason, note = "reject", ALREADY_SHORT, None
        elif position.symbol == symbol and position.direction == "long":
            action, reason, note = "close_long", None, "reversal_not_taken_same_bar"
        else:
            action, reason, note = "reject", BLOCKED_BY_OPEN_POSITION, None
    else:
        action, reason, note = "reject", NO_CROSSOVER, None
    return Decision(
        signal.signal,
        action,
        reason,
        note,
        signal.fast_sma,
        signal.slow_sma,
        signal.prev_fast_sma,
        signal.prev_slow_sma,
    )


def assess(
    closes: list[Decimal],
    params: StrategyParams,
    position: OpenView | None,
    symbol: str,
) -> Decision:
    signal = evaluate(closes, params.fast_window, params.slow_window)
    return decide(signal, position, symbol)
