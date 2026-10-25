import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sollab.httpclient import assert_allowed_url
from sollab.ledger import PaperLedger
from sollab.metalsources import parse_coinbase_daily, parse_yahoo_chart
from sollab.metalsstrategy import aligned_silver, price_cross, ratio_cross, run_metals
from sollab.metalsstrategy import Bar
from sollab.models import PricePoint
from sollab.storage import insert_prices

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_yahoo_and_coinbase_paths_are_allowlisted():
    assert_allowed_url(
        "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1d&range=5y"
    )
    assert_allowed_url("https://api.exchange.coinbase.com/products/PAXG-USD/candles?granularity=86400")
    with pytest.raises(ValueError):
        assert_allowed_url("https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d")
    with pytest.raises(ValueError):
        assert_allowed_url("https://query2.finance.yahoo.com/v8/finance/chart/GLD")


def test_daily_parser_drops_the_forming_bar():
    fetched = datetime(2026, 10, 25, tzinfo=timezone.utc)
    open_ts = int(datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp())
    forming = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp())
    payload = [
        [open_ts, "100", "110", "101", "109", "2"],
        [forming, "109", "111", "109", "110", "1"],
    ]
    bars = parse_coinbase_daily(
        "PAXG",
        "PAXG-USD",
        payload,
        "https://api.exchange.coinbase.com/products/PAXG-USD/candles?granularity=86400",
        fetched,
        fetched,
    )
    assert len(bars) == 1
    assert bars[0].close == Decimal("109")
    assert bars[0].interval == "1d"
    assert bars[0].open == Decimal("101")


