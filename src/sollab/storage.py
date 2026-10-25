"""SQLite storage for prices, paper orders, and the research ledger."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sollab.models import PricePoint
from sollab.timeutil import iso_z

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    pair TEXT NOT NULL,
    interval TEXT NOT NULL,
    open TEXT,
    high TEXT,
    low TEXT,
    close TEXT NOT NULL,
    volume TEXT,
    source_name TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_timestamp TEXT,
    dedupe_key TEXT NOT NULL,
    UNIQUE(symbol, interval, source_name, dedupe_key)
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    id INTEGER PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    rules_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(strategy_id, version)
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    candle_sources_json TEXT NOT NULL,
    candle_counts_json TEXT NOT NULL,
    starting_cash TEXT NOT NULL,
    ending_equity TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    note TEXT NOT NULL,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    simulation_run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    candle_source TEXT NOT NULL,
    candle_timestamp TEXT NOT NULL,
    signal TEXT NOT NULL,
    action TEXT NOT NULL,
    rejection_reason TEXT,
    note TEXT,
    fast_sma TEXT,
    slow_sma TEXT,
    prev_fast_sma TEXT,
    prev_slow_sma TEXT,
    close_price TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id),
    FOREIGN KEY(simulation_run_id) REFERENCES simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    simulation_run_id INTEGER NOT NULL,
    decision_id INTEGER,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    intent TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_notional TEXT,
    rejection_reason TEXT,
    simulated_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id),
    FOREIGN KEY(decision_id) REFERENCES decisions(id)
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    intent TEXT NOT NULL,
    mark_price TEXT NOT NULL,
    fill_price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    notional TEXT NOT NULL,
    fee TEXT NOT NULL,
    fee_rate TEXT NOT NULL,
    slippage_bps TEXT NOT NULL,
    simulated_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    simulation_run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity TEXT NOT NULL,
    entry_mark TEXT NOT NULL,
    entry_fill TEXT NOT NULL,
    entry_notional TEXT NOT NULL,
    entry_fee TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_mark TEXT,
    exit_fill TEXT,
    exit_notional TEXT,
    exit_fee TEXT,
    realized_pnl TEXT,
    holding_seconds INTEGER,
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id)
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    simulation_run_id INTEGER NOT NULL,
    simulated_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    event TEXT NOT NULL,
    symbol TEXT,
    direction TEXT,
    cash_free TEXT NOT NULL,
    locked_notional TEXT NOT NULL,
    cash_delta TEXT NOT NULL,
    fee TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    equity TEXT NOT NULL,
    position_id INTEGER,
    note TEXT,
    FOREIGN KEY(simulation_run_id) REFERENCES simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY,
    simulation_run_id INTEGER NOT NULL,
    simulated_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    cash_free TEXT NOT NULL,
    locked_notional TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    equity TEXT NOT NULL,
    mark_symbol TEXT,
    mark_price TEXT,
    note TEXT,
    FOREIGN KEY(simulation_run_id) REFERENCES simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_prices_lookup
ON prices(symbol, interval, source_name, source_timestamp);
"""

TABLES = (
    "prices",
    "strategy_versions",
    "simulation_runs",
    "decisions",
    "orders",
    "fills",
    "positions",
    "ledger",
    "equity",
    "errors",
)


def connect(path: str | Path) -> sqlite3.Connection:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(destination)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def dec_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def parse_dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


def _dedupe_key(point: PricePoint) -> str:
    if point.source_timestamp is not None:
        return iso_z(point.source_timestamp)
    return f"fetch:{iso_z(point.fetched_at)}"


def insert_prices(conn: sqlite3.Connection, points: list[PricePoint]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for point in points:
        if point.close <= 0:
            raise ValueError("refusing to store a non-positive price")
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO prices (
                symbol, pair, interval, open, high, low, close, volume,
                source_name, endpoint, fetched_at, source_timestamp, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                point.symbol,
                point.pair,
                point.interval,
                dec_text(point.open),
                dec_text(point.high),
                dec_text(point.low),
                dec_text(point.close),
                dec_text(point.volume),
                point.source_name,
                point.endpoint,
                iso_z(point.fetched_at),
                iso_z(point.source_timestamp) if point.source_timestamp else None,
                _dedupe_key(point),
            ),
        )
        if conn.total_changes > before:
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def record_error(
    conn: sqlite3.Connection,
    component: str,
    message: str,
    detail: str | None,
    ts: datetime,
) -> None:
    conn.execute(
        "INSERT INTO errors (ts, component, message, detail) VALUES (?, ?, ?, ?)",
        (iso_z(ts), component, message, detail),
    )


def reset_simulation(conn: sqlite3.Connection) -> None:
    """Delete paper-trading rows. Prices and source errors stay."""
    for table in ("fills", "orders", "decisions", "positions", "ledger", "equity", "simulation_runs"):
        conn.execute(f"DELETE FROM {table}")


def upsert_strategy(
    conn: sqlite3.Connection,
    *,
    strategy_id: str,
    version: str,
    name: str,
    parameters_json: str,
    rules_text: str,
    created_at: datetime,
) -> int:
    conn.execute(
        """
        INSERT INTO strategy_versions (
            strategy_id, version, name, parameters_json, rules_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_id, version) DO UPDATE SET
            name = excluded.name,
            parameters_json = excluded.parameters_json,
            rules_text = excluded.rules_text
        """,
        (strategy_id, version, name, parameters_json, rules_text, iso_z(created_at)),
    )
    row = conn.execute(
        "SELECT id FROM strategy_versions WHERE strategy_id = ? AND version = ?",
        (strategy_id, version),
    ).fetchone()
    if row is None:
        raise RuntimeError("strategy version was not stored")
    return int(row["id"])


def choose_candle_source(
    conn: sqlite3.Connection,
    symbol: str,
    preference: tuple[str, ...],
) -> str | None:
    for name in preference:
        row = conn.execute(
            """
            SELECT 1 FROM prices
            WHERE symbol = ? AND source_name = ? AND interval = '1h'
            LIMIT 1
            """,
            (symbol, name),
        ).fetchone()
        if row is not None:
            return name
    return None


def load_candles(conn: sqlite3.Connection, symbol: str, source_name: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM prices
            WHERE symbol = ? AND source_name = ? AND interval = '1h'
            ORDER BY source_timestamp ASC, id ASC
            """,
            (symbol, source_name),
        ).fetchall()
    )


def count_rows(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        counts[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    return counts


def price_group_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT symbol, interval, source_name, COUNT(*) AS n
            FROM prices
            GROUP BY symbol, interval, source_name
            ORDER BY symbol, interval, source_name
            """
        ).fetchall()
    )
