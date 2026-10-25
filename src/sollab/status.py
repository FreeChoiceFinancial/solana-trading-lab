"""Machine-readable paper-account status.

Current books use account_rules 3.0.0: 5000 USD shared cash, one open position
per market, 10 USD notional cap. cash_era 300 rows are the earlier account.
They stay in historical_300 and are not mixed into the current backtest or
forward rollups. Experiment replays do not close the historical book.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from sollab.constants import CASH_ERA_CURRENT, CASH_ERA_PRIOR, DISCLAIMER, STARTING_CASH
from sollab.storage import ensure_account_rules
from sollab.timeutil import iso_z

MONEY = Decimal("0.00000001")


def build_status(conn: sqlite3.Connection, *, recorded_at: datetime | None = None) -> dict[str, object]:
    recorded_at = recorded_at or datetime.now(timezone.utc)
    with conn:
        ensure_account_rules(conn, recorded_at)
    runs = [
        _run_metrics(conn, row)
        for row in conn.execute(
            """
            SELECT simulation_runs.*, strategy_versions.strategy_id, strategy_versions.version,
                   strategy_versions.name
            FROM simulation_runs
            JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
            ORDER BY simulation_runs.id
            """
        ).fetchall()
    ]
    historical = [run for run in runs if run["cash_era"] == CASH_ERA_PRIOR]
    current = [run for run in runs if run["cash_era"] != CASH_ERA_PRIOR]
    backtest = [run for run in current if run["period"] != "forward"]
    forward = [run for run in current if run["period"] == "forward"]
    return {
        "disclaimer": DISCLAIMER,
        "generated_at": iso_z(recorded_at),
        "account_rules": _account_rules(conn),
        "shared_account": _shared_account(conn, historical),
        "historical_300": {
            "cash_era": CASH_ERA_PRIOR,
            "label": "300_usd_starting_cash",
            "note": "Preserved paper results from the 300 USD account. Not recalculated at 5000 USD.",
            "runs": historical,
        },
        "backtest": backtest,
        "forward": forward,
        "backtest_rollup": _rollup(backtest),
        "forward_rollup": _rollup(forward),
        "pumpfun": _pump_status(conn),
        "last_successful_collection": {
            "prices_fetched_at": _max_text(conn, "SELECT MAX(fetched_at) AS ts FROM prices"),
            "pumpfun_fetched_at": _max_text(conn, "SELECT MAX(fetched_at) AS ts FROM pump_snapshots"),
        },
        "errors": _errors(conn),
    }


def write_status(
    conn: sqlite3.Connection,
    directory: str | Path,
    *,
    recorded_at: datetime | None = None,
    status: dict[str, object] | None = None,
) -> Path:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    status = status or build_status(conn, recorded_at=recorded_at)
    json_path = destination / "status.json"
    md_path = destination / "status.md"
    json_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    md_path.write_text(format_status_markdown(status) + "\n", encoding="utf-8")
    return json_path


def format_status_markdown(status: dict[str, object]) -> str:
    account = status["shared_account"]
    assert isinstance(account, dict)
    rules = status["account_rules"]
    assert isinstance(rules, dict)
    lines = [
        "sollab status",
        str(status["disclaimer"]),
        "",
        f"Account rules {rules.get('version')} — {rules.get('summary')}",
        (
            f"Shared cash free {account.get('cash_free')} locked {account.get('locked_notional')} "
            f"equity {account.get('equity')} realized {account.get('realized_pnl')} "
            f"unrealized {account.get('unrealized_pnl')} fees {account.get('fees')}"
        ),
        str(account.get("note")),
        "Current open positions:",
    ]
    opens = account.get("open_positions")
    if not isinstance(opens, list) or not opens:
        lines.append("- none")
    else:
        for position in opens:
            assert isinstance(position, dict)
            lines.append(
                "- {market} {book} {strategy_id} {strategy_version} {direction} {symbol} "
                "notional={entry_notional} opened_at={opened_at}".format(**position)
            )
    historical = status.get("historical_300")
    lines.extend(["", "Historical cash era 300"])
    if not isinstance(historical, dict) or not historical.get("runs"):
        lines.append("- none")
    else:
        lines.append(str(historical.get("note")))
        for run in historical["runs"]:
            assert isinstance(run, dict)
            lines.append(
                "- cash_era={cash_era} {strategy_id} {strategy_version} period={period} "
                "equity={equity} realized={realized_pnl} unrealized={unrealized_pnl} "
                "open={open_position}".format(**run)
            )
    remembered = account.get("historical_300")
    if isinstance(remembered, dict):
        for position in remembered.get("open_positions") or []:
            assert isinstance(position, dict)
            lines.append(
                "- open cash_era=300 {market} {direction} {symbol} notional={entry_notional}".format(**position)
            )
    lines.extend(["", "Backtest (cash era 5000)"])
    lines.extend(_section_lines(status["backtest"], status["backtest_rollup"]))
    lines.extend(["", "Forward paper"])
    lines.extend(_section_lines(status["forward"], status["forward_rollup"]))
    pump = status["pumpfun"]
    assert isinstance(pump, dict)
    lines.extend(
        [
            "",
            "pump.fun",
            f"- run={pump.get('recorded_at')} equity={pump.get('equity')} "
            f"realized={pump.get('realized_pnl')} unrealized={pump.get('unrealized_pnl')} "
            f"fees={pump.get('fees')} open={pump.get('open_position')}",
        ]
    )
    collected = status["last_successful_collection"]
    assert isinstance(collected, dict)
    errors = status["errors"]
    assert isinstance(errors, dict)
    lines.extend(
        [
            "",
            f"Last price collection {collected.get('prices_fetched_at')}",
            f"Last pump.fun collection {collected.get('pumpfun_fetched_at')}",
            f"Stored errors {errors.get('count')}",
        ]
    )
    latest = errors.get("latest")
    if isinstance(latest, list):
        for error in latest[:5]:
            assert isinstance(error, dict)
            lines.append(f"- {error.get('ts')} {error.get('component')}: {error.get('message')}")
    return "\n".join(lines)


def _section_lines(runs: object, rollup: object) -> list[str]:
    lines: list[str] = []
    if not isinstance(runs, list) or not runs:
        lines.append("- none")
    else:
        for run in runs:
            assert isinstance(run, dict)
            lines.append(
                "- cash_era={cash_era} {strategy_id} {strategy_version} period={period} book={book} "
                "equity={equity} realized={realized_pnl} unrealized={unrealized_pnl} "
                "fees={fees} win_rate={win_rate} profit_factor={profit_factor} "
                "max_drawdown={max_drawdown} open={open_position}".format(**run)
            )
    if isinstance(rollup, dict):
        lines.append(
            "Rollup closed={closed_trades} win_rate={win_rate} profit_factor={profit_factor} "
            "realized={realized_pnl} by_direction={by_direction} by_market={by_market} "
            "by_strategy={by_strategy}".format(**rollup)
        )
    return lines


def _run_metrics(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    run_id = int(row["id"])
    positions = [
        dict(item)
        for item in conn.execute(
            """
            SELECT symbol, direction, status, entry_notional, entry_fee, exit_fee, realized_pnl,
                   opened_at, closed_at, holding_seconds, COALESCE(market, 'crypto_spot') AS market
            FROM positions
            WHERE simulation_run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
    ]
    closed = [item for item in positions if item["status"] == "closed"]
    stats = _stats(closed)
    drawdown, drawdown_fraction = _drawdown(conn, run_id)
    fee_total = _sum_column(
        conn,
        """
        SELECT fills.fee AS value
        FROM fills
        JOIN orders ON orders.id = fills.order_id
        WHERE orders.simulation_run_id = ?
        """,
        run_id,
    )
    open_rows = [item for item in positions if item["status"] == "open"]
    open_position = None
    if open_rows:
        first = open_rows[0]
        open_position = f"{first['direction']} {first['symbol']}"
    return {
        "strategy_id": row["strategy_id"],
        "strategy_version": row["version"],
        "strategy_name": row["name"],
        "period": row["period"],
        "book": row["book"],
        "fill_model": row["fill_model"],
        "cash_era": _era(row["cash_era"], row["starting_cash"]),
        "starting_cash": row["starting_cash"],
        "recorded_at": row["recorded_at"],
        "window": json.loads(row["window_json"]) if row["window_json"] else None,
        "equity": row["ending_equity"],
        "realized_pnl": row["realized_pnl"],
        "unrealized_pnl": row["unrealized_pnl"],
        "fees": _money(fee_total),
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "max_drawdown": drawdown,
        "max_drawdown_fraction": drawdown_fraction,
        "closed_trades": stats["closed_trades"],
        "open_position": open_position,
        "open_positions": [
            {
                "market": item["market"],
                "symbol": item["symbol"],
                "direction": item["direction"],
                "entry_notional": item["entry_notional"],
                "opened_at": item["opened_at"],
            }
            for item in open_rows
        ],
        "by_direction": _grouped(closed, "direction"),
        "by_market": _grouped(closed, "market"),
    }


