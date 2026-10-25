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
    closes = ["100", "100", "100", "110", "110", "90", "90"]
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
        assert Decimal(row["equity"]) == Decimal(row["realized_pnl"]) + Decimal(row["unrealized_pnl"]) + Decimal("5000")


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


def test_fill_price_is_the_next_open(conn):
    points = []
    closes = ["100", "100", "100", "110", "110", "90", "90"]
    opens = ["100", "100", "100", "110", "80", "90", "70"]
    for index, (open_price, close) in enumerate(zip(opens, closes)):
        stamp = START + timedelta(hours=index)
        points.append(
            PricePoint(
                symbol="BTC",
                pair="BTC-USD",
                interval="1h",
                open=Decimal(open_price),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("1"),
                source_name="coinbase_exchange",
                endpoint=ENDPOINT,
                fetched_at=START,
                source_timestamp=stamp,
            )
        )
    with conn:
        insert_prices(conn, points)
    run_strategy(
        conn,
        StrategyParams(fast_window=2, slow_window=3, slippage_bps=Decimal("0"), symbols=("BTC",)),
        recorded_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    fills = conn.execute(
        "SELECT intent, mark_price, fill_price, simulated_at FROM fills ORDER BY simulated_at, intent"
    ).fetchall()
    assert [row["intent"] for row in fills] == ["open", "close"]
    assert Decimal(fills[0]["mark_price"]) == Decimal("80")
    assert Decimal(fills[0]["fill_price"]) == Decimal("80")
    assert Decimal(fills[1]["mark_price"]) == Decimal("70")
    assert fills[0]["simulated_at"] == "2026-01-01T04:00:00Z"
    signal = conn.execute(
        """
        SELECT candle_timestamp, close_price FROM decisions
        WHERE action = 'open_long' AND rejection_reason IS NULL
        """
    ).fetchone()
    assert signal["candle_timestamp"] == "2026-01-01T03:00:00Z"
    assert Decimal(signal["close_price"]) == Decimal("110")


def test_prior_version_and_open_short_are_kept(conn):
    _seed(conn)
    from sollab.storage import upsert_strategy

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
        ) VALUES (?, '2026-10-25T09:00:00Z', '{}', '{}', '{}', '300', '297', '0', '-3', 'preserved',
                  'full_window', 'same_bar_close', 'preserved')
        """,
        (version_id,),
    )
    run_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    conn.execute(
        """
        INSERT INTO positions (
            strategy_version_id, simulation_run_id, symbol, direction, quantity, entry_mark,
            entry_fill, entry_notional, entry_fee, opened_at, status, recorded_at, market
        ) VALUES (?, ?, 'BTC', 'short', '0.0001', '80000', '80000', '10', '0.06',
                  '2026-10-25T09:00:00Z', 'open', '2026-10-25T09:00:00Z', 'crypto_spot')
        """,
        (version_id, run_id),
    )
    conn.commit()
    run_strategy(conn, _params(), recorded_at=datetime(2026, 10, 25, 12, tzinfo=timezone.utc))
    preserved = conn.execute(
        """
        SELECT positions.status, positions.symbol, positions.direction, simulation_runs.fill_model
        FROM positions
        JOIN simulation_runs ON simulation_runs.id = positions.simulation_run_id
        JOIN strategy_versions ON strategy_versions.id = positions.strategy_version_id
        WHERE strategy_versions.version = '1.0.0'
        """
    ).fetchone()
    assert preserved["status"] == "open"
    assert preserved["symbol"] == "BTC"
    assert preserved["direction"] == "short"
    assert preserved["fill_model"] == "same_bar_close"
    versions = [
        row["version"]
        for row in conn.execute(
            "SELECT version FROM strategy_versions WHERE strategy_id = 'sma_crossover' ORDER BY version"
        ).fetchall()
    ]
    assert versions == ["1.0.0", "1.1.0"]
    rules = {
        row["version"]: row["parameters_json"]
        for row in conn.execute(
            "SELECT version, parameters_json FROM config_journal WHERE config_id = 'account_rules'"
        ).fetchall()
    }
    assert set(rules) == {"1.0.0", "2.0.0", "3.0.0"}
    kept = __import__("json").loads(rules["2.0.0"])["grandfathered_open_positions"]
    assert kept[0]["symbol"] == "BTC"
    assert kept[0]["direction"] == "short"
    assert kept[0]["market"] == "crypto_spot"
    current_rules = __import__("json").loads(rules["3.0.0"])
    assert current_rules["shared_cash"] == "5000"
    assert current_rules["max_notional_per_position"] == "10"
    assert current_rules["previous_shared_cash"] == "300"
    assert __import__("json").loads(rules["2.0.0"])["shared_cash"] == "300"
    era = conn.execute(
        """
        SELECT cash_era FROM simulation_runs
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        WHERE strategy_versions.version = '1.0.0'
        """
    ).fetchone()["cash_era"]
    assert era == "300"
    current = conn.execute(
        """
        SELECT DISTINCT starting_cash, cash_era
        FROM simulation_runs
        JOIN strategy_versions ON strategy_versions.id = simulation_runs.strategy_version_id
        WHERE strategy_versions.version = '1.1.0'
        """
    ).fetchall()
    assert {(row["starting_cash"], row["cash_era"]) for row in current} == {("5000", "5000")}


def test_splits_score_only_their_own_timestamps(conn):
    closes = [str(100 + (index % 5)) for index in range(20)]
    with conn:
        insert_prices(conn, _candles("BTC", closes, ENDPOINT))
    summary = run_strategy(
        conn,
        StrategyParams(fast_window=2, slow_window=3, slippage_bps=Decimal("0"), symbols=("BTC",)),
        recorded_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    assert [item.period for item in summary.periods] == ["train", "validation", "forward"]
    rows = conn.execute(
        "SELECT period, window_json, parameters_json FROM simulation_runs ORDER BY id"
    ).fetchall()
    windows = {row["period"]: __import__("json").loads(row["window_json"]) for row in rows}
    assert windows["train"]["fill_end"] < windows["validation"]["signal_start"]
    assert windows["validation"]["fill_end"] < windows["forward"]["signal_start"]
    for row in rows:
        assert __import__("json").loads(row["parameters_json"])["fast_window"] == 2
        assert __import__("json").loads(row["parameters_json"])["fill_assumption"] == "next_candle_open"
    for period, window in windows.items():
        stamps = conn.execute(
            """
            SELECT candle_timestamp FROM decisions
            JOIN simulation_runs ON simulation_runs.id = decisions.simulation_run_id
            WHERE simulation_runs.period = ?
            """,
            (period,),
        ).fetchall()
        for stamp in stamps:
            assert window["signal_start"] <= stamp["candle_timestamp"] <= window["signal_end"]
        fills = conn.execute(
            """
            SELECT orders.simulated_at FROM orders
            JOIN simulation_runs ON simulation_runs.id = orders.simulation_run_id
            WHERE simulation_runs.period = ? AND orders.status = 'filled'
            """,
            (period,),
        ).fetchall()
        for fill in fills:
            assert window["signal_start"] < fill["simulated_at"] <= window["fill_end"]


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
