"""Text report and CSV/JSON exports. Exports read the database; they do not fetch."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sollab.constants import DISCLAIMER
from sollab.storage import TABLES, count_rows, price_group_counts
from sollab.timeutil import iso_z

PRICE_FIELDS = (
    "symbol",
    "pair",
    "interval",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_name",
    "endpoint",
    "fetched_at",
    "source_timestamp",
)

SIMULATED_LABEL = "SIMULATED_REPLAY_NOT_LIVE_TRADES"


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, object]]:
    if table not in TABLES:
        raise ValueError(f"unknown table: {table}")
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]


def export_tables(conn: sqlite3.Connection, directory: str | Path) -> Path:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        rows = _rows(conn, table)
        json_path = destination / f"{table}.json"
        csv_path = destination / f"{table}.csv"
        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        _write_csv(csv_path, rows)
    return destination


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["id"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_price_sample(
    conn: sqlite3.Connection,
    *,
    json_path: str | Path | None,
    csv_path: str | Path | None,
    label: str,
) -> list[dict[str, object]]:
    """Write a small labeled subset of stored prices. The label is chosen by the caller."""
    selected: list[sqlite3.Row] = []
    for group in price_group_counts(conn):
        limit = 1 if group["interval"] == "spot" else 2
        selected.extend(
            conn.execute(
                """
                SELECT * FROM prices
                WHERE symbol = ? AND interval = ? AND source_name = ?
                ORDER BY source_timestamp DESC, id DESC
                LIMIT ?
                """,
                (group["symbol"], group["interval"], group["source_name"], limit),
            ).fetchall()
        )
    selected.sort(
        key=lambda row: (
            row["symbol"],
            row["interval"],
            row["source_name"],
            row["source_timestamp"] or "",
        )
    )
    public_rows = [{field: row[field] for field in PRICE_FIELDS} for row in selected]
    payload = {
        "label": label,
        "disclaimer": DISCLAIMER,
        "sample_is_subset": True,
        "note": (
            "Each row was read from the SQLite prices table after collection. "
            "fetched_at is when sollab received the HTTP body. source_timestamp is the "
            "venue timestamp: candle open time for interval 1h, ticker time or "
            "last_updated_at for spot. These values were not entered by hand."
        ),
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "full_price_group_counts": [dict(group) for group in price_group_counts(conn)],
        "full_table_counts": count_rows(conn),
        "row_count": len(public_rows),
        "rows": public_rows,
    }
    if json_path is not None:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if csv_path is not None:
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("label", *PRICE_FIELDS))
            writer.writeheader()
            for row in public_rows:
                writer.writerow({"label": label, **row})
    return public_rows


def write_simulation_summary(conn: sqlite3.Connection, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run = conn.execute("SELECT * FROM simulation_runs ORDER BY id DESC LIMIT 1").fetchone()
    payload: dict[str, object] = {
        "label": SIMULATED_LABEL,
        "disclaimer": (
            "Orders, fills, P&L, and equity in this file are a paper replay. "
            "They are not exchange fills and no order was sent."
        ),
        "generated_at": iso_z(datetime.now(timezone.utc)),
    }
    if run is None:
        payload["simulation_run"] = None
        payload["note"] = "No simulation run is stored."
    else:
        run_id = run["id"]
        payload["simulation_run"] = dict(run)
        payload["positions"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM positions WHERE simulation_run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
        payload["fills"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT fills.* FROM fills
                JOIN orders ON orders.id = fills.order_id
                WHERE orders.simulation_run_id = ?
                ORDER BY fills.id
                """,
                (run_id,),
            ).fetchall()
        ]
        payload["rejection_counts"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT rejection_reason, COUNT(*) AS n
                FROM decisions
                WHERE simulation_run_id = ? AND rejection_reason IS NOT NULL
                GROUP BY rejection_reason
                ORDER BY n DESC, rejection_reason
                """,
                (run_id,),
            ).fetchall()
        ]
        payload["ledger"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ledger WHERE simulation_run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_report(conn: sqlite3.Connection) -> str:
    lines = [
        "sollab report",
        DISCLAIMER,
        "",
        "Latest stored price in each symbol, interval, and source.",
        "fetched_at is local receipt time. source_timestamp is the venue time.",
    ]
    latest = conn.execute(
        """
        SELECT p.* FROM prices p
        JOIN (
            SELECT symbol, interval, source_name, MAX(source_timestamp) AS source_timestamp
            FROM prices
            WHERE source_timestamp IS NOT NULL
            GROUP BY symbol, interval, source_name
        ) grouped
          ON p.symbol = grouped.symbol
         AND p.interval = grouped.interval
         AND p.source_name = grouped.source_name
         AND p.source_timestamp = grouped.source_timestamp
        ORDER BY p.symbol, p.interval, p.source_name
        """
    ).fetchall()
    if not latest:
        lines.append("  no prices stored")
    for row in latest:
        lines.append(
            "  {symbol} {interval} {source_name} close={close} source_timestamp={source_timestamp} "
            "fetched_at={fetched_at} endpoint={endpoint}".format(**row)
        )
    counts = count_rows(conn)
    lines.append("")
    lines.append("Table counts: " + ", ".join(f"{name}={counts[name]}" for name in TABLES))
    run = conn.execute("SELECT * FROM simulation_runs ORDER BY id DESC LIMIT 1").fetchone()
    lines.extend(["", "Strategy replay"])
    if run is None:
        lines.append("  no simulation stored. Run: python -m sollab run-strategy")
    else:
        version = conn.execute(
            "SELECT * FROM strategy_versions WHERE id = ?",
            (run["strategy_version_id"],),
        ).fetchone()
        lines.append(f"  id={version['strategy_id']} version={version['version']} name={version['name']}")
        lines.append(f"  recorded_at={run['recorded_at']}")
        lines.append(f"  candle_sources={run['candle_sources_json']}")
        lines.append(f"  candle_counts={run['candle_counts_json']}")
        lines.append(
            f"  starting_cash={run['starting_cash']} ending_equity={run['ending_equity']} "
            f"realized_pnl={run['realized_pnl']} unrealized_pnl={run['unrealized_pnl']}"
        )
        lines.append(f"  note={run['note']}")
        lines.append("  rules:")
        for rule_line in version["rules_text"].splitlines():
            lines.append(f"    {rule_line}")
        open_rows = conn.execute(
            "SELECT * FROM positions WHERE simulation_run_id = ? AND status = 'open'",
            (run["id"],),
        ).fetchall()
        lines.append("  open positions:")
        if not open_rows:
            lines.append("    none")
        for position in open_rows:
            lines.append(
                "    {direction} {symbol} qty={quantity} entry_fill={entry_fill} "
                "opened_at={opened_at} notional={entry_notional}".format(**position)
            )
        closed = conn.execute(
            """
            SELECT * FROM positions
            WHERE simulation_run_id = ? AND status = 'closed'
            ORDER BY opened_at, id
            """,
            (run["id"],),
        ).fetchall()
        lines.append(f"  closed positions: {len(closed)}")
        for position in closed[:10]:
            lines.append(
                "    {direction} {symbol} entry={entry_fill} exit={exit_fill} "
                "realized_pnl={realized_pnl} holding_seconds={holding_seconds} "
                "opened_at={opened_at} closed_at={closed_at}".format(**position)
            )
        if len(closed) > 10:
            lines.append(f"    ... {len(closed) - 10} more closed positions")
        lines.append("  rejection reasons:")
        reasons = conn.execute(
            """
            SELECT rejection_reason, COUNT(*) AS n
            FROM decisions
            WHERE simulation_run_id = ? AND rejection_reason IS NOT NULL
            GROUP BY rejection_reason
            ORDER BY n DESC, rejection_reason
            """,
            (run["id"],),
        ).fetchall()
        if not reasons:
            lines.append("    none")
        for reason in reasons:
            lines.append(f"    {reason['rejection_reason']}: {reason['n']}")
    error_count = counts["errors"]
    lines.extend(["", f"Source errors stored: {error_count}"])
    for error in conn.execute("SELECT * FROM errors ORDER BY id DESC LIMIT 5").fetchall():
        lines.append(f"  {error['ts']} {error['component']}: {error['message']}")
    lines.append("")
    return "\n".join(lines)