def test_yahoo_parser_keeps_source_time_and_skips_nulls():
    fetched = datetime(2026, 10, 25, 22, tzinfo=timezone.utc)
    closed = int(datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc).timestamp())
    forming = int(fetched.timestamp())
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": 366.61, "regularMarketTime": closed},
                    "timestamp": [closed, forming],
                    "indicators": {
                        "quote": [
                            {
                                "open": [368.95, None],
                                "high": [370, 371],
                                "low": [366, 365],
                                "close": [366.61, 367],
                                "volume": [100, 50],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    points = parse_yahoo_chart(
        "GLD",
        "GLD",
        payload,
        "https://query1.finance.yahoo.com/v8/finance/chart/GLD?interval=1d&range=5y",
        fetched,
        fetched,
    )
    daily = [point for point in points if point.interval == "1d"]
    spot = [point for point in points if point.interval == "spot"]
    assert len(daily) == 1
    assert daily[0].close == Decimal("366.61")
    assert daily[0].source_timestamp == datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
    assert spot[0].source_name == "yahoo_chart"


def test_future_silver_bar_does_not_change_the_ratio():
    gold = [
        Bar(START + timedelta(days=index), Decimal("100"), Decimal("100"), "coinbase_exchange", "ep")
        for index in range(5)
    ]
    early = [Bar(START, Decimal("2"), Decimal("2"), "yahoo_chart", "ep")]
    future = early + [Bar(START + timedelta(days=10), Decimal("1"), Decimal("0.01"), "yahoo_chart", "ep")]
    assert aligned_silver(gold, future, 4) == aligned_silver(gold, early, 4)
    assert ratio_cross(gold, future, 4) == ratio_cross(gold, early, 4)


def test_price_cross_uses_only_the_prefix():
    flat = [Decimal("100")] * 21
    assert price_cross(flat) == "none"
    crossed = flat + [Decimal("110")]
    assert price_cross(crossed) == "long"
    assert price_cross(crossed[:-1]) == "none"


def test_short_borrow_is_charged_on_a_metals_slot():
    ledger = PaperLedger(slippage_bps=Decimal("0"), borrow_apr=Decimal("0.365"))
    ledger.seed(T0)
    opened = ledger.open_position("PAXG", "short", Decimal("100"), T0, Decimal("10"), market="metals")
    assert opened.status == "filled"
    blocked = ledger.open_position("GLD", "long", Decimal("100"), T0, Decimal("10"), market="metals")
    assert blocked.rejection_reason == "position_already_open"
    later = T0 + timedelta(days=1)
    unrealized, equity = ledger.mark("metals", Decimal("100"), later)
    assert unrealized == Decimal("-0.07")
    assert equity == ledger.balance_equity(Decimal("100"))
    closed = ledger.close_position("PAXG", "short", Decimal("100"), later, market="metals")
    assert closed.status == "filled"
    assert closed.trade_realized_pnl == Decimal("-0.13")
    assert closed.note is not None and "borrow_fee=0.01000000" in closed.note
    assert ledger.cash_free == Decimal("4999.87")
    assert ledger.position is None


def _point(symbol: str, source: str, index: int, close: str, open_: str | None = None) -> PricePoint:
    price = Decimal(close)
    return PricePoint(
        symbol=symbol,
        pair=f"{symbol}-USD",
        interval="1d",
        open=Decimal(open_) if open_ else price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1"),
        source_name=source,
        endpoint="https://api.exchange.coinbase.com/products/PAXG-USD/candles?granularity=86400",
        fetched_at=START,
        source_timestamp=START + timedelta(days=index),
    )


def test_replay_splits_do_not_fill_on_the_signal_bar(conn):
    gold = []
    for index in range(40):
        close = "100" if index < 25 else "110"
        nxt_open = "80" if index == 26 else close
        gold.append(_point("PAXG", "coinbase_exchange", index, close, nxt_open))
    silver = [_point("SI", "yahoo_chart", index, "2") for index in range(40)]
    with conn:
        insert_prices(conn, gold + silver)
    summary = run_metals(conn, recorded_at=datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert summary.paxg_bars == 40
    periods = {item.period for item in summary.periods}
    assert periods == {"train", "validation", "forward"}
    rows = conn.execute(
        """
        SELECT strategy_versions.strategy_id, simulation_runs.period, simulation_runs.note,
               simulation_runs.window_json, simulation_runs.book, simulation_runs.cash_era
        FROM simulation_runs
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        WHERE strategy_versions.strategy_id LIKE 'metals_%'
        """
    ).fetchall()
    assert {row["strategy_id"] for row in rows} == {
        "metals_sma_trend",
        "metals_gold_silver_ratio",
        "metals_buy_hold",
    }
    assert all(row["book"] == "experiment" and row["cash_era"] == "5000" for row in rows)
    windows = {}
    for row in rows:
        if row["strategy_id"] == "metals_sma_trend":
            windows[row["period"]] = json.loads(row["window_json"])
            assert "Buy-and-hold ending equity" in row["note"]
    assert windows["train"]["fill_end"] < windows["validation"]["signal_start"]
    assert windows["validation"]["fill_end"] < windows["forward"]["signal_start"]
    fills = conn.execute(
        """
        SELECT orders.simulated_at, decisions.candle_timestamp
        FROM orders
        JOIN simulation_runs ON simulation_runs.id = orders.simulation_run_id
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        LEFT JOIN decisions ON decisions.simulation_run_id = orders.simulation_run_id
            AND decisions.candle_timestamp < orders.simulated_at
        WHERE strategy_versions.strategy_id = 'metals_sma_trend'
          AND orders.status = 'filled'
          AND orders.intent = 'open'
        """
    ).fetchall()
    assert fills
    for row in fills:
        assert row["candle_timestamp"] < row["simulated_at"]
    marked = conn.execute(
        """
        SELECT fills.mark_price, fills.fill_price
        FROM fills
        JOIN orders ON orders.id = fills.order_id
        JOIN simulation_runs ON simulation_runs.id = orders.simulation_run_id
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        WHERE strategy_versions.strategy_id = 'metals_sma_trend'
          AND orders.intent = 'open'
          AND fills.mark_price = '80'
        """
    ).fetchone()
    assert marked is not None
    assert Decimal(marked["fill_price"]) != Decimal("110")
    assert Decimal(marked["fill_price"]) > Decimal("80")
