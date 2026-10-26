from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sollab.cli import main
from sollab.jobs import collection_gaps, decide, record_job_run
from sollab.status import build_status
from sollab.storage import upsert_strategy

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def test_hourly_backup_does_not_double_and_next_hour_runs(conn):
    record_job_run(conn, "hourly", datetime(2026, 10, 26, 12, 7, tzinfo=timezone.utc))
    assert decide(conn, "hourly", datetime(2026, 10, 26, 12, 37, tzinfo=timezone.utc)) == "skip"
    assert decide(conn, "hourly", datetime(2026, 10, 26, 12, 57, tzinfo=timezone.utc)) == "run"
    assert decide(conn, "hourly", datetime(2026, 10, 26, 13, 7, tzinfo=timezone.utc)) == "run"


def test_hourly_backup_success_blocks_the_following_primary(conn):
    record_job_run(conn, "hourly", datetime(2026, 10, 26, 12, 37, tzinfo=timezone.utc))
    assert decide(conn, "hourly", datetime(2026, 10, 26, 13, 7, tzinfo=timezone.utc)) == "skip"
    assert decide(conn, "hourly", datetime(2026, 10, 26, 13, 37, tzinfo=timezone.utc)) == "run"


def test_pump_backup_skips_and_the_next_two_hour_slot_runs(conn):
    record_job_run(conn, "pumpfun", datetime(2026, 10, 26, 0, 23, tzinfo=timezone.utc))
    assert decide(conn, "pumpfun", datetime(2026, 10, 26, 0, 53, tzinfo=timezone.utc)) == "skip"
    assert decide(conn, "pumpfun", datetime(2026, 10, 26, 2, 23, tzinfo=timezone.utc)) == "run"


def test_gaps_list_silence_over_two_hours_only(conn):
    record_job_run(conn, "hourly", NOW - timedelta(hours=24))
    record_job_run(conn, "hourly", NOW - timedelta(hours=22))
    record_job_run(conn, "hourly", NOW - timedelta(hours=19))
    record_job_run(conn, "hourly", NOW - timedelta(hours=1))
    status = build_status(conn, recorded_at=NOW)
    hourly_gaps = [gap for gap in status["gaps"] if gap["job"] == "hourly"]
    assert [(gap["from"], gap["to"], gap["hours"]) for gap in hourly_gaps] == [
        ("2026-10-25T14:00:00Z", "2026-10-25T17:00:00Z", "3.00"),
        ("2026-10-25T17:00:00Z", "2026-10-26T11:00:00Z", "18.00"),
    ]
    assert any(item["job"] == "hourly" and item["recorded_at"] == "2026-10-26T11:00:00Z" for item in status["job_runs"])
    exact = collection_gaps(
        [NOW - timedelta(hours=4), NOW - timedelta(hours=2), NOW],
        NOW,
        job="hourly",
    )
    assert [gap["hours"] for gap in exact] == ["20.00"]


def test_job_gate_cli_prints_run(tmp_path, capsys):
    database = tmp_path / "sollab.db"
    assert main(["job-gate", "--db", str(database), "--job", "hourly"]) == 0
    assert capsys.readouterr().out.strip() == "run"


def _version(conn, strategy_id: str, version: str) -> int:
    return upsert_strategy(
        conn,
        strategy_id=strategy_id,
        version=version,
        name=strategy_id,
        parameters_json="{}",
        rules_text="paper",
        created_at=NOW,
    )


def _simulation(
    conn,
    version_id: int,
    *,
    period: str,
    cash_era: str,
    realized: str,
    unrealized: str,
    equity: str,
) -> int:
    conn.execute(
        """
        INSERT INTO simulation_runs (
            strategy_version_id, recorded_at, parameters_json, candle_sources_json,
            candle_counts_json, starting_cash, ending_equity, realized_pnl, unrealized_pnl,
            note, period, fill_model, book, cash_era
        ) VALUES (?, ?, '{}', '{}', '{}', ?, ?, ?, ?, 'paper', ?, 'next_candle_open', 'experiment', ?)
        """,
        (version_id, "2026-10-26T12:00:00Z", cash_era if cash_era == "300" else "5000", equity, realized, unrealized, period, cash_era),
    )
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def _position(conn, version_id: int, run_id: int, *, symbol: str, direction: str, notional: str, market: str) -> None:
    conn.execute(
        """
        INSERT INTO positions (
            strategy_version_id, simulation_run_id, symbol, direction, quantity, entry_mark,
            entry_fill, entry_notional, entry_fee, opened_at, status, recorded_at, market
        ) VALUES (?, ?, ?, ?, '1', '1', '1', ?, '0', '2026-10-26T11:00:00Z', 'open',
                  '2026-10-26T11:00:00Z', ?)
        """,
        (version_id, run_id, symbol, direction, notional, market),
    )


