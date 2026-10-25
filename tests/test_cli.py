from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sollab.cli import main
from sollab.models import PricePoint
from sollab.storage import connect, insert_prices


def test_help_exits_zero():
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_cli_run_strategy_and_report(tmp_path, capsys):
    database = tmp_path / "sollab.db"
    conn = connect(database)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = []
    closes = ["100"] * 20 + ["130"] + ["50"] * 15
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
                endpoint="https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600",
                fetched_at=start,
                source_timestamp=start + timedelta(hours=index),
            )
        )
    with conn:
        insert_prices(conn, points)
    conn.close()

    assert main(["run-strategy", "--db", str(database)]) == 0
    strategy_out = capsys.readouterr().out
    assert "paper replay only" in strategy_out
    assert "opens=1" in strategy_out

    sample_json = tmp_path / "sample.json"
    summary = tmp_path / "replay.json"
    assert (
        main(
            [
                "report",
                "--db",
                str(database),
                "--export-dir",
                str(tmp_path / "exports"),
                "--sample-json",
                str(sample_json),
                "--simulation-summary",
                str(summary),
            ]
        )
        == 0
    )
    report = capsys.readouterr().out
    assert "coinbase_exchange" in report
    assert "source_timestamp=" in report
    assert "sma_crossover" in report
    assert "SIMULATED_REPLAY_NOT_LIVE_TRADES" in summary.read_text(encoding="utf-8")
    assert "TEST_FIXTURE" not in sample_json.read_text(encoding="utf-8")
    assert "STORED_PRICE_SAMPLE" in sample_json.read_text(encoding="utf-8")
