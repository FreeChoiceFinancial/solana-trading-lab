"""Collect free public metals prices into the shared SQLite price table."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from sollab.constants import SOURCE_COINBASE
from sollab.httpclient import make_client
from sollab.metalsconst import KRAKEN_DAILY, YAHOO_BARS
from sollab.metalsources import (
    SOURCE_YAHOO,
    coingecko_metals_url,
    fetch_coinbase_paxg_daily,
    fetch_yahoo_symbol,
    kraken_daily_url,
    parse_coingecko_metals,
    parse_kraken_daily,
)
from sollab.models import PricePoint
from sollab.sources import coinbase_ticker_url, parse_coinbase_ticker
from sollab.httpclient import fetch_json
from sollab.storage import insert_prices, record_error

logger = logging.getLogger(__name__)


@dataclass
class MetalsCollectSummary:
    fetched_by_symbol: dict[str, int] = field(default_factory=dict)
    inserted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return self.fetched_by_symbol.get("PAXG", 0) > 0 and self.fetched_by_symbol.get("SI", 0) > 0


def collect_metals(
    conn,
    *,
    pause_seconds: float = 0.25,
    sleeper=time.sleep,
    client: httpx.Client | None = None,
    max_retries: int = 3,
    now: datetime | None = None,
) -> MetalsCollectSummary:
    summary = MetalsCollectSummary()
    own_client = client is None
    if client is None:
        client = make_client()
    pause = max(0.0, pause_seconds)
    armed = False
    clock = now or datetime.now(timezone.utc)
    http_kwargs = {"sleeper": sleeper, "max_retries": max_retries}

    def wait() -> None:
        nonlocal armed
        if armed and pause:
            sleeper(pause)
        armed = True

    def save(points: list[PricePoint]) -> None:
        if not points:
            return
        with conn:
            inserted, skipped = insert_prices(conn, points)
        summary.inserted += inserted
        summary.skipped += skipped
        for point in points:
            summary.fetched_by_symbol[point.symbol] = summary.fetched_by_symbol.get(point.symbol, 0) + 1
            if point.source_name not in summary.sources_used:
                summary.sources_used.append(point.source_name)

    def fail(component: str, exc: Exception) -> None:
        message = str(exc)
        logger.error("%s failed: %s", component, message)
        summary.errors.append(f"{component}: {message}")
        with conn:
            record_error(conn, component, message, type(exc).__name__, datetime.now(timezone.utc))

    try:
        wait()
        try:
            endpoint = coinbase_ticker_url("PAXG-USD")
            body = fetch_json(client, endpoint, **http_kwargs)
            save([parse_coinbase_ticker("PAXG", "PAXG-USD", body.data, endpoint, body.fetched_at)])
        except Exception as exc:
            fail("coinbase_ticker:PAXG", exc)
        wait()
        try:
            save(fetch_coinbase_paxg_daily(client, clock, **http_kwargs))
        except Exception as exc:
            fail("coinbase_candles:PAXG", exc)
        for symbol, pair in KRAKEN_DAILY:
            wait()
            try:
                endpoint = kraken_daily_url(pair)
                body = fetch_json(client, endpoint, **http_kwargs)
                save(parse_kraken_daily(symbol, body.data, endpoint, body.fetched_at, clock))
            except Exception as exc:
                fail(f"kraken_ohlc:{symbol}", exc)
        wait()
        try:
            endpoint = coingecko_metals_url()
            body = fetch_json(client, endpoint, **http_kwargs)
            save(parse_coingecko_metals(body.data, endpoint, body.fetched_at))
        except Exception as exc:
            fail("coingecko_metals", exc)
        for yahoo_symbol, symbol in YAHOO_BARS:
            wait()
            try:
                save(fetch_yahoo_symbol(client, yahoo_symbol, symbol, clock, **http_kwargs))
            except Exception as exc:
                fail(f"yahoo_chart:{yahoo_symbol}", exc)
    finally:
        if own_client:
            client.close()
    if SOURCE_COINBASE not in summary.sources_used and SOURCE_YAHOO not in summary.sources_used:
        logger.warning("metals collect stored no candle source")
    return summary