def _rollup(runs: list[dict[str, object]]) -> dict[str, object]:
    closed: list[dict[str, object]] = []
    for run in runs:
        by_direction = run.get("by_direction")
        if not isinstance(by_direction, dict):
            continue
        for direction, stats in by_direction.items():
            if not isinstance(stats, dict):
                continue
            count = int(stats["closed_trades"])
            # Rollups recompute from the run's grouped stats only when the raw rows
            # are not attached. The grouped stats already carry the sums we need.
            closed.append(
                {
                    "direction": direction,
                    "market": None,
                    "strategy": f"{run['strategy_id']} {run['strategy_version']}",
                    "realized_pnl": stats["realized_pnl"],
                    "closed_trades": count,
                    "wins": int(stats["wins"]),
                    "losses": int(stats["losses"]),
                    "gross_profit": stats["gross_profit"],
                    "gross_loss": stats["gross_loss"],
                }
            )
    return _combine(closed, runs)


def _combine(groups: list[dict[str, object]], runs: list[dict[str, object]]) -> dict[str, object]:
    closed = sum(int(item["closed_trades"]) for item in groups)
    wins = sum(int(item["wins"]) for item in groups)
    losses = sum(int(item["losses"]) for item in groups)
    realized = sum((_decimal(item["realized_pnl"]) for item in groups), Decimal(0))
    gross_profit = sum((_decimal(item["gross_profit"]) for item in groups), Decimal(0))
    gross_loss = sum((_decimal(item["gross_loss"]) for item in groups), Decimal(0))
    return {
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": _ratio(Decimal(wins), Decimal(closed)) if closed else None,
        "profit_factor": _ratio(gross_profit, gross_loss) if gross_loss > 0 else None,
        "realized_pnl": _money(realized),
        "by_direction": _fold(groups, "direction"),
        "by_market": _fold_runs(runs, "by_market"),
        "by_strategy": _fold(groups, "strategy"),
    }


