"""Replay the SMA rules over stored candles and persist the paper ledger.

Version 1.1.0 judges the signal on candle t and fills at the next candle's
open. A 1.1.0 run replaces earlier 1.1.0 rows only. sma_crossover 1.0.0 rows
stay in the database, including an open position from that book.

Train, validation, and forward are separate experiment books. Each starts
from the strategy's starting cash. They do not close the preserved 1.0.0 book.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sollab.constants import CASH_ERA_CURRENT, FILL_MODEL, MARKET_CRYPTO
from sollab.ledger import FillResult, LedgerEvent, PaperLedger, Position
from sollab.splits import PeriodWindow, full_window, plan_splits
from sollab.storage import (
    choose_candle_source,
    dec_text,
    ensure_account_rules,
    load_candles,
    record_error,
    reset_strategy_version,
    upsert_strategy,
)
from sollab.strategy import (
    Decision,
    OpenView,
    StrategyParams,
    assess,
    parameters_json,
    rules_text,
)
from sollab.timeutil import iso_z, parse_timestamp


class NoCandleData(Exception):
    """The database has no closed hourly candles for the requested symbols."""


@dataclass(frozen=True)
class Candle:
    symbol: str
    source_name: str
    endpoint: str
    source_timestamp: datetime
    open: Decimal | None
    close: Decimal


@dataclass(frozen=True)
class EquitySnap:
    ts: datetime
    cash_free: Decimal
    locked_notional: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    mark_symbol: str | None
    mark_price: Decimal | None
    note: str


@dataclass
class Applied:
    symbol: str
    source_name: str
    candle_timestamp: datetime
    close_price: Decimal
    decision: Decision
    result: FillResult | None
    fill_timestamp: datetime | None = None


@dataclass
class PeriodSummary:
    period: str
    opens: int
    closes: int
    rejected_orders: int
    decisions: int
    ending_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    open_position: str | None
    rejection_counts: dict[str, int]


@dataclass
class SimulationSummary:
    sources: dict[str, str]
    endpoints: dict[str, str]
    candle_counts: dict[str, int]
    decisions: int
    opens: int
    closes: int
    rejected_orders: int
    ending_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    open_position: str | None
    rejection_counts: dict[str, int]
    recorded_at: datetime
    warnings: list[str]
    period: str = "full_window"
    periods: list[PeriodSummary] = field(default_factory=list)


def _priority(symbol: str, symbols: tuple[str, ...]) -> int:
    try:
        return symbols.index(symbol)
    except ValueError:
        return len(symbols)


def _retarget(decision: Decision, *, reason: str | None, note: str | None) -> Decision:
    return Decision(
        decision.signal,
        decision.action,
        reason,
        note,
        decision.fast_sma,
        decision.slow_sma,
        decision.prev_fast_sma,
        decision.prev_slow_sma,
    )


def _intent(action: str) -> str:
    return "open" if action.startswith("open") else "close"


def _direction(action: str) -> str:
    if action in {"open_long", "close_long"}:
        return "long"
    return "short"


def _unfilled(ledger: PaperLedger, item: Applied, reason: str) -> FillResult:
    unrealized, equity = ledger.snapshot(None)
    action = item.decision.action
    return FillResult(
        status="rejected",
        rejection_reason=reason,
        symbol=item.symbol,
        direction=_direction(action),
        intent=_intent(action),
        requested_notional=ledger.max_notional if _intent(action) == "open" else None,
        mark_price=item.close_price,
        fill_price=None,
        quantity=None,
        notional=None,
        fee=None,
        fee_rate=ledger.fee_rate,
        slippage_bps=ledger.slippage_bps,
        cash_free=ledger.cash_free,
        locked_notional=ledger.locked_notional,
        realized_pnl=ledger.realized_pnl,
        trade_realized_pnl=None,
        unrealized_pnl=unrealized,
        equity=equity,
        position_id=ledger.position.id if ledger.position else None,
        holding_seconds=None,
        note=None,
    )


def _execute(ledger: PaperLedger, item: Applied, mark: Decimal, ts: datetime, params: StrategyParams) -> FillResult:
    action = item.decision.action
    if action == "open_long":
        result = ledger.open_position(item.symbol, "long", mark, ts, params.max_notional, MARKET_CRYPTO)
    elif action == "open_short":
        result = ledger.open_position(item.symbol, "short", mark, ts, params.max_notional, MARKET_CRYPTO)
    elif action == "close_long":
        result = ledger.close_position(item.symbol, "long", mark, ts, MARKET_CRYPTO)
    elif action == "close_short":
        result = ledger.close_position(item.symbol, "short", mark, ts, MARKET_CRYPTO)
    else:
        raise RuntimeError(f"no fill for action {action}")
    if (
        result.status == "filled"
        and result.intent == "open"
        and result.notional is not None
        and result.notional > params.max_notional
    ):
        raise RuntimeError(f"notional cap violated: {result.notional}")
    return result


def replay(
    candles: dict[str, list[Candle]],
    params: StrategyParams,
    window: PeriodWindow,
) -> tuple[PaperLedger, list[Applied], list[EquitySnap]]:
    events = [candle for rows in candles.values() for candle in rows if candle.source_timestamp <= window.fill_end]
    events.sort(key=lambda candle: (candle.source_timestamp, _priority(candle.symbol, params.symbols), candle.symbol))
    if not events:
        raise NoCandleData("no closed candles to replay")

    ledger = PaperLedger(
        starting_cash=params.starting_cash,
        max_notional=params.max_notional,
        min_notional=params.min_notional,
        fee_rate=params.fee_rate,
        slippage_bps=params.slippage_bps,
    )
    ledger.seed(events[0].source_timestamp)
    histories: dict[str, list[Decimal]] = {symbol: [] for symbol in candles}
    last_marks: dict[str, Decimal] = {}
    applied: list[Applied] = []
    pending: list[Applied] = []
    equity: list[EquitySnap] = []

    def snap(ts: datetime, note: str) -> None:
        if ledger.position is None:
            unrealized, account_equity = ledger.snapshot(None)
            equity.append(_snap(ts, ledger, unrealized, account_equity, None, None, note))
            return
        mark = last_marks.get(ledger.position.symbol)
        unrealized, account_equity = ledger.snapshot(mark)
        equity.append(
            _snap(ts, ledger, unrealized, account_equity, ledger.position.symbol, mark, note)
        )

    snap(events[0].source_timestamp, "seed")
    index = 0
    while index < len(events):
        timestamp = events[index].source_timestamp
        bar: list[Candle] = []
        while index < len(events) and events[index].source_timestamp == timestamp:
            bar.append(events[index])
            index += 1
        by_symbol = {candle.symbol: candle for candle in bar}
        still_pending: list[Applied] = []
        ready: list[tuple[Applied, Candle]] = []
        for item in pending:
            candle = by_symbol.get(item.symbol)
            if candle is None:
                still_pending.append(item)
                continue
            if candle.open is None:
                item.fill_timestamp = timestamp
                item.decision = _retarget(item.decision, reason="missing_open", note="next_candle_open_missing")
                item.result = _unfilled(ledger, item, "missing_open")
                continue
            ready.append((item, candle))
        pending = still_pending
        ready.sort(key=lambda pair: (_priority(pair[0].symbol, params.symbols), pair[0].symbol))
        for item, candle in ready:
            assert candle.open is not None
            result = _execute(ledger, item, candle.open, timestamp, params)
            item.fill_timestamp = timestamp
            item.result = result
            last_marks[item.symbol] = candle.open
            if result.status == "rejected":
                item.decision = _retarget(
                    item.decision,
                    reason=result.rejection_reason,
                    note="next_candle_open_rejected",
                )
            else:
                previous = item.decision.note
                note = "filled_next_candle_open"
                if previous:
                    note = f"{previous}; {note}"
                item.decision = _retarget(item.decision, reason=None, note=note)
        for candle in bar:
            histories[candle.symbol].append(candle.close)
            last_marks[candle.symbol] = candle.close
        if not (window.signal_start <= timestamp <= window.signal_end):
            snap(timestamp, "warmup_or_gap")
            continue
        for candle in bar:
            view = None
            if ledger.position is not None:
                view = OpenView(ledger.position.symbol, ledger.position.direction)
            decision = assess(histories[candle.symbol], params, view, candle.symbol)
            item = Applied(
                symbol=candle.symbol,
                source_name=candle.source_name,
                candle_timestamp=candle.source_timestamp,
                close_price=candle.close,
                decision=decision,
                result=None,
            )
            applied.append(item)
            if decision.action in {"open_long", "open_short", "close_long", "close_short"}:
                previous = decision.note
                note = "pending_next_candle_open"
                if previous:
                    note = f"{previous}; {note}"
                item.decision = _retarget(decision, reason=None, note=note)
                pending.append(item)
        snap(timestamp, "signal")
    for item in pending:
        item.decision = _retarget(item.decision, reason="no_next_candle", note="no_next_candle")
        item.result = _unfilled(ledger, item, "no_next_candle")
    return ledger, applied, equity


def _snap(
    ts: datetime,
    ledger: PaperLedger,
    unrealized: Decimal,
    account_equity: Decimal,
    mark_symbol: str | None,
    mark_price: Decimal | None,
    note: str,
) -> EquitySnap:
    return EquitySnap(
        ts=ts,
        cash_free=ledger.cash_free,
        locked_notional=ledger.locked_notional,
        realized_pnl=ledger.realized_pnl,
        unrealized_pnl=unrealized,
        equity=account_equity,
        mark_symbol=mark_symbol,
        mark_price=mark_price,
        note=note,
    )


def _candle_from_row(row: sqlite3.Row) -> Candle:
    if row["source_timestamp"] is None:
        raise ValueError(f"{row['symbol']} candle is missing a source timestamp")
    open_price = Decimal(row["open"]) if row["open"] is not None else None
    return Candle(
        symbol=row["symbol"],
        source_name=row["source_name"],
        endpoint=row["endpoint"],
        source_timestamp=parse_timestamp(row["source_timestamp"]),
        open=open_price,
        close=Decimal(row["close"]),
    )


def _slice(candles: dict[str, list[Candle]], window: PeriodWindow) -> dict[str, list[Candle]]:
    sliced: dict[str, list[Candle]] = {}
    for symbol, rows in candles.items():
        kept = [row for row in rows if row.source_timestamp <= window.fill_end]
        if kept:
            sliced[symbol] = kept
    return sliced


def run_strategy(
    conn: sqlite3.Connection,
    params: StrategyParams | None = None,
    recorded_at: datetime | None = None,
) -> SimulationSummary:
    params = params or StrategyParams()
    recorded_at = recorded_at or datetime.now(timezone.utc)
    loaded: dict[str, list[Candle]] = {}
    sources: dict[str, str] = {}
    endpoints: dict[str, str] = {}
    warnings: list[str] = []
    for symbol in params.symbols:
        source = choose_candle_source(conn, symbol, params.source_preference)
        if source is None:
            message = f"no closed 1h candles stored for {symbol}"
            warnings.append(message)
            with conn:
                record_error(conn, "run-strategy", message, None, recorded_at)
            continue
        rows = [_candle_from_row(row) for row in load_candles(conn, symbol, source)]
        if not rows:
            message = f"{symbol} source {source} returned no candle rows"
            warnings.append(message)
            with conn:
                record_error(conn, "run-strategy", message, None, recorded_at)
            continue
        loaded[symbol] = rows
        sources[symbol] = source
        endpoints[symbol] = rows[0].endpoint
    if not loaded:
        raise NoCandleData("no closed 1h candles stored; run collect first")

    timestamps = [candle.source_timestamp for rows in loaded.values() for candle in rows]
    windows = plan_splits(timestamps)
    if windows is None:
        windows = [full_window(timestamps)]
        warnings.append(
            "series is too short for a 60/20/remainder split with a one-bar gap; stored as full_window"
        )
    period_summaries: list[PeriodSummary] = []
    headline: SimulationSummary | None = None
    with conn:
        ensure_account_rules(conn, recorded_at)
        reset_strategy_version(conn, params.strategy_id, params.version)
        version_id = upsert_strategy(
            conn,
            strategy_id=params.strategy_id,
            version=params.version,
            name=params.name,
            parameters_json=parameters_json(params),
            rules_text=rules_text(params),
            created_at=recorded_at,
        )
        for window in windows:
            sliced = _slice(loaded, window)
            ledger, applied, equity = replay(sliced, params, window)
            summary = _summarize(ledger, applied, equity, sources, endpoints, recorded_at, warnings)
            summary.period = window.name
            summary.candle_counts = {symbol: len(rows) for symbol, rows in sliced.items()}
            _persist(conn, params, version_id, ledger, applied, equity, summary, window)
            period_summaries.append(
                PeriodSummary(
                    period=window.name,
                    opens=summary.opens,
                    closes=summary.closes,
                    rejected_orders=summary.rejected_orders,
                    decisions=summary.decisions,
                    ending_equity=summary.ending_equity,
                    realized_pnl=summary.realized_pnl,
                    unrealized_pnl=summary.unrealized_pnl,
                    open_position=summary.open_position,
                    rejection_counts=dict(summary.rejection_counts),
                )
            )
            if window.name in {"forward", "full_window"}:
                headline = summary
    if headline is None:
        raise RuntimeError("replay produced no period")
    headline.periods = period_summaries
    headline.candle_counts = {symbol: len(rows) for symbol, rows in loaded.items()}
    headline.warnings = warnings
    return headline


def _summarize(
    ledger: PaperLedger,
    applied: list[Applied],
    equity: list[EquitySnap],
    sources: dict[str, str],
    endpoints: dict[str, str],
    recorded_at: datetime,
    warnings: list[str],
) -> SimulationSummary:
    rejection_counts: dict[str, int] = {}
    opens = closes = rejected_orders = 0
    for item in applied:
        if item.decision.rejection_reason:
            rejection_counts[item.decision.rejection_reason] = (
                rejection_counts.get(item.decision.rejection_reason, 0) + 1
            )
        if item.result is None:
            continue
        if item.result.status == "rejected":
            rejected_orders += 1
        elif item.result.intent == "open":
            opens += 1
        elif item.result.intent == "close":
            closes += 1
    last = equity[-1]
    open_position = None
    if ledger.position is not None:
        open_position = f"{ledger.position.direction} {ledger.position.symbol}"
    return SimulationSummary(
        sources=sources,
        endpoints=endpoints,
        candle_counts={},
        decisions=len(applied),
        opens=opens,
        closes=closes,
        rejected_orders=rejected_orders,
        ending_equity=last.equity,
        realized_pnl=last.realized_pnl,
        unrealized_pnl=last.unrealized_pnl,
        open_position=open_position,
        rejection_counts=rejection_counts,
        recorded_at=recorded_at,
        warnings=list(warnings),
    )


def _persist(
    conn: sqlite3.Connection,
    params: StrategyParams,
    version_id: int,
    ledger: PaperLedger,
    applied: list[Applied],
    equity: list[EquitySnap],
    summary: SimulationSummary,
    window: PeriodWindow,
) -> None:
    note = (
        f"Paper replay period={window.name}. Next-candle open fills. Cash era {CASH_ERA_CURRENT}. "
        "Fast and slow windows were fixed before this run and were not fit on validation or forward. "
        "This experiment book does not close preserved sma_crossover 1.0.0 positions or cash_era 300 rows. "
        "Not live orders and not exchange fills."
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
            iso_z(summary.recorded_at),
            parameters_json(params),
            json.dumps({"sources": summary.sources, "endpoints": summary.endpoints}, sort_keys=True),
            json.dumps(summary.candle_counts, sort_keys=True),
            dec_text(params.starting_cash),
            dec_text(summary.ending_equity),
            dec_text(summary.realized_pnl),
            dec_text(summary.unrealized_pnl),
            note,
            window.name,
            FILL_MODEL,
            "experiment",
            json.dumps(window.as_dict(), sort_keys=True),
            CASH_ERA_CURRENT,
        ),
    )
    run_id = int(cursor.lastrowid)
    id_map = _insert_positions(conn, version_id, run_id, ledger, summary.recorded_at)
    for item in applied:
        decision_id = _insert_decision(conn, version_id, run_id, item, summary.recorded_at)
        if item.result is not None:
            _insert_order(conn, version_id, run_id, decision_id, item, summary.recorded_at, id_map)
    for event in ledger.events:
        _insert_ledger(conn, run_id, event, summary.recorded_at, id_map)
    for snap in equity:
        _insert_equity(conn, run_id, snap, summary.recorded_at)


def _insert_positions(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    ledger: PaperLedger,
    recorded_at: datetime,
) -> dict[int, int]:
    positions: list[Position] = list(ledger.closed_positions)
    positions.extend(ledger.positions.values())
    mapping: dict[int, int] = {}
    for position in positions:
        cursor = conn.execute(
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
        mapping[position.id] = int(cursor.lastrowid)
    return mapping


def _insert_decision(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    item: Applied,
    recorded_at: datetime,
) -> int:
    cursor = conn.execute(
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
            item.symbol,
            item.source_name,
            iso_z(item.candle_timestamp),
            item.decision.signal,
            item.decision.action,
            item.decision.rejection_reason,
            item.decision.note,
            dec_text(item.decision.fast_sma),
            dec_text(item.decision.slow_sma),
            dec_text(item.decision.prev_fast_sma),
            dec_text(item.decision.prev_slow_sma),
            dec_text(item.close_price),
            iso_z(recorded_at),
        ),
    )
    return int(cursor.lastrowid)


def _insert_order(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    decision_id: int,
    item: Applied,
    recorded_at: datetime,
    id_map: dict[int, int],
) -> None:
    result = item.result
    if result is None:
        return
    simulated_at = item.fill_timestamp or item.candle_timestamp
    cursor = conn.execute(
        """
        INSERT INTO orders (
            strategy_version_id, simulation_run_id, decision_id, symbol, direction, intent,
            status, requested_notional, rejection_reason, simulated_at, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            run_id,
            decision_id,
            result.symbol,
            result.direction,
            result.intent,
            result.status,
            dec_text(result.requested_notional),
            result.rejection_reason,
            iso_z(simulated_at),
            iso_z(recorded_at),
        ),
    )
    if result.status != "filled" or result.fill_price is None or result.position_id is None:
        return
    conn.execute(
        """
        INSERT INTO fills (
            order_id, position_id, symbol, direction, intent, mark_price, fill_price,
            quantity, notional, fee, fee_rate, slippage_bps, simulated_at, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(cursor.lastrowid),
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
            iso_z(simulated_at),
            iso_z(recorded_at),
        ),
    )


def _insert_ledger(
    conn: sqlite3.Connection,
    run_id: int,
    event: LedgerEvent,
    recorded_at: datetime,
    id_map: dict[int, int],
) -> None:
    position_id = None if event.position_id is None else id_map.get(event.position_id, event.position_id)
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


def _insert_equity(
    conn: sqlite3.Connection,
    run_id: int,
    snap: EquitySnap,
    recorded_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO equity (
            simulation_run_id, simulated_at, recorded_at, cash_free, locked_notional,
            realized_pnl, unrealized_pnl, equity, mark_symbol, mark_price, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            iso_z(snap.ts),
            iso_z(recorded_at),
            dec_text(snap.cash_free),
            dec_text(snap.locked_notional),
            dec_text(snap.realized_pnl),
            dec_text(snap.unrealized_pnl),
            dec_text(snap.equity),
            snap.mark_symbol,
            dec_text(snap.mark_price),
            snap.note,
        ),
    )
