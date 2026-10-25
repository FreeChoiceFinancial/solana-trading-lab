import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from sollab.collect import collect
from sollab.httpclient import HttpFailure, assert_allowed_url, fetch_json
from sollab.sources import (
    fetch_kraken_ohlc,
    parse_coinbase_candles,
    parse_coinbase_ticker,
    parse_coingecko_simple,
    parse_kraken_ohlc,
)
from sollab.timeutil import parse_timestamp

# Payloads captured from the public APIs on 2026-10-25. They are fixtures for
# the parser, not a substitute for the live collector.
COINBASE_TICKER = (
    '{"ask":"80532.3","bid":"80532.29","volume":"2346.75164125","trade_id":1110478087,'
    '"price":"80532.3","size":"0.00323463","time":"2026-10-25T15:58:53.942062143Z",'
    '"rfq_volume":"78.491974"}'
)
COINBASE_CANDLE = [1792940400, Decimal("80418.78"), Decimal("80695.69"), Decimal("80547.37"), Decimal("80535.42"), Decimal("77.55149066")]
COINGECKO = {
    "bitcoin": {"usd": 80563, "last_updated_at": 1792943898},
    "solana": {"usd": Decimal("101.52"), "last_updated_at": 1792943898},
}
KRAKEN_BTC = [1792940400, "80546.9", "80697.6", "80427.7", "80532.9", "80579.1", "45.57029958", 4233]
KRAKEN_SOL_OPEN = [1792944000, "101.50", "101.50", "101.35", "101.36", "101.41", "138.45167622", 101]