def _fold(groups: list[dict[str, object]], key: str) -> dict[str, object]:
    folded: dict[str, list[dict[str, object]]] = {}
    for item in groups:
        name = item.get(key)
        if not isinstance(name, str):
            continue
        folded.setdefault(name, []).append(item)
    output: dict[str, object] = {}
    for name, items in folded.items():
        closed = sum(int(item["closed_trades"]) for item in items)
        wins = sum(int(item["wins"]) for item in items)
        realized = sum((_decimal(item["realized_pnl"]) for item in items), Decimal(0))
        gross_profit = sum((_decimal(item["gross_profit"]) for item in items), Decimal(0))
        gross_loss = sum((_decimal(item["gross_loss"]) for item in items), Decimal(0))
        output[name] = {
            "closed_trades": closed,
            "wins": wins,
            "win_rate": _ratio(Decimal(wins), Decimal(closed)) if closed else None,
            "profit_factor": _ratio(gross_profit, gross_loss) if gross_loss > 0 else None,
            "realized_pnl": _money(realized),
        }
    return output


def _fold_runs(runs: list[dict[str, object]], field_name: str) -> dict[str, object]:
    groups: list[dict[str, object]] = []
    for run in runs:
        nested = run.get(field_name)
        if not isinstance(nested, dict):
            continue
        for name, stats in nested.items():
            if not isinstance(stats, dict):
                continue
            groups.append(
                {
                    "market": name,
                    "closed_trades": int(stats["closed_trades"]),
                    "wins": int(stats["wins"]),
                    "realized_pnl": stats["realized_pnl"],
                    "gross_profit": stats["gross_profit"],
                    "gross_loss": stats["gross_loss"],
                }
            )
    return _fold(groups, "market")


