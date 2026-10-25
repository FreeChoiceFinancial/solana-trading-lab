"""Replay the SMA rules over stored candles and persist the paper ledger.

The replay is deterministic for a given price table and parameter set.
`run_strategy` replaces previous simulation rows. It does not send orders.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sollab.ledger import FillResult, LedgerEvent, PaperLedger, Position
from sollab.storage import (
    choose_candle_source,
    dec_text,
    load_candles,
    record_error,
    reset_simulation,
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


@dataclass(frozen=True)
class Applied:
    symbol: str
    source_name: str
    candle_timestamp: datetime
    close_price: Decimal
    decision: Decision
    result: FillResult | None


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


def _priority(symbol: str, symbols: tuple[str, ...]) -> int:
    try:
        return symbols.index(symbol)
    except ValueError:
        return len(symbols)


def replay(
    candles: dict[str, list[Candle]],
    params: StrategyParams,
) -> tuple[PaperLedger, list[Applied], list[EquitySnap]]:
    events = [candle for rows in candles.values() for candle in rows]
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
    equity: list[EquitySnap] = []
    unrealized, account_equity = ledger.snapshot(None)
    equity.append(
        _snap(events[0].source_timestamp, ledger, unrealized, account_equity, None, None, "seed")
    )

    index = 0
    while index < len(events):
        timestamp = events[index].source_timestamp
        bar: list[Candle] = []
        while index < len(events) and events[index].source_timestamp == timestamp:
            bar.append(events[index])
            index += 1
        view = None
        if ledger.position is not None:
            view = OpenView(ledger.position.symbol, ledger.position.direction)
        opened_this_bar = False
        for candle in bar:
            histories[candle.symbol].append(candle.close)
            last_marks[candle.symbol] = candle.close
            decision = assess(histories[candle.symbol], params, view, candle.symbol)
            if decision.action in {"open_long", "open_short"} and opened_this_bar:
                decision = Decision(
                    decision.signal,
                    "reject",
                    "blocked_by_open_position",
                    "same_timestamp_priority",
                    decision.fast_sma,
                    decision.slow_sma,
                    decision.prev_fast_sma,
                    decision.prev_slow_sma,
                )
            result: FillResult | None = None
            if decision.action == "open_long":
                result = ledger.open_position(
                    candle.symbol, "long", candle.close, candle.source_timestamp, params.max_notional
                )
            elif decision.action == "open_short":
                result = ledger.open_position(
                    candle.symbol, "short", candle.close, candle.source_timestamp, params.max_notional
                )
            elif decision.action == "close_long":
                result = ledger.close_position(candle.symbol, "long", candle.close, candle.source_timestamp)
            elif decision.action == "close_short":
                result = ledger.close_position(candle.symbol, "short", candle.close, candle.source_timestamp)
            if result is not None and result.status == "rejected":
                decision = Decision(
                    decision.signal,
                    decision.action,
                    result.rejection_reason,
                    "ledger_rejected",
                    decision.fast_sma,
                    decision.slow_sma,
                    decision.prev_fast_sma,
                    decision.prev_slow_sma,
                )
            if (
                result is not None
                and result.status == "filled"
                and result.intent == "open"
                and result.notional is not None
                and result.notional > params.max_notional
            ):
                raise RuntimeError(f"notional cap violated: {result.notional}")
            if result is not None and result.status == "filled" and result.intent == "open":
                opened_this_bar = True
            applied.append(
                Applied(
                    symbol=candle.symbol,
                    source_name=candle.source_name,
                    candle_timestamp=candle.source_timestamp,
                    close_price=candle.close,
                    decision=decision,
                    result=result,
                )
            )
            if ledger.position is None:
                unrealized, account_equity = ledger.snapshot(None)
                equity.append(
                    _snap(candle.source_timestamp, ledger, unrealized, account_equity, None, None, "flat")
                )
            else:
                mark = last_marks[ledger.position.symbol]
                unrealized, account_equity = ledger.snapshot(mark)
                equity.append(
                    _snap(
                        candle.source_timestamp,
                        ledger,
                        unrealized,
                        account_equity,
                        ledger.position.symbol,
                        mark,
                        "mark",
                    )
                )
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
    return Candle(
        symbol=row["symbol"],
        source_name=row["source_name"],
        endpoint=row["endpoint"],
        source_timestamp=parse_timestamp(row["source_timestamp"]),
        close=Decimal(row["close"]),
    )


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

    ledger, applied, equity = replay(loaded, params)
    summary = _summarize(ledger, applied, equity, sources, endpoints, recorded_at, warnings)
    summary.candle_counts = {symbol: len(rows) for symbol, rows in loaded.items()}
    _persist(conn, params, ledger, applied, equity, summary)
    return summary


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
        warnings=warnings,
    )


def _persist(
    conn: sqlite3.Connection,
    params: StrategyParams,
    ledger: PaperLedger,
    applied: list[Applied],
    equity: list[EquitySnap],
    summary: SimulationSummary,
) -> None:
    note = (
        "Paper replay of stored closed candles. Same-bar close fills. "
        "Not live orders and not exchange fills."
    )
    with conn:
        reset_simulation(conn)
        version_id = upsert_strategy(
            conn,
            strategy_id=params.strategy_id,
            version=params.version,
            name=params.name,
            parameters_json=parameters_json(params),
            rules_text=rules_text(params),
            created_at=summary.recorded_at,
        )
        cursor = conn.execute(
            """
            INSERT INTO simulation_runs (
                strategy_version_id, recorded_at, parameters_json, candle_sources_json,
                candle_counts_json, starting_cash, ending_equity, realized_pnl,
                unrealized_pnl, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        run_id = int(cursor.lastrowid)
        _insert_positions(conn, version_id, run_id, ledger, summary.recorded_at)
        for item in applied:
            decision_id = _insert_decision(conn, version_id, run_id, item, summary.recorded_at)
            if item.result is not None:
                _insert_order(conn, version_id, run_id, decision_id, item, summary.recorded_at)
        for event in ledger.events:
            _insert_ledger(conn, run_id, event, summary.recorded_at)
        for snap in equity:
            _insert_equity(conn, run_id, snap, summary.recorded_at)


def _insert_positions(
    conn: sqlite3.Connection,
    version_id: int,
    run_id: int,
    ledger: PaperLedger,
    recorded_at: datetime,
) -> None:
    positions: list[Position] = list(ledger.closed_positions)
    if ledger.position is not None:
        positions.append(ledger.position)
    for position in positions:
        conn.execute(
            """
            INSERT INTO positions (
                id, strategy_version_id, simulation_run_id, symbol, direction, quantity,
                entry_mark, entry_fill, entry_notional, entry_fee, opened_at, closed_at,
                exit_mark, exit_fill, exit_notional, exit_fee, realized_pnl, holding_seconds,
                status, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.id,
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
            ),
        )


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
) -> None:
    result = item.result
    if result is None:
        return
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
            iso_z(item.candle_timestamp),
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
            result.position_id,
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
            iso_z(item.candle_timestamp),
            iso_z(recorded_at),
        ),
    )


def _insert_ledger(
    conn: sqlite3.Connection,
    run_id: int,
    event: LedgerEvent,
    recorded_at: datetime,
) -> None:
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
            event.position_id,
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
