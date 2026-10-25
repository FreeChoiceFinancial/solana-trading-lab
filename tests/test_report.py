import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sollab.models import PricePoint
from sollab.simulate import run_strategy
from sollab.status import build_status, format_status_markdown, write_status
from sollab.storage import insert_prices, upsert_strategy
from sollab.strategy import StrategyParams

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
ENDPOINT = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600"


def _candles(closes: list[str]) -> list[PricePoint]:
    points = []
    for index, close in enumerate(closes):
        points.append(
            PricePoint(
                symbol="BTC",
                pair="BTC-USD",
                interval="1h",
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("1"),
                source_name="coinbase_exchange",
                endpoint=ENDPOINT,
                fetched_at=START,
                source_timestamp=START + timedelta(hours=index),
            )
        )
    return points


def test_status_json_splits_backtest_and_forward(conn, tmp_path):
    closes = [str(100 + (index % 5)) for index in range(20)]
    with conn:
        insert_prices(conn, _candles(closes))
    version_id = upsert_strategy(
        conn,
        strategy_id="sma_crossover",
        version="1.0.0",
        name="Hourly SMA crossover",
        parameters_json="{}",
        rules_text="same-bar close fills",
        created_at=datetime(2026, 10, 25, 9, tzinfo=timezone.utc),
    )
    conn.execute(
        """
        INSERT INTO simulation_runs (
            strategy_version_id, recorded_at, parameters_json, candle_sources_json,
            candle_counts_json, starting_cash, ending_equity, realized_pnl, unrealized_pnl, note,
            period, fill_model, book
        ) VALUES (?, '2026-10-25T09:00:00Z', '{}', '{}', '{}', '300', '297.07', '-2', '-0.93',
                  'preserved', 'full_window', 'same_bar_close', 'preserved')
        """,
        (version_id,),
    )
    run_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    conn.execute(
        """
        INSERT INTO positions (
            strategy_version_id, simulation_run_id, symbol, direction, quantity, entry_mark,
            entry_fill, entry_notional, entry_fee, opened_at, status, recorded_at, market
        ) VALUES (?, ?, 'BTC', 'short', '0.0001', '80000', '79960', '9.999', '0.06',
                  '2026-10-25T09:00:00Z', 'open', '2026-10-25T09:00:00Z', 'crypto_spot')
        """,
        (version_id, run_id),
    )
    conn.execute(
        """
        INSERT INTO ledger (
            simulation_run_id, simulated_at, recorded_at, event, symbol, direction, cash_free,
            locked_notional, cash_delta, fee, realized_pnl, unrealized_pnl, equity, note
        ) VALUES (?, '2026-10-25T09:00:00Z', '2026-10-25T09:00:00Z', 'open', 'BTC', 'short',
                  '289.94', '9.999', '-10.06', '0.06', '0', '-0.93', '297.07', 'preserved')
        """,
        (run_id,),
    )
    conn.commit()
    run_strategy(
        conn,
        StrategyParams(fast_window=2, slow_window=3, slippage_bps=Decimal("0"), symbols=("BTC",)),
        recorded_at=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
    )
    recorded = datetime(2026, 10, 25, 13, tzinfo=timezone.utc)
    status = build_status(conn, recorded_at=recorded)
    assert status["account_rules"]["version"] == "4.0.0"
    assert status["account_rules"]["parameters"]["shared_cash"] == "5000"
    assert status["account_rules"]["parameters"]["max_notional_per_position"] == "10"
    assert "metals" in status["account_rules"]["parameters"]["markets"]
    assert {run["period"] for run in status["backtest"]} >= {"train", "validation"}
    assert all(run["cash_era"] == "5000" for run in status["backtest"])
    assert [run["period"] for run in status["forward"]] == ["forward"]
    assert all(run["strategy_version"] == "1.1.0" and run["cash_era"] == "5000" for run in status["forward"])
    assert all(run["period"] != "forward" for run in status["backtest"])
    shared = status["shared_account"]
    assert shared["starting_cash"] == "5000"
    assert shared["cash_era"] == "5000"
    assert shared["max_notional_per_position"] == "10"
    assert shared["open_positions"] == []
    historical = status["historical_300"]["runs"]
    assert historical[0]["strategy_version"] == "1.0.0"
    assert historical[0]["cash_era"] == "300"
    assert historical[0]["open_position"] == "short BTC"
    assert status["forward"][0]["fill_model"] == "next_candle_open"
    assert "win_rate" in status["forward"][0]
    assert "profit_factor" in status["forward"][0]
    assert "max_drawdown" in status["forward"][0]
    assert "long" in status["forward_rollup"]["by_direction"] or "short" in status["forward_rollup"]["by_direction"] or status["forward_rollup"]["closed_trades"] == 0
    text = format_status_markdown(status)
    assert "Backtest" in text
    assert "Forward paper" in text
    assert "crypto_spot" in text
    path = write_status(conn, tmp_path, status=status)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["historical_300"]["runs"][0]["cash_era"] == "300"
    assert loaded["shared_account"]["historical_300"]["open_positions"][0]["symbol"] == "BTC"
    assert (tmp_path / "status.md").exists()
