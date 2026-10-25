"""Paper baselines for the metals slot.

Both strategies use one metals position, at most 10 USD, on the shared
5000 USD account. Fills are the next daily bar's open. Parameters are
fixed. They are not fit on validation or forward. A buy-and-hold long of
the same PAXG window is the benchmark.

The gold/silver rule is one leg. It trades PAXG only. Silver is a signal.
A silver close is eligible only when its bar timestamp is at or before
the gold bar timestamp.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sollab.constants import (
    CASH_ERA_CURRENT,
    FEE_RATE,
    FILL_MODEL,
    MARKET_METALS,
    MAX_NOTIONAL,
    MIN_NOTIONAL,
    SLIPPAGE_BPS,
    STARTING_CASH,
)
from sollab.ledger import PaperLedger, q
from sollab.metalsconst import (
    BENCHMARK_ID,
    FAST_WINDOW,
    RATIO_STRATEGY_ID,
    SHORT_BORROW_APR,
    SILVER_SOURCE,
    SILVER_SYMBOL,
    SLOW_WINDOW,
    SMA_STRATEGY_ID,
    STRATEGY_VERSION,
    TRADED_SOURCE,
    TRADED_SYMBOL,
)
from sollab.models import as_decimal
from sollab.splits import PeriodWindow, full_window, plan_splits
from sollab.storage import dec_text, ensure_account_rules, record_error, reset_strategy_version, upsert_strategy
from sollab.timeutil import iso_z, parse_timestamp

INSUFFICIENT_HISTORY = "insufficient_history"
NO_CROSSOVER = "no_crossover"
NO_NEXT_CANDLE = "no_next_candle"
MISSING_SILVER = "missing_silver"
ALREADY_LONG = "already_long"
ALREADY_SHORT = "already_short"


class NoMetalsData(Exception):
    """PAXG daily candles are not stored."""


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: Decimal
    close: Decimal
    source: str
    endpoint: str


@dataclass
class DecisionRow:
    ts: datetime
    signal: str
    action: str
    reason: str | None
    note: str | None
    fast: Decimal | None
    slow: Decimal | None
    close: Decimal
    source: str


@dataclass
class FillRow:
    ts: datetime
    result: object


@dataclass
class PeriodResult:
    period: str
    strategy_id: str
    ending_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    benchmark_equity: Decimal
    open_position: str | None
    opens: int
    closes: int


@dataclass
class MetalsSummary:
    recorded_at: datetime
    periods: list[PeriodResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    paxg_bars: int = 0
    silver_bars: int = 0


def sma(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def price_cross(closes: list[Decimal], fast: int = FAST_WINDOW, slow: int = SLOW_WINDOW) -> str:
    """Crossover using only the closes passed in. The last close is the signal bar."""
    if len(closes) < slow + 1:
        return INSUFFICIENT_HISTORY
    prev_fast = sma(closes[-fast - 1 : -1])
    prev_slow = sma(closes[-slow - 1 : -1])
    now_fast = sma(closes[-fast:])
    now_slow = sma(closes[-slow:])
    if prev_fast <= prev_slow and now_fast > now_slow:
        return "long"
    if prev_fast >= prev_slow and now_fast < now_slow:
        return "short"
    return "none"


def aligned_silver(gold: list[Bar], silver: list[Bar], index: int) -> list[Decimal | None]:
    """Silver closes usable at each gold bar through index. Later silver bars are ignored."""
    usable = [bar for bar in silver if bar.ts <= gold[index].ts]
    out: list[Decimal | None] = []
    cursor = 0
    latest: Decimal | None = None
    ordered = usable
    for gold_bar in gold[: index + 1]:
        while cursor < len(ordered) and ordered[cursor].ts <= gold_bar.ts:
            latest = ordered[cursor].close
            cursor += 1
        out.append(latest)
    return out


def ratio_cross(gold: list[Bar], silver: list[Bar], index: int, slow: int = SLOW_WINDOW) -> str:
    series = aligned_silver(gold, silver, index)
    ratios: list[Decimal] = []
    for gold_bar, silver_close in zip(gold[: index + 1], series):
        if silver_close is None or silver_close <= 0:
            continue
        ratios.append(gold_bar.close / silver_close)
    if len(ratios) < slow + 1:
        return INSUFFICIENT_HISTORY if series[-1] is not None else MISSING_SILVER
    prev_mean = sma(ratios[-slow - 1 : -1])
    now_mean = sma(ratios[-slow:])
    prev_ratio = ratios[-2]
    now_ratio = ratios[-1]
    # Mean reversion: a ratio that crosses above its own mean shorts gold.
    if prev_ratio <= prev_mean and now_ratio > now_mean:
        return "short"
    if prev_ratio >= prev_mean and now_ratio < now_mean:
        return "long"
    return "none"


def run_metals(
    conn: sqlite3.Connection,
    recorded_at: datetime | None = None,
) -> MetalsSummary:
    recorded_at = recorded_at or datetime.now(timezone.utc)
    gold = _load(conn, TRADED_SYMBOL, TRADED_SOURCE)
    silver = _load(conn, SILVER_SYMBOL, SILVER_SOURCE)
    if not gold:
        raise NoMetalsData("no closed PAXG 1d Coinbase candles; run metals-collect first")
    summary = MetalsSummary(recorded_at=recorded_at, paxg_bars=len(gold), silver_bars=len(silver))
    windows = plan_splits([bar.ts for bar in gold])
    if windows is None:
        windows = [full_window([bar.ts for bar in gold])]
        summary.warnings.append("PAXG series is too short for a 60/20 split; stored as full_window")
    if not silver:
        summary.warnings.append("no SI daily bars; gold/silver ratio was not run")
        with conn:
            record_error(conn, "metals-run", summary.warnings[-1], None, recorded_at)
    with conn:
        ensure_account_rules(conn, recorded_at)
        for strategy_id in (BENCHMARK_ID, SMA_STRATEGY_ID, RATIO_STRATEGY_ID):
            reset_strategy_version(conn, strategy_id, STRATEGY_VERSION)
        for window in windows:
            benchmark = _run_buy_hold(gold, window)
            _store(
                conn,
                strategy_id=BENCHMARK_ID,
                name="PAXG buy and hold",
                rules=_benchmark_rules(),
                parameters=_parameters("buy_and_hold"),
                window=window,
                gold=gold,
                replay=benchmark,
                benchmark_equity=benchmark.ending_equity,
                recorded_at=recorded_at,
            )
            trend = _run_cross(gold, window, lambda index: price_cross([bar.close for bar in gold[: index + 1]]))
            _store(
                conn,
                strategy_id=SMA_STRATEGY_ID,
                name="Metals daily SMA trend",
                rules=_sma_rules(),
                parameters=_parameters("sma_crossover"),
                window=window,
                gold=gold,
                replay=trend,
                benchmark_equity=benchmark.ending_equity,
                recorded_at=recorded_at,
            )
            if silver:
                ratio = _run_cross(gold, window, lambda index: ratio_cross(gold, silver, index))
                _store(
                    conn,
                    strategy_id=RATIO_STRATEGY_ID,
                    name="Gold silver ratio mean reversion",
                    rules=_ratio_rules(),
                    parameters=_parameters("ratio_mean_reversion"),
                    window=window,
                    gold=gold,
                    replay=ratio,
                    benchmark_equity=benchmark.ending_equity,
                    recorded_at=recorded_at,
                )
            for strategy_id, replay in (
                (BENCHMARK_ID, benchmark),
                (SMA_STRATEGY_ID, trend),
                *(( (RATIO_STRATEGY_ID, ratio), ) if silver else ()),
            ):
                summary.periods.append(
                    PeriodResult(
                        period=window.name,
                        strategy_id=strategy_id,
                        ending_equity=replay.ending_equity,
                        realized_pnl=replay.realized,
                        unrealized_pnl=replay.unrealized,
                        benchmark_equity=benchmark.ending_equity,
                        open_position=replay.open_position,
                        opens=replay.opens,
                        closes=replay.closes,
                    )
                )
    return summary


@dataclass(frozen=True)
class Mark:
    ts: datetime
    equity: Decimal
    cash_free: Decimal
    locked: Decimal
    realized: Decimal
    unrealized: Decimal
    price: Decimal


@dataclass
class Replay:
    ledger: PaperLedger
    decisions: list[DecisionRow]
    fills: list[FillRow]
    equity: list[Mark]
    ending_equity: Decimal
    realized: Decimal
    unrealized: Decimal
    open_position: str | None
    opens: int
    closes: int


def _run_buy_hold(gold: list[Bar], window: PeriodWindow) -> Replay:
    ledger = _ledger()
    ledger.seed(gold[0].ts)
    decisions: list[DecisionRow] = []
    fills: list[FillRow] = []
    equity: list[Mark] = []
    opened = False
    scored = [bar for bar in gold if window.signal_start <= bar.ts <= window.fill_end]
    last = scored[-1] if scored else None
    for bar in gold:
        if bar.ts > window.fill_end:
            break
        if (
            not opened
            and last is not None
            and window.signal_start <= bar.ts <= window.signal_end
        ):
            result = ledger.open_position(
                TRADED_SYMBOL, "long", bar.open, bar.ts, MAX_NOTIONAL, MARKET_METALS
            )
            decisions.append(
                DecisionRow(bar.ts, "long", "open", result.rejection_reason, "buy_and_hold_entry", None, None, bar.close, bar.source)
            )
            fills.append(FillRow(bar.ts, result))
            opened = result.status == "filled"
        if opened and last is not None and bar.ts == last.ts and ledger.positions.get(MARKET_METALS) is not None:
            result = ledger.close_position(TRADED_SYMBOL, "long", bar.close, bar.ts, MARKET_METALS)
            decisions.append(
                DecisionRow(bar.ts, "flat", "close", result.rejection_reason, "buy_and_hold_exit", None, None, bar.close, bar.source)
            )
            fills.append(FillRow(bar.ts, result))
            opened = ledger.positions.get(MARKET_METALS) is not None
        equity.append(_mark(ledger, bar))
    return _finish(ledger, decisions, fills, equity)


def _run_cross(gold: list[Bar], window: PeriodWindow, signal_at) -> Replay:
    ledger = _ledger()
    ledger.seed(gold[0].ts)
    decisions: list[DecisionRow] = []
    fills: list[FillRow] = []
    equity: list[Mark] = []
    pending: tuple[str, str] | None = None
    for index, bar in enumerate(gold):
        if bar.ts > window.fill_end:
            break
        if pending is not None:
            intent, direction = pending
            pending = None
            if intent == "open":
                result = ledger.open_position(
                    TRADED_SYMBOL, direction, bar.open, bar.ts, MAX_NOTIONAL, MARKET_METALS
                )
            else:
                result = ledger.close_position(TRADED_SYMBOL, direction, bar.open, bar.ts, MARKET_METALS)
            fills.append(FillRow(bar.ts, result))
        if window.signal_start <= bar.ts <= window.signal_end:
            signal = signal_at(index)
            position = ledger.positions.get(MARKET_METALS)
            action, reason, queued = _decide(signal, position.direction if position else None, index + 1 < len(gold) and gold[index + 1].ts <= window.fill_end)
            if queued is not None:
                pending = queued
            decisions.append(
                DecisionRow(bar.ts, signal if signal in {"long", "short"} else "none", action, reason, None, None, None, bar.close, bar.source)
            )
        equity.append(_mark(ledger, bar))
    return _finish(ledger, decisions, fills, equity)


def _decide(signal: str, position: str | None, has_next: bool) -> tuple[str, str | None, tuple[str, str] | None]:
    if signal in {INSUFFICIENT_HISTORY, MISSING_SILVER}:
        return "reject", signal, None
    if signal == "none":
        return "reject", NO_CROSSOVER, None
    if not has_next:
        return "reject", NO_NEXT_CANDLE, None
    if position is None:
        return "open", None, ("open", signal)
    if position == signal:
        return "reject", ALREADY_LONG if signal == "long" else ALREADY_SHORT, None
    return "close", None, ("close", position)


def _mark(ledger: PaperLedger, bar: Bar) -> Mark:
    unrealized, marked = ledger.mark(MARKET_METALS, bar.close, bar.ts)
    return Mark(
        ts=bar.ts,
        equity=marked,
        cash_free=ledger.cash_free,
        locked=ledger.locked_notional,
        realized=ledger.realized_pnl,
        unrealized=unrealized,
        price=bar.close,
    )


def _ledger() -> PaperLedger:
    return PaperLedger(
        starting_cash=STARTING_CASH,
        max_notional=MAX_NOTIONAL,
        min_notional=MIN_NOTIONAL,
        fee_rate=FEE_RATE,
        slippage_bps=SLIPPAGE_BPS,
        borrow_apr=SHORT_BORROW_APR,
    )


def _finish(ledger: PaperLedger, decisions: list[DecisionRow], fills: list[FillRow], equity: list[Mark]) -> Replay:
    unrealized, ending = ledger.snapshot(None)
    opens = sum(1 for item in fills if item.result.status == "filled" and item.result.intent == "open")
    closes = sum(1 for item in fills if item.result.status == "filled" and item.result.intent == "close")
    open_position = None
    if ledger.position is not None:
        open_position = f"{ledger.position.direction} {ledger.position.symbol}"
    return Replay(
        ledger=ledger,
        decisions=decisions,
        fills=fills,
        equity=equity,
        ending_equity=ending,
        realized=ledger.realized_pnl,
        unrealized=unrealized,
        open_position=open_position,
        opens=opens,
        closes=closes,
    )


def _load(conn: sqlite3.Connection, symbol: str, source: str) -> list[Bar]:
    rows = conn.execute(
        """
        SELECT open, close, source_timestamp, endpoint, source_name
        FROM prices
        WHERE symbol = ? AND interval = '1d' AND source_name = ?
          AND open IS NOT NULL AND source_timestamp IS NOT NULL
        ORDER BY source_timestamp
        """,
        (symbol, source),
    ).fetchall()
    by_time: dict[datetime, Bar] = {}
    for row in rows:
        ts = parse_timestamp(row["source_timestamp"])
        by_time[ts] = Bar(
            ts=ts,
            open=as_decimal(row["open"]),
            close=as_decimal(row["close"]),
            source=row["source_name"],
            endpoint=row["endpoint"],
        )
    return [by_time[key] for key in sorted(by_time)]


def _parameters(kind: str) -> str:
    return json.dumps(
        {
            "kind": kind,
            "fast_window": FAST_WINDOW,
            "slow_window": SLOW_WINDOW,
            "symbol": TRADED_SYMBOL,
            "source": TRADED_SOURCE,
            "silver_symbol": SILVER_SYMBOL,
            "silver_source": SILVER_SOURCE,
            "fill_assumption": FILL_MODEL,
            "market": MARKET_METALS,
            "max_notional": "10",
            "starting_cash": "5000",
            "borrow_apr": format(SHORT_BORROW_APR, "f"),
            "borrow_day_count": "actual/365",
            "parameters_fit_on_period": False,
            "same_bar_reversal": False,
        },
        sort_keys=True,
    )


def _sma_rules() -> str:
    return (
        "metals_sma_trend 1.0.0. Daily PAXG closes from Coinbase. "
        f"Bullish cross is the {FAST_WINDOW}-bar SMA moving from at or below the {SLOW_WINDOW}-bar SMA to above it. "
        "The fill is the next stored daily open. One metals position, 10 USD, shared 5000 USD account. "
        "Shorts accrue 0.50 percent annualized borrow on entry notional, actual/365. "
        "Windows are fixed and are not fit on validation or forward."
    )


def _ratio_rules() -> str:
    return (
        "metals_gold_silver_ratio 1.0.0. The ratio is the PAXG close divided by the latest SI=F close "
        "whose bar timestamp is at or before that PAXG bar. A cross of the ratio above its "
        f"{SLOW_WINDOW}-bar mean shorts PAXG. A cross below it goes long PAXG. Silver is not traded. "
        "This is one leg, not a hedged pair. Fill is the next PAXG open. Short borrow is 0.50 percent."
    )


def _benchmark_rules() -> str:
    return (
        "metals_buy_hold 1.0.0. Long 10 USD of PAXG at the first open inside the scored window "
        "and exit at the last bar's close. Same taker fee and slippage as the strategies. "
        "No borrow, because the benchmark is long. Not a forecast."
    )


def _store(
    conn: sqlite3.Connection,
    *,
    strategy_id: str,
    name: str,
    rules: str,
    parameters: str,
    window: PeriodWindow,
    gold: list[Bar],
    replay: Replay,
    benchmark_equity: Decimal,
    recorded_at: datetime,
) -> None:
    version_id = upsert_strategy(
        conn,
        strategy_id=strategy_id,
        version=STRATEGY_VERSION,
        name=name,
        parameters_json=parameters,
        rules_text=rules,
        created_at=recorded_at,
    )
    excess = q(replay.ending_equity - benchmark_equity)
    note = (
        f"Paper metals period={window.name}. Next daily open fills. Cash era {CASH_ERA_CURRENT}. "
        f"Buy-and-hold ending equity on this window is {benchmark_equity}. "
        f"Strategy minus buy-and-hold is {excess}. Not live orders."
    )
    cursor = conn.execute(
        """
        INSERT INTO simulation_runs (
            strategy_version_id, recorded_at, parameters_json, candle_sources_json,
            candle_counts_json, starting_cash, ending_equity, realized_pnl,
            unrealized_pnl, note, period, fill_model, book, window_json, cash_era
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            iso_z(recorded_at),
            parameters,
            json.dumps({"source": gold[0].source, "endpoint": gold[0].endpoint}, sort_keys=True),
            json.dumps({"PAXG": len(gold)}, sort_keys=True),
            "5000",
            dec_text(replay.ending_equity),
            dec_text(replay.realized),
            dec_text(replay.unrealized),
            note,
            window.name,
            FILL_MODEL,
            "experiment",
            json.dumps(window.as_dict(), sort_keys=True),
            CASH_ERA_CURRENT,
        ),
    )
    run_id = int(cursor.lastrowid)
    id_map: dict[int, int] = {}
    for position in list(replay.ledger.closed_positions) + list(replay.ledger.positions.values()):
        inserted = conn.execute(
            """
            INSERT INTO positions (
                strategy_version_id, simulation_run_id, symbol, direction, quantity,
                entry_mark, entry_fill, entry_notional, entry_fee, opened_at, closed_at,
                exit_mark, exit_fill, exit_notional, exit_fee, realized_pnl, holding_seconds,
                status, recorded_at, market
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                run_id,
                position.symbol,
                position.direction,
                dec_text(position.quantity),
                dec_text(position.entry_mark),
                dec_text(position.entry_fill),
                dec_text(position.entry_notional),
                dec_text(position.entry_fee),
                iso_z(position.opened_at),
                iso_z(position.closed_at) if position.closed_at else None,
                dec_text(position.exit_mark),
                dec_text(position.exit_fill),
                dec_text(position.exit_notional),
                dec_text(position.exit_fee),
                dec_text(position.realized_pnl),
                position.holding_seconds,
                position.status,
                iso_z(recorded_at),
                position.market,
            ),
        )
        id_map[position.id] = int(inserted.lastrowid)
    for item in replay.decisions:
        conn.execute(
            """
            INSERT INTO decisions (
                strategy_version_id, simulation_run_id, symbol, candle_source, candle_timestamp,
                signal, action, rejection_reason, note, fast_sma, slow_sma, prev_fast_sma,
                prev_slow_sma, close_price, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                run_id,
                TRADED_SYMBOL,
                item.source,
                iso_z(item.ts),
                item.signal,
                item.action,
                item.reason,
                item.note,
                dec_text(item.fast),
                dec_text(item.slow),
                None,
                None,
                dec_text(item.close),
                iso_z(recorded_at),
            ),
        )
    for item in replay.fills:
        result = item.result
        order = conn.execute(
            """
            INSERT INTO orders (
                strategy_version_id, simulation_run_id, decision_id, symbol, direction, intent,
                status, requested_notional, rejection_reason, simulated_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                run_id,
                None,
                result.symbol,
                result.direction,
                result.intent,
                result.status,
                dec_text(result.requested_notional),
                result.rejection_reason,
                iso_z(item.ts),
                iso_z(recorded_at),
            ),
        )
        if result.status != "filled" or result.position_id is None:
            continue
        conn.execute(
            """
            INSERT INTO fills (
                order_id, position_id, symbol, direction, intent, mark_price, fill_price,
                quantity, notional, fee, fee_rate, slippage_bps, simulated_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(order.lastrowid),
                id_map[result.position_id],
                result.symbol,
                result.direction,
                result.intent,
                dec_text(result.mark_price),
                dec_text(result.fill_price),
                dec_text(result.quantity),
                dec_text(result.notional),
                dec_text(result.fee),
                dec_text(result.fee_rate),
                dec_text(result.slippage_bps),
                iso_z(item.ts),
                iso_z(recorded_at),
            ),
        )
    for event in replay.ledger.events:
        position_id = None if event.position_id is None else id_map.get(event.position_id)
        conn.execute(
            """
            INSERT INTO ledger (
                simulation_run_id, simulated_at, recorded_at, event, symbol, direction,
                cash_free, locked_notional, cash_delta, fee, realized_pnl, unrealized_pnl,
                equity, position_id, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                iso_z(event.ts),
                iso_z(recorded_at),
                event.event,
                event.symbol,
                event.direction,
                dec_text(event.cash_free),
                dec_text(event.locked_notional),
                dec_text(event.cash_delta),
                dec_text(event.fee),
                dec_text(event.realized_pnl),
                dec_text(event.unrealized_pnl),
                dec_text(event.equity),
                position_id,
                event.note,
            ),
        )
    for point in replay.equity:
        conn.execute(
            """
            INSERT INTO equity (
                simulation_run_id, simulated_at, recorded_at, cash_free, locked_notional,
                realized_pnl, unrealized_pnl, equity, mark_symbol, mark_price, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                iso_z(point.ts),
                iso_z(recorded_at),
                dec_text(point.cash_free),
                dec_text(point.locked),
                dec_text(point.realized),
                dec_text(point.unrealized),
                dec_text(point.equity),
                TRADED_SYMBOL,
                dec_text(point.price),
                "bar_mark",
            ),
        )
