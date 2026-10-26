"""SQLite storage for prices, paper orders, and the research ledger."""

from __future__ import annotations

import json
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
    period TEXT,
    fill_model TEXT,
    book TEXT,
    window_json TEXT,
    cash_era TEXT,
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
    market TEXT DEFAULT 'crypto_spot',
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

CREATE TABLE IF NOT EXISTS pump_snapshots (
    id INTEGER PRIMARY KEY,
    collect_id TEXT NOT NULL,
    mint TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    creator TEXT,
    pool_address TEXT,
    dex_id TEXT,
    quote_mint TEXT,
    quote_symbol TEXT,
    created_at TEXT,
    graduation_status TEXT NOT NULL,
    price_usd TEXT,
    market_cap_usd TEXT,
    fdv_usd TEXT,
    reserve_usd TEXT,
    volume_m5_usd TEXT,
    volume_h1_usd TEXT,
    volume_h24_usd TEXT,
    buys_m5 INTEGER,
    sells_m5 INTEGER,
    buyers_m5 INTEGER,
    sellers_m5 INTEGER,
    buys_h1 INTEGER,
    sells_h1 INTEGER,
    buyers_h1 INTEGER,
    sellers_h1 INTEGER,
    buys_h24 INTEGER,
    sells_h24 INTEGER,
    virtual_token_reserves TEXT,
    virtual_quote_reserves TEXT,
    real_token_reserves TEXT,
    real_quote_reserves TEXT,
    token_total_supply TEXT,
    curve_complete INTEGER,
    progress TEXT,
    decimals INTEGER,
    mint_authority TEXT,
    freeze_authority TEXT,
    token_program TEXT,
    quote_is_sol INTEGER,
    global_fee_basis_points INTEGER,
    initial_real_token_reserves TEXT,
    sol_usd TEXT,
    sol_usd_source TEXT,
    field_sources_json TEXT NOT NULL,
    source_name TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_timestamp TEXT,
    UNIQUE(mint, collect_id)
);

CREATE TABLE IF NOT EXISTS pump_flags (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    mint TEXT NOT NULL,
    flag TEXT NOT NULL,
    status TEXT NOT NULL,
    rule TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES pump_snapshots(id),
    UNIQUE(snapshot_id, flag)
);

CREATE TABLE IF NOT EXISTS pump_network_fees (
    id INTEGER PRIMARY KEY,
    collect_id TEXT NOT NULL UNIQUE,
    fetched_at TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    slot INTEGER,
    base_fee_lamports INTEGER,
    priority_micro_lamports_per_cu TEXT,
    priority_sample_count INTEGER,
    assumed_compute_units INTEGER,
    priority_fee_lamports TEXT,
    sol_usd TEXT,
    sol_usd_source TEXT,
    sol_usd_endpoint TEXT,
    global_fee_basis_points INTEGER,
    global_decode_ok INTEGER NOT NULL,
    initial_real_token_reserves TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS pump_simulation_runs (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    starting_cash TEXT NOT NULL,
    ending_equity TEXT,
    realized_pnl TEXT,
    unrealized_pnl TEXT,
    note TEXT NOT NULL,
    sma_open_json TEXT,
    inherited_cash_json TEXT,
    cash_era TEXT,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id)
);

CREATE TABLE IF NOT EXISTS pump_decisions (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    simulation_run_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    mint TEXT NOT NULL,
    snapshot_id INTEGER,
    signal_time TEXT NOT NULL,
    action TEXT NOT NULL,
    rejection_reason TEXT,
    note TEXT,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id),
    FOREIGN KEY(simulation_run_id) REFERENCES pump_simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS pump_orders (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    simulation_run_id INTEGER NOT NULL,
    decision_id INTEGER,
    market TEXT NOT NULL,
    mint TEXT NOT NULL,
    intent TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_notional TEXT,
    rejection_reason TEXT,
    simulated_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(simulation_run_id) REFERENCES pump_simulation_runs(id)
);

CREATE TABLE IF NOT EXISTS pump_fills (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    position_id INTEGER,
    market TEXT NOT NULL,
    mint TEXT NOT NULL,
    intent TEXT NOT NULL,
    signal_time TEXT NOT NULL,
    fill_time TEXT NOT NULL,
    execution_delay_seconds INTEGER NOT NULL,
    virtual_token_reserves TEXT,
    virtual_quote_reserves TEXT,
    spendable_lamports TEXT,
    net_quote_lamports TEXT,
    curve_fee_lamports TEXT,
    tokens_raw TEXT,
    token_ui TEXT,
    effective_price_usd TEXT,
    notional_usd TEXT,
    extra_slippage_bps TEXT NOT NULL,
    solana_base_lamports INTEGER,
    solana_priority_lamports TEXT,
    network_fee_usd TEXT,
    sol_usd TEXT,
    sol_usd_source TEXT,
    protocol_fee_bps INTEGER NOT NULL,
    creator_fee_bps INTEGER NOT NULL,
    simulated_label TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES pump_orders(id)
);