def _shared_account(conn: sqlite3.Connection, historical_runs: list[dict[str, object]]) -> dict[str, object]:
    opens = _open_positions(conn, CASH_ERA_CURRENT, include_experiments=False)
    historical_opens = _open_positions(conn, CASH_ERA_PRIOR, include_experiments=True)
    run = conn.execute(
        """
        SELECT simulation_runs.*, strategy_versions.strategy_id, strategy_versions.version
        FROM simulation_runs
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        WHERE COALESCE(simulation_runs.cash_era, '5000') = '5000'
          AND COALESCE(simulation_runs.book, 'live') != 'experiment'
        ORDER BY simulation_runs.id DESC
        LIMIT 1
        """
    ).fetchone()
    starting = format(STARTING_CASH, "f")
    if run is None:
        account = {
            "account_rules_version": "3.0.0",
            "cash_era": CASH_ERA_CURRENT,
            "starting_cash": starting,
            "cash_free": starting,
            "locked_notional": "0",
            "equity": starting,
            "realized_pnl": "0",
            "unrealized_pnl": "0",
            "fees": "0",
            "max_notional_per_position": "10",
            "open_positions": opens,
        }
    else:
        ledger = conn.execute(
            """
            SELECT cash_free, locked_notional
            FROM ledger
            WHERE simulation_run_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(run["id"]),),
        ).fetchone()
        fee_total = _sum_column(
            conn,
            """
            SELECT fills.fee AS value
            FROM fills
            JOIN orders ON orders.id = fills.order_id
            WHERE orders.simulation_run_id = ?
            """,
            int(run["id"]),
        )
        account = {
            "account_rules_version": "3.0.0",
            "cash_era": CASH_ERA_CURRENT,
            "starting_cash": run["starting_cash"],
            "cash_free": ledger["cash_free"] if ledger is not None else run["starting_cash"],
            "locked_notional": ledger["locked_notional"] if ledger is not None else "0",
            "equity": run["ending_equity"],
            "realized_pnl": run["realized_pnl"],
            "unrealized_pnl": run["unrealized_pnl"],
            "fees": _money(fee_total),
            "max_notional_per_position": "10",
            "strategy_id": run["strategy_id"],
            "strategy_version": run["version"],
            "open_positions": opens,
        }
    account["historical_300"] = {
        "cash_era": CASH_ERA_PRIOR,
        "open_positions": historical_opens,
        "run_count": len(historical_runs),
    }
    account["note"] = (
        "Current paper account starts at 5000 USD under account_rules 3.0.0. "
        "The cap is still 10 USD notional per market. "
        "cash_era 300 results are preserved and are not part of this cash balance."
    )
    return account


def _open_positions(
    conn: sqlite3.Connection,
    cash_era: str,
    *,
    include_experiments: bool,
) -> list[dict[str, object]]:
    experiment_sql = "" if include_experiments else "AND COALESCE(simulation_runs.book, 'preserved') != 'experiment'"
    return [
        {
            "market": row["market"],
            "book": row["book"],
            "cash_era": cash_era,
            "strategy_id": row["strategy_id"],
            "strategy_version": row["version"],
            "direction": row["direction"],
            "symbol": row["symbol"],
            "entry_notional": row["entry_notional"],
            "opened_at": row["opened_at"],
        }
        for row in conn.execute(
            f"""
            SELECT positions.symbol, positions.direction, positions.entry_notional, positions.opened_at,
                   COALESCE(positions.market, 'crypto_spot') AS market,
                   COALESCE(simulation_runs.book, 'preserved') AS book,
                   strategy_versions.strategy_id, strategy_versions.version
            FROM positions
            JOIN simulation_runs ON simulation_runs.id = positions.simulation_run_id
            JOIN strategy_versions ON strategy_versions.id = positions.strategy_version_id
            WHERE positions.status = 'open'
              AND COALESCE(simulation_runs.cash_era, '5000') = ?
              {experiment_sql}
            ORDER BY positions.id
            """,
            (cash_era,),
        ).fetchall()
    ]


def _pump_status(conn: sqlite3.Connection) -> dict[str, object]:
    run = conn.execute(
        """
        SELECT pump_simulation_runs.*, strategy_versions.strategy_id, strategy_versions.version
        FROM pump_simulation_runs
        JOIN strategy_versions ON strategy_versions.id = pump_simulation_runs.strategy_version_id
        ORDER BY pump_simulation_runs.id DESC
        LIMIT 1
        """
    ).fetchone()
    if run is None:
        return {
            "strategy_id": "bonding_curve_momentum",
            "strategy_version": "1.0.0",
            "recorded_at": None,
            "equity": None,
            "realized_pnl": None,
            "unrealized_pnl": None,
            "fees": None,
            "win_rate": None,
            "profit_factor": None,
            "open_position": None,
            "by_direction": {},
        }
    closed = [
        dict(row)
        for row in conn.execute(
            """
            SELECT realized_pnl, entry_network_fee_usd, exit_network_fee_usd, status
            FROM pump_positions
            WHERE simulation_run_id = ? AND status = 'closed'
            """,
            (int(run["id"]),),
        ).fetchall()
    ]
    stats = _stats(closed)
    fees = sum(
        (
            _decimal(row["entry_network_fee_usd"]) + _decimal(row["exit_network_fee_usd"])
            for row in conn.execute(
                """
                SELECT entry_network_fee_usd, exit_network_fee_usd
                FROM pump_positions
                WHERE simulation_run_id = ?
                """,
                (int(run["id"]),),
            ).fetchall()
        ),
        Decimal(0),
    )
    open_row = conn.execute(
        """
        SELECT mint, status FROM pump_positions
        WHERE simulation_run_id = ? AND status = 'open'
        ORDER BY id LIMIT 1
        """,
        (int(run["id"]),),
    ).fetchone()
    return {
        "strategy_id": run["strategy_id"],
        "strategy_version": run["version"],
        "market": "pumpfun",
        "period": "forward",
        "book": "live",
        "cash_era": _era(run["cash_era"], run["starting_cash"]),
        "recorded_at": run["recorded_at"],
        "equity": run["ending_equity"],
        "realized_pnl": run["realized_pnl"],
        "unrealized_pnl": run["unrealized_pnl"],
        "fees": _money(fees),
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "closed_trades": stats["closed_trades"],
        "open_position": None if open_row is None else open_row["mint"],
        "by_direction": {"long": stats} if closed else {},
    }


def _account_rules(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT version, recorded_at, summary, parameters_json
        FROM config_journal
        WHERE config_id = 'account_rules'
        ORDER BY version DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"version": None, "summary": None, "parameters": None}
    return {
        "version": row["version"],
        "recorded_at": row["recorded_at"],
        "summary": row["summary"],
        "parameters": json.loads(row["parameters_json"]),
    }


def _errors(conn: sqlite3.Connection) -> dict[str, object]:
    count = int(conn.execute("SELECT COUNT(*) AS n FROM errors").fetchone()["n"])
    latest = [
        {"ts": row["ts"], "component": row["component"], "message": row["message"]}
        for row in conn.execute(
            "SELECT ts, component, message FROM errors ORDER BY id DESC LIMIT 10"
        ).fetchall()
    ]
    return {"count": count, "latest": latest}


def _grouped(rows: list[dict[str, object]], key: str) -> dict[str, object]:
    found: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        found.setdefault(str(row[key]), []).append(row)
    return {name: _stats(items) for name, items in found.items()}


def _stats(rows: list[dict[str, object]]) -> dict[str, object]:
    realized_values = [_decimal(row.get("realized_pnl")) for row in rows if row.get("realized_pnl") is not None]
    wins = [value for value in realized_values if value > 0]
    losses = [value for value in realized_values if value < 0]
    gross_profit = sum(wins, Decimal(0))
    gross_loss = sum((-value for value in losses), Decimal(0))
    closed = len(realized_values)
    return {
        "closed_trades": closed,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _ratio(Decimal(len(wins)), Decimal(closed)) if closed else None,
        "profit_factor": _ratio(gross_profit, gross_loss) if gross_loss > 0 else None,
        "realized_pnl": _money(sum(realized_values, Decimal(0))),
        "gross_profit": _money(gross_profit),
        "gross_loss": _money(gross_loss),
    }


def _drawdown(conn: sqlite3.Connection, run_id: int) -> tuple[str | None, str | None]:
    peak: Decimal | None = None
    max_dd = Decimal(0)
    max_fraction = Decimal(0)
    seen = False
    for row in conn.execute(
        "SELECT equity FROM equity WHERE simulation_run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall():
        seen = True
        equity = _decimal(row["equity"])
        if peak is None or equity > peak:
            peak = equity
        if peak is not None and peak > 0:
            drawdown = peak - equity
            if drawdown > max_dd:
                max_dd = drawdown
                max_fraction = drawdown / peak
    if not seen:
        return None, None
    return _money(max_dd), format(max_fraction.quantize(MONEY, rounding=ROUND_HALF_UP), "f")


def _sum_column(conn: sqlite3.Connection, sql: str, run_id: int) -> Decimal:
    total = Decimal(0)
    for row in conn.execute(sql, (run_id,)).fetchall():
        total += _decimal(row["value"])
    return total


def _max_text(conn: sqlite3.Connection, sql: str) -> str | None:
    row = conn.execute(sql).fetchone()
    if row is None or row["ts"] is None:
        return None
    return str(row["ts"])


def _era(cash_era: object, starting_cash: object) -> str:
    if cash_era:
        return str(cash_era)
    text = "" if starting_cash is None else str(starting_cash)
    if text == "300" or text.startswith("300."):
        return CASH_ERA_PRIOR
    return CASH_ERA_CURRENT


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def _money(value: Decimal) -> str:
    return format(value.quantize(MONEY, rounding=ROUND_HALF_UP), "f")


def _ratio(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == 0:
        return None
    return format((numerator / denominator).quantize(MONEY, rounding=ROUND_HALF_UP), "f")
