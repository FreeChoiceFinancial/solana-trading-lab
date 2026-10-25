from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sollab.models import PricePoint
from sollab.simulate import run_strategy
from sollab.storage import insert_prices
from sollab.strategy import StrategyParams

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
ENDPOINT = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600"
SOL_ENDPOINT = "https://api.exchange.coinbase.com/products/SOL-USD/candles?granularity=3600"


def _params() -> StrategyParams:
    return StrategyParams(
        fast_window=2,
        slow_window=3,
        slippage_bps=Decimal("0"),
        symbols=("BTC", "SOL"),
    )


def _candles(symbol: str, closes: list[str], endpoint: str) -> list[PricePoint]:
    points = []
    for index, close in enumerate(closes):
        stamp = START + timedelta(hours=index)
        points.append(
            PricePoint(
                symbol=symbol,
                pair=f"{symbol}-USD",
                interval="1h",
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("1"),
                source_name="coinbase_exchange",
                endpoint=endpoint,
                fetched_at=START,
                source_timestamp=stamp,
            )
        )
    return points


def _seed(conn) -> None:
    closes = ["100", "100", "100", "110", "110", "90"]
    with conn:
        insert_prices(conn, _candles("BTC", closes, ENDPOINT) + _candles("SOL", closes, SOL_ENDPOINT))


def test_replay_respects_one_position_fees_and_holding(conn):
    _seed(conn)
    summary = run_strategy(conn, _params(), recorded_at=datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert summary.opens == 1
    assert summary.closes == 1
    assert summary.open_position is None
    assert summary.sources == {"BTC": "coinbase_exchange", "SOL": "coinbase_exchange"}
    assert summary.realized_pnl != summary.unrealized_pnl
    assert summary.unrealized_pnl == Decimal("0")

    positions = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
    assert len(positions) == 1
    position = positions[0]
    assert position["symbol"] == "BTC"
    assert position["direction"] == "long"
    assert Decimal(position["entry_notional"]) <= Decimal("10")
    assert Decimal(position["entry_notional"]) >= Decimal("1")
    from sollab.ledger import q

    assert Decimal(position["entry_fee"]) == q(Decimal(position["entry_notional"]) * Decimal("0.006"))
    assert position["holding_seconds"] == 7200
    assert position["status"] == "closed"
    assert Decimal(position["realized_pnl"]) == summary.realized_pnl

    sol_fills = conn.execute("SELECT * FROM fills WHERE symbol = 'SOL'").fetchall()
    assert sol_fills == []
    blocked = conn.execute(
        """
        SELECT COUNT(*) AS n FROM decisions
        WHERE symbol = 'SOL' AND rejection_reason = 'blocked_by_open_position'
        """
    ).fetchone()["n"]
    assert blocked >= 1

    open_event = conn.execute("SELECT * FROM ledger WHERE event = 'open'").fetchone()
    assert Decimal(open_event["realized_pnl"]) == Decimal("0")
    assert Decimal(open_event["unrealized_pnl"]) < Decimal("0")
    close_event = conn.execute("SELECT * FROM ledger WHERE event = 'close'").fetchone()
    assert Decimal(close_event["realized_pnl"]) == Decimal(position["realized_pnl"])
    assert Decimal(close_event["unrealized_pnl"]) == Decimal("0")

    equity_rows = conn.execute("SELECT equity, realized_pnl, unrealized_pnl FROM equity").fetchall()
    for row in equity_rows:
        assert Decimal(row["equity"]) == Decimal(row["realized_pnl"]) + Decimal(row["unrealized_pnl"]) + Decimal("300")


def test_replay_is_stable_when_run_twice(conn):
    _seed(conn)
    run_strategy(conn, _params(), recorded_at=datetime(2026, 10, 25, tzinfo=timezone.utc))
    first = [
        dict(row)
        for row in conn.execute(
            """
            SELECT symbol, direction, intent, fill_price, notional, fee, simulated_at
            FROM fills ORDER BY simulated_at, intent
            """
        ).fetchall()
    ]
    run_strategy(conn, _params(), recorded_at=datetime(2026, 10, 25, 1, tzinfo=timezone.utc))
    second = [
        dict(row)
        for row in conn.execute(
            """
            SELECT symbol, direction, intent, fill_price, notional, fee, simulated_at
            FROM fills ORDER BY simulated_at, intent
            """
        ).fetchall()
    ]
    assert first == second
    assert conn.execute("SELECT COUNT(*) AS n FROM simulation_runs").fetchone()["n"] == 1


def test_coinbase_candles_win_over_kraken(conn):
    _seed(conn)
    kraken = _candles(
        "BTC",
        ["100", "100", "100", "110", "110", "90"],
        "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60",
    )
    replaced = []
    for point in kraken:
        replaced.append(
            PricePoint(
                symbol=point.symbol,
                pair="XXBTZUSD",
                interval="1h",
                open=point.open,
                high=point.high,
                low=point.low,
                close=point.close,
                volume=point.volume,
                source_name="kraken",
                endpoint=point.endpoint,
                fetched_at=point.fetched_at,
                source_timestamp=point.source_timestamp,
            )
        )
    with conn:
        insert_prices(conn, replaced)
    summary = run_strategy(
        conn,
        StrategyParams(fast_window=2, slow_window=3, slippage_bps=Decimal("0"), symbols=("BTC",)),
        recorded_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    assert summary.sources["BTC"] == "coinbase_exchange"