CREATE TABLE IF NOT EXISTS pump_positions (
    id INTEGER PRIMARY KEY,
    strategy_version_id INTEGER NOT NULL,
    simulation_run_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    mint TEXT NOT NULL,
    status TEXT NOT NULL,
    tokens_raw TEXT NOT NULL,
    token_ui TEXT NOT NULL,
    decimals INTEGER NOT NULL,
    entry_notional_usd TEXT NOT NULL,
    entry_network_fee_usd TEXT NOT NULL,
    entry_effective_price_usd TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_proceeds_usd TEXT,
    exit_network_fee_usd TEXT,
    exit_effective_price_usd TEXT,
    realized_pnl TEXT,
    exit_reason TEXT,
    holding_seconds INTEGER,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id)
);

CREATE TABLE IF NOT EXISTS pump_ledger (
    id INTEGER PRIMARY KEY,
    simulation_run_id INTEGER NOT NULL,
    simulated_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    event TEXT NOT NULL,
    market TEXT,
    mint TEXT,
    cash TEXT NOT NULL,
    cash_delta TEXT NOT NULL,
    network_fee_usd TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    unrealized_pnl TEXT,
    equity TEXT,
    note TEXT,
    FOREIGN KEY(simulation_run_id) REFERENCES pump_simulation_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_pump_snapshots_mint
ON pump_snapshots(mint, fetched_at);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY,
    job TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_journal (
    id INTEGER PRIMARY KEY,
    config_id TEXT NOT NULL,
    version TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    UNIQUE(config_id, version)
);
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
    "pump_snapshots",
    "pump_flags",
    "pump_network_fees",
    "pump_simulation_runs",
    "pump_decisions",
    "pump_orders",
    "pump_fills",
    "pump_positions",
    "pump_ledger",
    "job_runs",
    "config_journal",
)


def connect(path: str | Path) -> sqlite3.Connection:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(destination)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    if name not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _migrate(conn: sqlite3.Connection) -> None:
    """Add milestone-3 columns on databases created by earlier milestones."""
    _add_column(conn, "simulation_runs", "period", "TEXT")
    _add_column(conn, "simulation_runs", "fill_model", "TEXT")
    _add_column(conn, "simulation_runs", "book", "TEXT")
    _add_column(conn, "simulation_runs", "window_json", "TEXT")
    _add_column(conn, "positions", "market", "TEXT DEFAULT 'crypto_spot'")
    conn.execute("UPDATE positions SET market = 'crypto_spot' WHERE market IS NULL")
    conn.execute(
        """
        UPDATE simulation_runs
        SET period = 'full_window',
            fill_model = 'same_bar_close',
            book = 'preserved'
        WHERE period IS NULL AND fill_model IS NULL AND book IS NULL
        """
    )
    _add_column(conn, "simulation_runs", "cash_era", "TEXT")
    _add_column(conn, "pump_simulation_runs", "cash_era", "TEXT")
    label_cash_eras(conn)


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


def label_cash_eras(conn: sqlite3.Connection) -> None:
    """Tag stored paper books that used the 300 USD account. Newer rows set cash_era themselves."""
    conn.execute(
        """
        UPDATE simulation_runs
        SET cash_era = '300'
        WHERE cash_era IS NULL
          AND (starting_cash = '300' OR starting_cash LIKE '300.%')
        """
    )
    conn.execute(
        """
        UPDATE pump_simulation_runs
        SET cash_era = '300'
        WHERE cash_era IS NULL
          AND starting_cash NOT LIKE '5000%'
        """
    )


def reset_simulation(conn: sqlite3.Connection) -> None:
    """Delete SMA paper-trading rows. Prices, pump snapshots, and source errors stay."""
    for table in ("fills", "orders", "decisions", "positions", "ledger", "equity", "simulation_runs"):
        conn.execute(f"DELETE FROM {table}")


def reset_strategy_version(conn: sqlite3.Connection, strategy_id: str, version: str) -> None:
    """Delete one strategy version's paper rows. Other versions, prices, and pump rows stay."""
    rows = conn.execute(
        """
        SELECT simulation_runs.id
        FROM simulation_runs
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        WHERE strategy_versions.strategy_id = ? AND strategy_versions.version = ?
          AND COALESCE(simulation_runs.cash_era, '') != '300'
        """,
        (strategy_id, version),
    ).fetchall()
    run_ids = [int(row["id"]) for row in rows]
    if not run_ids:
        return
    placeholders = ",".join("?" for _ in run_ids)
    conn.execute(
        f"""
        DELETE FROM fills
        WHERE order_id IN (SELECT id FROM orders WHERE simulation_run_id IN ({placeholders}))
        """,
        run_ids,
    )
    for table in ("orders", "decisions", "positions", "ledger", "equity"):
        conn.execute(f"DELETE FROM {table} WHERE simulation_run_id IN ({placeholders})", run_ids)
    conn.execute(f"DELETE FROM simulation_runs WHERE id IN ({placeholders})", run_ids)