def test_parse_captured_public_payloads():
    fetched = datetime(2026, 10, 25, 16, 5, tzinfo=timezone.utc)
    ticker = parse_coinbase_ticker(
        "BTC",
        "BTC-USD",
        json.loads(COINBASE_TICKER),
        "https://api.exchange.coinbase.com/products/BTC-USD/ticker",
        fetched,
    )
    assert ticker.close == Decimal("80532.3")
    assert ticker.source_timestamp == parse_timestamp("2026-10-25T15:58:53.942062Z")
    assert ticker.interval == "spot"

    closed_at = datetime.fromtimestamp(1792940400 + 3600, timezone.utc)
    candles = parse_coinbase_candles(
        "BTC",
        "BTC-USD",
        [COINBASE_CANDLE],
        "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600",
        fetched,
        closed_at,
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal("80535.42")
    assert candles[0].open == Decimal("80547.37")
    assert candles[0].low == Decimal("80418.78")
    assert candles[0].high == Decimal("80695.69")
    still_open = parse_coinbase_candles(
        "BTC",
        "BTC-USD",
        [COINBASE_CANDLE],
        "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600",
        fetched,
        datetime.fromtimestamp(1792940400 + 10, timezone.utc),
    )
    assert still_open == []

    spots = parse_coingecko_simple(
        COINGECKO,
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana&vs_currencies=usd&include_last_updated_at=true",
        fetched,
    )
    by_symbol = {point.symbol: point for point in spots}
    assert by_symbol["BTC"].close == Decimal(80563)
    assert by_symbol["SOL"].close == Decimal("101.52")
    assert by_symbol["BTC"].source_timestamp == datetime.fromtimestamp(1792943898, timezone.utc)

    kraken = parse_kraken_ohlc(
        "BTC",
        {"error": [], "result": {"XXBTZUSD": [KRAKEN_BTC], "last": 1792940400}},
        "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60",
        fetched,
        closed_at,
    )
    assert kraken[0].pair == "XXBTZUSD"
    assert kraken[0].close == Decimal("80532.9")
    assert kraken[0].source_name == "kraken"

    dropped = parse_kraken_ohlc(
        "SOL",
        {"error": [], "result": {"SOLUSD": [KRAKEN_SOL_OPEN], "last": 1792940400}},
        "https://api.kraken.com/0/public/OHLC?pair=SOLUSD&interval=60",
        fetched,
        datetime.fromtimestamp(1792944000 + 10, timezone.utc),
    )
    assert dropped == []


def test_url_allowlist_blocks_trading_and_credential_urls():
    assert_allowed_url("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
    assert_allowed_url("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60")
    with pytest.raises(ValueError):
        assert_allowed_url("https://api.exchange.coinbase.com/orders")
    with pytest.raises(ValueError):
        assert_allowed_url("https://api.coinbase.com/v2/accounts")
    with pytest.raises(ValueError):
        assert_allowed_url("http://api.kraken.com/0/public/OHLC")
    with pytest.raises(ValueError):
        assert_allowed_url("https://user:secret@api.kraken.com/0/public/OHLC")


def test_retries_429_and_does_not_retry_404(caplog):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow down"})
        return httpx.Response(200, json={"ok": True})

    sleeps: list[float] = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level(logging.WARNING, logger="sollab.httpclient"):
            body = fetch_json(
                client,
                "https://api.coingecko.com/api/v3/simple/price",
                max_retries=3,
                sleeper=sleeps.append,
            )
    assert body.data == {"ok": True}
    assert calls["n"] == 3
    assert sleeps
    assert "retrying" in caplog.text

    calls["n"] = 0

    def missing(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(404, json={"message": "missing"})

    with httpx.Client(transport=httpx.MockTransport(missing)) as client:
        with pytest.raises(HttpFailure) as caught:
            fetch_json(
                client,
                "https://api.coingecko.com/api/v3/simple/price",
                max_retries=3,
                sleeper=sleeps.append,
            )
    assert calls["n"] == 1
    assert caught.value.retryable is False


def test_collect_falls_back_to_kraken_and_records_the_failure(conn):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = str(request.url)
        if url.endswith("/ticker"):
            product = url.split("/products/")[1].split("/")[0]
            price = "100" if product.startswith("BTC") else "20"
            return httpx.Response(200, json={"price": price, "time": "2026-01-01T00:00:00Z", "volume": "1"})
        if "/candles" in url:
            return httpx.Response(404, json={"message": "unavailable"})
        if "coingecko" in url:
            return httpx.Response(
                200,
                json={
                    "bitcoin": {"usd": 100, "last_updated_at": 1767225600},
                    "solana": {"usd": 20, "last_updated_at": 1767225600},
                },
            )
        if "kraken.com" in url:
            pair = "XXBTZUSD" if "XBTUSD" in url else "SOLUSD"
            close = "100" if pair == "XXBTZUSD" else "20"
            return httpx.Response(
                200,
                json={
                    "error": [],
                    "result": {
                        pair: [[1700000000, close, close, close, close, close, "1", 1]],
                        "last": 1700000000,
                    },
                },
            )
        return httpx.Response(500, json={"message": url})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = collect(conn, pause_seconds=0, sleeper=lambda _seconds: None, client=client, max_retries=0)
    assert summary.fetched_by_symbol["BTC"] > 0
    assert summary.fetched_by_symbol["SOL"] > 0
    assert any("kraken.com" in url for url in seen)
    assert any("coinbase_candles" in error for error in summary.errors)
    stored_errors = conn.execute("SELECT COUNT(*) AS n FROM errors").fetchone()["n"]
    assert stored_errors >= 1
    kraken_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM prices WHERE source_name = 'kraken' AND interval = '1h'"
    ).fetchone()["n"]
    assert kraken_rows == 2


def test_kraken_body_rate_limit_is_retried(caplog):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"error": ["EAPI:Rate limit exceeded"], "result": {}})
        return httpx.Response(
            200,
            json={
                "error": [],
                "result": {
                    "XXBTZUSD": [[1700000000, "100", "100", "100", "100", "100", "1", 1]],
                    "last": 1700000000,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level(logging.WARNING, logger="sollab.sources"):
            points = fetch_kraken_ohlc(
                client,
                "BTC",
                now=datetime(2024, 1, 1, tzinfo=timezone.utc),
                max_retries=1,
                sleeper=lambda _seconds: None,
            )
    assert calls["n"] == 2
    assert points[0].close == Decimal("100")
    assert "rate limit" in caplog.text.lower()
