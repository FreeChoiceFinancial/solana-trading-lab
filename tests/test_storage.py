import json
from datetime import datetime, timezone
from decimal import Decimal

from sollab.models import PricePoint
from sollab.reporting import export_tables, write_price_sample
from sollab.storage import count_rows, insert_prices, record_error
from sollab.timeutil import iso_z

FETCHED = datetime(2026, 10, 25, 16, 5, tzinfo=timezone.utc)
SOURCE_TS = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)


def _point() -> PricePoint:
    return PricePoint(
        symbol="BTC",
        pair="BTC-USD",
        interval="1h",
        open=Decimal("80547.37"),
        high=Decimal("80695.69"),
        low=Decimal("80418.78"),
        close=Decimal("80535.42"),
        volume=Decimal("77.55149066"),
        source_name="coinbase_exchange",
        endpoint="https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600",
        fetched_at=FETCHED,
        source_timestamp=SOURCE_TS,
    )


def test_price_round_trip_and_duplicate_ignore(conn):
    with conn:
        inserted, skipped = insert_prices(conn, [_point()])
    assert (inserted, skipped) == (1, 0)
    with conn:
        inserted, skipped = insert_prices(conn, [_point()])
    assert (inserted, skipped) == (0, 1)
    row = conn.execute("SELECT * FROM prices").fetchone()
    assert row["symbol"] == "BTC"
    assert row["close"] == "80535.42"
    assert row["source_name"] == "coinbase_exchange"
    assert row["endpoint"].endswith("/candles?granularity=3600")
    assert row["fetched_at"] == iso_z(FETCHED)
    assert row["source_timestamp"] == iso_z(SOURCE_TS)
    assert Decimal(row["close"]) == Decimal("80535.42")


def test_export_csv_json_round_trip(conn, tmp_path):
    with conn:
        insert_prices(conn, [_point()])
        record_error(conn, "unit", "boom", "HttpFailure", FETCHED)
    directory = export_tables(conn, tmp_path / "exports")
    prices = json.loads((directory / "prices.json").read_text(encoding="utf-8"))
    assert prices[0]["endpoint"] == _point().endpoint
    assert prices[0]["fetched_at"] == iso_z(FETCHED)
    assert prices[0]["source_timestamp"] == iso_z(SOURCE_TS)
    csv_text = (directory / "prices.csv").read_text(encoding="utf-8")
    assert "coinbase_exchange" in csv_text
    assert "80535.42" in csv_text
    errors = json.loads((directory / "errors.json").read_text(encoding="utf-8"))
    assert errors[0]["message"] == "boom"

    sample_json = tmp_path / "sample.json"
    sample_csv = tmp_path / "sample.csv"
    write_price_sample(
        conn,
        json_path=sample_json,
        csv_path=sample_csv,
        label="TEST_FIXTURE",
    )
    payload = json.loads(sample_json.read_text(encoding="utf-8"))
    assert payload["label"] == "TEST_FIXTURE"
    assert payload["row_count"] == 1
    assert payload["rows"][0]["source_timestamp"] == iso_z(SOURCE_TS)
    assert "TEST_FIXTURE" in sample_csv.read_text(encoding="utf-8")
    assert count_rows(conn)["prices"] == 1
