"""Fetch public BTC and SOL prices and store them.

Coinbase Exchange candles are the primary hourly source. Kraken public OHLC
is requested only when Coinbase returns no closed hourly candles. CoinGecko's
keyless simple price is an additional spot print. Failures are logged and
written to the errors table; they are not replaced with guessed prices.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from sollab.constants import SYMBOLS
from sollab.httpclient import make_client
from sollab.models import PricePoint
from sollab.sources import (
    fetch_coinbase_candles,
    fetch_coinbase_ticker,
    fetch_coingecko_simple,
    fetch_kraken_ohlc,
)
from sollab.storage import insert_prices, record_error

logger = logging.getLogger(__name__)


@dataclass
class CollectSummary:
    fetched_by_symbol: dict[str, int]
    inserted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return all(self.fetched_by_symbol.get(symbol, 0) > 0 for symbol in self.fetched_by_symbol)


def collect(
    conn,
    symbols: tuple[str, ...] = SYMBOLS,
    *,
    pause_seconds: float = 0.25,
    sleeper=time.sleep,
    client: httpx.Client | None = None,
    max_retries: int = 3,
) -> CollectSummary:
    summary = CollectSummary(fetched_by_symbol={symbol: 0 for symbol in symbols})
    own_client = client is None
    if client is None:
        client = make_client()
    pause = max(0.0, pause_seconds)
    armed = False

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
        logger.info(
            "stored source=%s interval=%s symbols=%s points=%s inserted=%s skipped=%s",
            points[0].source_name,
            points[0].interval,
            sorted({point.symbol for point in points}),
            len(points),
            inserted,
            skipped,
        )

    def fail(component: str, exc: Exception) -> None:
        message = str(exc)
        logger.error("%s failed: %s", component, message)
        summary.errors.append(f"{component}: {message}")
        with conn:
            record_error(conn, component, message, type(exc).__name__, datetime.now(timezone.utc))

    http_kwargs = {"sleeper": sleeper, "max_retries": max_retries}
    try:
        for symbol in symbols:
            wait()
            try:
                save([fetch_coinbase_ticker(client, symbol, **http_kwargs)])
            except Exception as exc:
                fail(f"coinbase_ticker:{symbol}", exc)
            wait()
            candle_points: list[PricePoint] = []
            try:
                candle_points = fetch_coinbase_candles(client, symbol, **http_kwargs)
                save(candle_points)
            except Exception as exc:
                fail(f"coinbase_candles:{symbol}", exc)
                candle_points = []
            if candle_points:
                continue
            wait()
            try:
                logger.warning("falling back to Kraken OHLC for %s", symbol)
                save(fetch_kraken_ohlc(client, symbol, **http_kwargs))
            except Exception as exc:
                fail(f"kraken_ohlc:{symbol}", exc)
        wait()
        try:
            save(fetch_coingecko_simple(client, **http_kwargs))
        except Exception as exc:
            fail("coingecko_simple", exc)
    finally:
        if own_client:
            client.close()
    return summary
