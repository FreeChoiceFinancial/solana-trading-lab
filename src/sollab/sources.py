"""Parsers and fetchers for public BTC and SOL prices.

Spot rows use the venue's last-trade or last-updated time. Hourly rows are
closed candles only: the bucket that has not finished is dropped, not stored
as if it were final. Kraken is used only when Coinbase returns no closed candles.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from sollab.constants import (
    COINBASE_API,
    COINGECKO_API,
    KRAKEN_API,
    SOURCE_COINBASE,
    SOURCE_COINGECKO,
    SOURCE_KRAKEN,
)
from sollab.httpclient import fetch_json
from sollab.models import PricePoint, as_decimal
from sollab.timeutil import parse_timestamp

logger = logging.getLogger(__name__)

HOUR = 3600
PRODUCTS = {"BTC": "BTC-USD", "SOL": "SOL-USD"}
KRAKEN_PAIRS = {"BTC": "XBTUSD", "SOL": "SOLUSD"}
COINGECKO_IDS = {"bitcoin": "BTC", "solana": "SOL"}


class SourceError(Exception):
    """A venue payload could not be used."""


def coinbase_ticker_url(product: str) -> str:
    return f"{COINBASE_API}/products/{product}/ticker"


def coinbase_candles_url(product: str) -> str:
    return f"{COINBASE_API}/products/{product}/candles?granularity={HOUR}"


def coingecko_simple_url() -> str:
    return (
        f"{COINGECKO_API}/api/v3/simple/price"
        "?ids=bitcoin,solana&vs_currencies=usd&include_last_updated_at=true"
    )


def kraken_ohlc_url(pair: str) -> str:
    return f"{KRAKEN_API}/0/public/OHLC?pair={pair}&interval=60"


def _closed(open_ts: datetime, now: datetime) -> bool:
    return int(open_ts.timestamp()) + HOUR <= int(now.timestamp())


def parse_coinbase_ticker(
    symbol: str,
    product: str,
    payload: object,
    endpoint: str,
    fetched_at: datetime,
) -> PricePoint:
    if not isinstance(payload, dict) or "price" not in payload or "time" not in payload:
        raise SourceError(f"Coinbase ticker payload missing price or time: {str(payload)[:200]}")
    price = as_decimal(payload["price"])
    if price <= 0:
        raise SourceError("Coinbase ticker price is not positive")
    volume = as_decimal(payload["volume"]) if payload.get("volume") not in (None, "") else None
    return PricePoint(
        symbol=symbol,
        pair=product,
        interval="spot",
        open=None,
        high=None,
        low=None,
        close=price,
        volume=volume,
        source_name=SOURCE_COINBASE,
        endpoint=endpoint,
        fetched_at=fetched_at,
        source_timestamp=parse_timestamp(payload["time"]),
    )


def parse_coinbase_candles(
    symbol: str,
    product: str,
    payload: object,
    endpoint: str,
    fetched_at: datetime,
    now: datetime,
) -> list[PricePoint]:
    if isinstance(payload, dict):
        raise SourceError(f"Coinbase candles error: {str(payload)[:200]}")
    if not isinstance(payload, list):
        raise SourceError("Coinbase candles payload is not a list")
    by_time: dict[datetime, PricePoint] = {}
    dropped = 0
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            logger.warning("skipping malformed Coinbase candle for %s: %s", symbol, row)
            continue
        open_ts = parse_timestamp(row[0])
        if not _closed(open_ts, now):
            dropped += 1
            continue
        low, high, open_, close, volume = (as_decimal(row[i]) for i in range(1, 6))
        if min(open_, high, low, close) <= 0 or high < low:
            logger.warning("skipping non-positive Coinbase candle for %s at %s", symbol, open_ts)
            continue
        by_time[open_ts] = PricePoint(
            symbol=symbol,
            pair=product,
            interval="1h",
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source_name=SOURCE_COINBASE,
            endpoint=endpoint,
            fetched_at=fetched_at,
            source_timestamp=open_ts,
        )
    if dropped:
        logger.info("dropped %s forming Coinbase candle(s) for %s", dropped, symbol)
    return [by_time[key] for key in sorted(by_time)]


def parse_coingecko_simple(
    payload: object,
    endpoint: str,
    fetched_at: datetime,
) -> list[PricePoint]:
    if not isinstance(payload, dict):
        raise SourceError("CoinGecko payload is not an object")
    status = payload.get("status")
    if isinstance(status, dict) and status.get("error_code"):
        raise SourceError(f"CoinGecko error: {str(status)[:200]}")
    points: list[PricePoint] = []
    for coin_id, symbol in COINGECKO_IDS.items():
        entry = payload.get(coin_id)
        if not isinstance(entry, dict) or "usd" not in entry:
            logger.warning("CoinGecko response missing %s", coin_id)
            continue
        price = as_decimal(entry["usd"])
        if price <= 0:
            logger.warning("CoinGecko %s price is not positive", coin_id)
            continue
        source_ts = None
        if entry.get("last_updated_at") is not None:
            source_ts = parse_timestamp(entry["last_updated_at"])
        points.append(
            PricePoint(
                symbol=symbol,
                pair=f"{coin_id}/usd",
                interval="spot",
                open=None,
                high=None,
                low=None,
                close=price,
                volume=None,
                source_name=SOURCE_COINGECKO,
                endpoint=endpoint,
                fetched_at=fetched_at,
                source_timestamp=source_ts,
            )
        )
    if not points:
        raise SourceError("CoinGecko returned no BTC or SOL prices")
    return points


def parse_kraken_ohlc(
    symbol: str,
    payload: object,
    endpoint: str,
    fetched_at: datetime,
    now: datetime,
) -> list[PricePoint]:
    if not isinstance(payload, dict):
        raise SourceError("Kraken payload is not an object")
    errors = payload.get("error") or []
    if errors:
        joined = ", ".join(str(item) for item in errors)
        raise SourceError(f"Kraken error: {joined}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SourceError("Kraken result missing")
    keys = [key for key in result.keys() if key != "last"]
    if len(keys) != 1 or not isinstance(result[keys[0]], list):
        raise SourceError(f"Kraken pair key missing: {keys}")
    pair_key = str(keys[0])
    by_time: dict[datetime, PricePoint] = {}
    dropped = 0
    for row in result[pair_key]:
        if not isinstance(row, list) or len(row) < 7:
            logger.warning("skipping malformed Kraken candle for %s: %s", symbol, row)
            continue
        open_ts = parse_timestamp(row[0])
        if not _closed(open_ts, now):
            dropped += 1
            continue
        open_, high, low, close, volume = (as_decimal(row[i]) for i in (1, 2, 3, 4, 6))
        if min(open_, high, low, close) <= 0 or high < low:
            logger.warning("skipping non-positive Kraken candle for %s at %s", symbol, open_ts)
            continue
        by_time[open_ts] = PricePoint(
            symbol=symbol,
            pair=pair_key,
            interval="1h",
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source_name=SOURCE_KRAKEN,
            endpoint=endpoint,
            fetched_at=fetched_at,
            source_timestamp=open_ts,
        )
    if dropped:
        logger.info("dropped %s forming Kraken candle(s) for %s", dropped, symbol)
    return [by_time[key] for key in sorted(by_time)]


def fetch_coinbase_ticker(client: httpx.Client, symbol: str, **http_kwargs: object) -> PricePoint:
    product = PRODUCTS[symbol]
    endpoint = coinbase_ticker_url(product)
    body = fetch_json(client, endpoint, **http_kwargs)  # type: ignore[arg-type]
    return parse_coinbase_ticker(symbol, product, body.data, endpoint, body.fetched_at)


def fetch_coinbase_candles(
    client: httpx.Client,
    symbol: str,
    now: datetime | None = None,
    **http_kwargs: object,
) -> list[PricePoint]:
    product = PRODUCTS[symbol]
    endpoint = coinbase_candles_url(product)
    body = fetch_json(client, endpoint, **http_kwargs)  # type: ignore[arg-type]
    clock = now or datetime.now(timezone.utc)
    return parse_coinbase_candles(symbol, product, body.data, endpoint, body.fetched_at, clock)


def fetch_coingecko_simple(client: httpx.Client, **http_kwargs: object) -> list[PricePoint]:
    endpoint = coingecko_simple_url()
    body = fetch_json(client, endpoint, **http_kwargs)  # type: ignore[arg-type]
    return parse_coingecko_simple(body.data, endpoint, body.fetched_at)


def fetch_kraken_ohlc(
    client: httpx.Client,
    symbol: str,
    now: datetime | None = None,
    **http_kwargs: object,
) -> list[PricePoint]:
    pair = KRAKEN_PAIRS[symbol]
    if not pair.isalnum():
        raise SourceError(f"invalid Kraken pair: {pair}")
    endpoint = kraken_ohlc_url(pair)
    sleeper = http_kwargs.get("sleeper", time.sleep)
    attempts = int(http_kwargs.get("max_retries", 3)) + 1  # type: ignore[arg-type]
    clock = now or datetime.now(timezone.utc)
    last_error: Exception | None = None
    for attempt in range(attempts):
        body = fetch_json(client, endpoint, **http_kwargs)  # type: ignore[arg-type]
        errors = body.data.get("error") if isinstance(body.data, dict) else None
        if errors and any("Rate limit" in str(item) for item in errors):
            last_error = SourceError(f"Kraken rate limit: {errors}")
            if attempt + 1 >= attempts:
                logger.error("Kraken rate limit persisted url=%s error=%s", endpoint, errors)
                raise last_error
            delay = min(10.0, 0.5 * (2**attempt))
            logger.warning("retrying Kraken OHLC after rate limit url=%s sleep_seconds=%s", endpoint, delay)
            sleeper(delay)  # type: ignore[operator]
            continue
        return parse_kraken_ohlc(symbol, body.data, endpoint, body.fetched_at, clock)
    raise SourceError(f"Kraken OHLC failed: {last_error}")
