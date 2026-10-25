"""Public metals prices: Coinbase PAXG, Kraken PAXG and XAUT, Yahoo daily bars.

Daily candles are stored only after the bar has closed. A forming bar is
dropped. Yahoo's chart host is an undocumented public endpoint and can
change or block; failures are stored as errors and are not filled in.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote

import httpx

from sollab.constants import COINBASE_API, COINGECKO_API, KRAKEN_API, SOURCE_COINBASE, SOURCE_COINGECKO, SOURCE_KRAKEN
from sollab.httpclient import fetch_json
from sollab.metalsconst import BACKFILL_START, CHUNK_DAYS, COINGECKO_METALS
from sollab.models import PricePoint, as_decimal
from sollab.sources import SourceError
from sollab.timeutil import parse_timestamp

logger = logging.getLogger(__name__)

DAY = 86400
SOURCE_YAHOO = "yahoo_chart"
YAHOO_API = "https://query1.finance.yahoo.com"


def _closed(open_ts: datetime, now: datetime, width: int = DAY) -> bool:
    return int(open_ts.timestamp()) + width <= int(now.timestamp())


def coinbase_daily_url(product: str, start: datetime, end: datetime) -> str:
    start_s = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_s = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"{COINBASE_API}/products/{product}/candles"
        f"?granularity={DAY}&start={start_s}&end={end_s}"
    )


def kraken_daily_url(pair: str) -> str:
    return f"{KRAKEN_API}/0/public/OHLC?pair={pair}&interval=1440"


def yahoo_chart_url(symbol: str) -> str:
    return f"{YAHOO_API}/v8/finance/chart/{quote(symbol, safe='')}?interval=1d&range=5y"


def coingecko_metals_url() -> str:
    ids = ",".join(COINGECKO_METALS)
    return (
        f"{COINGECKO_API}/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd&include_last_updated_at=true"
    )


def _candle(
    *,
    symbol: str,
    pair: str,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal | None,
    source_name: str,
    endpoint: str,
    fetched_at: datetime,
    source_timestamp: datetime,
) -> PricePoint | None:
    if min(open_, high, low, close) <= 0 or high < low:
        logger.warning("skipping non-positive metals candle %s at %s", symbol, source_timestamp)
        return None
    return PricePoint(
        symbol=symbol,
        pair=pair,
        interval="1d",
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source_name=source_name,
        endpoint=endpoint,
        fetched_at=fetched_at,
        source_timestamp=source_timestamp,
    )


def parse_coinbase_daily(
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
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            continue
        open_ts = parse_timestamp(row[0])
        if not _closed(open_ts, now):
            continue
        low, high, open_, close, volume = (as_decimal(row[i]) for i in range(1, 6))
        point = _candle(
            symbol=symbol,
            pair=product,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source_name=SOURCE_COINBASE,
            endpoint=endpoint,
            fetched_at=fetched_at,
            source_timestamp=open_ts,
        )
        if point is not None:
            by_time[open_ts] = point
    return [by_time[key] for key in sorted(by_time)]


def parse_kraken_daily(
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
        raise SourceError("Kraken error: " + ", ".join(str(item) for item in errors))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SourceError("Kraken result missing")
    keys = [key for key in result if key != "last"]
    if len(keys) != 1 or not isinstance(result[keys[0]], list):
        raise SourceError(f"Kraken pair key missing: {keys}")
    by_time: dict[datetime, PricePoint] = {}
    for row in result[keys[0]]:
        if not isinstance(row, list) or len(row) < 7:
            continue
        open_ts = parse_timestamp(row[0])
        if not _closed(open_ts, now):
            continue
        open_, high, low, close = (as_decimal(row[i]) for i in (1, 2, 3, 4))
        volume = as_decimal(row[6])
        point = _candle(
            symbol=symbol,
            pair=str(keys[0]),
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source_name=SOURCE_KRAKEN,
            endpoint=endpoint,
            fetched_at=fetched_at,
            source_timestamp=open_ts,
        )
        if point is not None:
            by_time[open_ts] = point
    return [by_time[key] for key in sorted(by_time)]


def parse_yahoo_chart(
    symbol: str,
    yahoo_symbol: str,
    payload: object,
    endpoint: str,
    fetched_at: datetime,
    now: datetime,
) -> list[PricePoint]:
    if not isinstance(payload, dict):
        raise SourceError("Yahoo payload is not an object")
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise SourceError("Yahoo chart missing")
    if chart.get("error"):
        raise SourceError(f"Yahoo chart error: {str(chart['error'])[:200]}")
    result = chart.get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise SourceError("Yahoo chart result missing")
    block = result[0]
    meta = block.get("meta") if isinstance(block.get("meta"), dict) else {}
    points: list[PricePoint] = []
    market_time = meta.get("regularMarketTime")
    market_price = meta.get("regularMarketPrice")
    if market_time is not None and market_price is not None:
        price = as_decimal(market_price)
        if price > 0:
            points.append(
                PricePoint(
                    symbol=symbol,
                    pair=yahoo_symbol,
                    interval="spot",
                    open=None,
                    high=None,
                    low=None,
                    close=price,
                    volume=None,
                    source_name=SOURCE_YAHOO,
                    endpoint=endpoint,
                    fetched_at=fetched_at,
                    source_timestamp=parse_timestamp(market_time),
                )
            )
    timestamps = block.get("timestamp")
    indicators = block.get("indicators")
    quote = None
    if isinstance(indicators, dict):
        quotes = indicators.get("quote")
        if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict):
            quote = quotes[0]
    if not isinstance(timestamps, list) or quote is None:
        if points:
            return points
        raise SourceError("Yahoo chart has no daily bars")
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    by_time: dict[datetime, PricePoint] = {}
    for index, raw_ts in enumerate(timestamps):
        if raw_ts is None or index >= len(closes) or closes[index] is None:
            continue
        if index >= len(opens) or opens[index] is None:
            continue
        open_ts = parse_timestamp(raw_ts)
        if not _closed(open_ts, now):
            continue
        high = as_decimal(highs[index]) if index < len(highs) and highs[index] is not None else as_decimal(closes[index])
        low = as_decimal(lows[index]) if index < len(lows) and lows[index] is not None else as_decimal(closes[index])
        volume = as_decimal(volumes[index]) if index < len(volumes) and volumes[index] is not None else None
        point = _candle(
            symbol=symbol,
            pair=yahoo_symbol,
            open_=as_decimal(opens[index]),
            high=high,
            low=low,
            close=as_decimal(closes[index]),
            volume=volume,
            source_name=SOURCE_YAHOO,
            endpoint=endpoint,
            fetched_at=fetched_at,
            source_timestamp=open_ts,
        )
        if point is not None:
            by_time[open_ts] = point
    points.extend(by_time[key] for key in sorted(by_time))
    if not points:
        raise SourceError(f"Yahoo returned no closed bars for {yahoo_symbol}")
    return points


def parse_coingecko_metals(payload: object, endpoint: str, fetched_at: datetime) -> list[PricePoint]:
    if not isinstance(payload, dict):
        raise SourceError("CoinGecko payload is not an object")
    points: list[PricePoint] = []
    for coin_id, symbol in COINGECKO_METALS.items():
        entry = payload.get(coin_id)
        if not isinstance(entry, dict) or "usd" not in entry:
            continue
        price = as_decimal(entry["usd"])
        if price <= 0:
            continue
        source_ts = parse_timestamp(entry["last_updated_at"]) if entry.get("last_updated_at") is not None else None
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
        raise SourceError("CoinGecko returned no metals prices")
    return points


def coinbase_daily_chunks(now: datetime) -> list[tuple[datetime, datetime]]:
    start = parse_timestamp(BACKFILL_START)
    cursor = start
    chunks: list[tuple[datetime, datetime]] = []
    while cursor < now:
        end = min(now, cursor + timedelta(days=CHUNK_DAYS))
        chunks.append((cursor, end))
        cursor = end
    return chunks


def fetch_coinbase_paxg_daily(client: httpx.Client, now: datetime, **http_kwargs: object) -> list[PricePoint]:
    points: list[PricePoint] = []
    for start, end in coinbase_daily_chunks(now):
        endpoint = coinbase_daily_url("PAXG-USD", start, end)
        body = fetch_json(client, endpoint, **http_kwargs)  # type: ignore[arg-type]
        points.extend(
            parse_coinbase_daily("PAXG", "PAXG-USD", body.data, endpoint, body.fetched_at, now)
        )
    return points


def fetch_yahoo_symbol(
    client: httpx.Client,
    yahoo_symbol: str,
    symbol: str,
    now: datetime,
    **http_kwargs: object,
) -> list[PricePoint]:
    endpoint = yahoo_chart_url(yahoo_symbol)
    body = fetch_json(client, endpoint, **http_kwargs)  # type: ignore[arg-type]
    return parse_yahoo_chart(symbol, yahoo_symbol, body.data, endpoint, body.fetched_at, now)