def test_shared_account_sums_every_forward_book(conn):
    sma = _version(conn, "sma_crossover", "1.1.0")
    metals = _version(conn, "metals_sma_trend", "1.0.0")
    pump = _version(conn, "bonding_curve_momentum", "1.0.0")
    old = _version(conn, "sma_crossover", "1.0.0")

    forward_btc = _simulation(conn, sma, period="forward", cash_era="5000", realized="-0.40", unrealized="-0.10", equity="4999.50")
    _position(conn, sma, forward_btc, symbol="BTC", direction="short", notional="10", market="crypto_spot")
    forward_paxg = _simulation(conn, metals, period="forward", cash_era="5000", realized="-0.15", unrealized="0.90", equity="5000.75")
    _position(conn, metals, forward_paxg, symbol="PAXG", direction="short", notional="10", market="metals")
    train = _simulation(conn, metals, period="train", cash_era="5000", realized="3.00", unrealized="0", equity="5003")
    _position(conn, metals, train, symbol="SLV", direction="long", notional="10", market="metals")
    preserved = _simulation(conn, old, period="full_window", cash_era="300", realized="-2", unrealized="-0.93", equity="297.07")
    _position(conn, old, preserved, symbol="BTC", direction="short", notional="9.99974888", market="crypto_spot")

    conn.execute(
        """
        INSERT INTO pump_simulation_runs (
            strategy_version_id, recorded_at, parameters_json, starting_cash, ending_equity,
            realized_pnl, unrealized_pnl, note, cash_era
        ) VALUES (?, '2026-10-26T10:00:00Z', '{}', '5000', '5100', '100', '0', 'old', '5000')
        """,
        (pump,),
    )
    old_pump = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    conn.execute(
        """
        INSERT INTO pump_positions (
            strategy_version_id, simulation_run_id, market, mint, status, tokens_raw, token_ui,
            decimals, entry_notional_usd, entry_network_fee_usd, entry_effective_price_usd,
            opened_at, recorded_at
        ) VALUES (?, ?, 'pumpfun', 'OLD', 'open', '1', '1', 6, '10', '0', '1',
                  '2026-10-26T10:00:00Z', '2026-10-26T10:00:00Z')
        """,
        (pump, old_pump),
    )
    conn.execute(
        """
        INSERT INTO pump_simulation_runs (
            strategy_version_id, recorded_at, parameters_json, starting_cash, ending_equity,
            realized_pnl, unrealized_pnl, note, cash_era
        ) VALUES (?, '2026-10-26T12:00:00Z', '{}', '5000', '5000.25', '0', '0.25', 'current', '5000')
        """,
        (pump,),
    )
    current_pump = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    conn.execute(
        """
        INSERT INTO pump_positions (
            strategy_version_id, simulation_run_id, market, mint, status, tokens_raw, token_ui,
            decimals, entry_notional_usd, entry_network_fee_usd, entry_effective_price_usd,
            opened_at, recorded_at
        ) VALUES (?, ?, 'pumpfun', 'TOKEN', 'open', '1', '1', 6, '10', '0', '1',
                  '2026-10-26T12:00:00Z', '2026-10-26T12:00:00Z')
        """,
        (pump, current_pump),
    )
    conn.commit()

    shared = build_status(conn, recorded_at=NOW)["shared_account"]
    assert shared["forward_books"] == 3
    assert [(item["direction"], item["symbol"], item["market"]) for item in shared["open_positions"]] == [
        ("short", "BTC", "crypto_spot"),
        ("short", "PAXG", "metals"),
        ("long", "TOKEN", "pumpfun"),
    ]
    assert Decimal(shared["locked_notional"]) == Decimal("30")
    assert Decimal(shared["realized_pnl"]) == Decimal("-0.55")
    assert Decimal(shared["unrealized_pnl"]) == Decimal("1.05")
    assert Decimal(shared["equity"]) == Decimal("5000.50")
    assert Decimal(shared["cash_free"]) == Decimal("4969.45")
    assert shared["historical_300"]["open_positions"][0]["symbol"] == "BTC"
    assert Decimal(shared["historical_300"]["open_positions"][0]["entry_notional"]) == Decimal("9.99974888")