def ensure_account_rules(conn: sqlite3.Connection, recorded_at: datetime) -> None:
    """Record account rule versions. Existing journal rows are not rewritten."""
    label_cash_eras(conn)
    prior = conn.execute(
        """
        SELECT created_at FROM strategy_versions
        WHERE strategy_id = 'sma_crossover' AND version = '1.0.0'
        """
    ).fetchone()
    previous_time = prior["created_at"] if prior is not None else iso_z(recorded_at)
    preserved = [
        {
            "symbol": row["symbol"],
            "direction": row["direction"],
            "market": row["market"],
            "opened_at": row["opened_at"],
        }
        for row in conn.execute(
            """
            SELECT positions.symbol, positions.direction, positions.opened_at,
                   COALESCE(positions.market, 'crypto_spot') AS market
            FROM positions
            JOIN simulation_runs ON simulation_runs.id = positions.simulation_run_id
            WHERE positions.status = 'open'
              AND COALESCE(simulation_runs.book, 'preserved') = 'preserved'
            ORDER BY positions.id
            """
        ).fetchall()
    ]
    _insert_config(
        conn,
        version="1.0.0",
        recorded_at=previous_time,
        summary="One open position for the whole paper portfolio, max 10 USD notional, 300 USD cash.",
        parameters={
            "max_open_positions": 1,
            "scope": "whole_portfolio",
            "max_notional_per_position": "10",
            "shared_cash": "300",
        },
    )
    _insert_config(
        conn,
        version="2.0.0",
        recorded_at=iso_z(recorded_at),
        summary=(
            "One open position per market (crypto_spot, pumpfun, stocks). "
            "Shared 300 USD cash. Each position max 10 USD notional. "
            "Existing open positions stay in their market."
        ),
        parameters={
            "max_open_positions_per_market": 1,
            "markets": ["crypto_spot", "pumpfun", "stocks"],
            "stocks": "reserved_no_data_no_orders",
            "max_notional_per_position": "10",
            "shared_cash": "300",
            "previous_version": "1.0.0",
            "grandfathered_open_positions": preserved,
            "cash_era": "300",
        },
    )
    _insert_config(
        conn,
        version="3.0.0",
        recorded_at=iso_z(recorded_at),
        summary=(
            "Shared paper cash is 5000 USD. One open position per market still holds, "
            "and the per-position cap stays 10 USD. "
            "Earlier 300 USD books stay stored with cash_era 300 and are not recalculated."
        ),
        parameters={
            "max_open_positions_per_market": 1,
            "markets": ["crypto_spot", "pumpfun", "stocks"],
            "stocks": "reserved_no_data_no_orders",
            "max_notional_per_position": "10",
            "shared_cash": "5000",
            "cash_era": "5000",
            "previous_version": "2.0.0",
            "previous_shared_cash": "300",
            "preserved_cash_era": "300",
            "historical_open_positions_cash_era_300": preserved,
        },
    )
    _insert_config(
        conn,
        version="4.0.0",
        recorded_at=iso_z(recorded_at),
        summary=(
            "Shared paper cash stays 5000 USD and the per-position cap stays 10 USD. "
            "One open position per market now includes metals. Long and short are allowed. "
            "A metals short accrues a paper borrow rate; earlier books are not rewritten."
        ),
        parameters={
            "max_open_positions_per_market": 1,
            "markets": ["crypto_spot", "pumpfun", "stocks", "metals"],
            "stocks": "reserved_no_data_no_orders",
            "metals": "one_slot_long_or_short",
            "max_notional_per_position": "10",
            "shared_cash": "5000",
            "cash_era": "5000",
            "previous_version": "3.0.0",
            "metals_short_borrow_apr": "0.005",
            "metals_short_borrow_note": (
                "Research assumption, actual/365 on entry notional. Not a live borrow quote. "
                "Crypto and pump.fun books keep borrow_apr at 0."
            ),
        },
    )


def _insert_config(
    conn: sqlite3.Connection,
    *,
    version: str,
    recorded_at: str,
    summary: str,
    parameters: dict[str, object],
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO config_journal (
            config_id, version, recorded_at, summary, parameters_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "account_rules",
            version,
            recorded_at,
            summary,
            json.dumps(parameters, sort_keys=True),
        ),
    )


def reset_pump_simulation(conn: sqlite3.Connection) -> None:
    """Delete current-era pump.fun paper rows. cash_era 300 rows, snapshots, and the SMA book stay."""
    label_cash_eras(conn)
    rows = conn.execute(
        """
        SELECT id FROM pump_simulation_runs
        WHERE COALESCE(cash_era, '5000') != '300'
        """
    ).fetchall()
    run_ids = [int(row["id"]) for row in rows]
    if not run_ids:
        return
    placeholders = ",".join("?" for _ in run_ids)
    conn.execute(
        f"""
        DELETE FROM pump_fills
        WHERE order_id IN (SELECT id FROM pump_orders WHERE simulation_run_id IN ({placeholders}))
        """,
        run_ids,
    )
    for table in ("pump_orders", "pump_decisions", "pump_positions", "pump_ledger"):
        conn.execute(f"DELETE FROM {table} WHERE simulation_run_id IN ({placeholders})", run_ids)
    conn.execute(f"DELETE FROM pump_simulation_runs WHERE id IN ({placeholders})", run_ids)


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
