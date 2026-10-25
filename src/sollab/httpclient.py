"""Allowlisted GET requests with bounded retries.

Only public market-data URLs used by this lab are permitted. The client has no
API-key header and no order, account, or wallet path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from json import JSONDecodeError, loads
from typing import Callable
from urllib.parse import urlparse

import httpx

from sollab.constants import USER_AGENT

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset(
    {
        "api.exchange.coinbase.com",
        "api.coingecko.com",
        "api.kraken.com",
    }
)

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


class HttpFailure(Exception):
    """A public data request failed after the retry policy finished."""

    def __init__(self, message: str, *, url: str, retryable: bool) -> None:
        super().__init__(message)
        self.url = url
        self.retryable = retryable


@dataclass(frozen=True)
class HttpJson:
    url: str
    status_code: int
    data: object
    fetched_at: datetime


def assert_allowed_url(url: str) -> None:
    """Reject anything other than the read-only endpoints this lab calls."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing URL outside the public market-data allowlist: {url}")
    if parsed.username or parsed.password:
        raise ValueError("refusing URL with embedded credentials")
    path = parsed.path
    if parsed.hostname == "api.exchange.coinbase.com":
        parts = path.split("/")
        # /products/{PRODUCT}/ticker or /products/{PRODUCT}/candles
        if (
            len(parts) != 4
            or parts[1] != "products"
            or parts[3] not in {"ticker", "candles"}
            or not parts[2].endswith("-USD")
            or not parts[2].replace("-", "").isalnum()
        ):
            raise ValueError(f"refusing Coinbase path: {path}")
        return
    if parsed.hostname == "api.coingecko.com":
        if path != "/api/v3/simple/price":
            raise ValueError(f"refusing CoinGecko path: {path}")
        return
    if parsed.hostname == "api.kraken.com":
        if path != "/0/public/OHLC":
            raise ValueError(f"refusing Kraken path: {path}")
        return
    raise ValueError(f"refusing URL: {url}")


def _retryable_status(code: int) -> bool:
    return code in {408, 429} or 500 <= code <= 599


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    delay = min(10.0, 0.5 * (2**attempt))
    if response is not None and response.status_code == 429:
        header = response.headers.get("Retry-After")
        if header:
            try:
                delay = float(header)
            except ValueError:
                pass
    return min(10.0, max(0.0, delay))


def fetch_json(
    client: httpx.Client,
    url: str,
    *,
    max_retries: int = 3,
    sleeper: Sleeper = time.sleep,
    clock: Clock | None = None,
) -> HttpJson:
    """GET JSON. Retry timeouts, 408, 429, and 5xx. Do not retry other 4xx.

    ``max_retries`` is the number of retries after the first attempt. The wait
    between attempts is capped at 10 seconds. ``fetched_at`` is the local UTC
    time when a successful body was received, before JSON parsing.
    """
    assert_allowed_url(url)
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            response = client.get(url)
        except httpx.TransportError as exc:
            last_error = exc
            retryable = True
            status_text = type(exc).__name__
        else:
            if response.status_code < 400:
                fetched_at = clock()
                try:
                    data = loads(response.text, parse_float=Decimal)
                except JSONDecodeError as exc:
                    message = f"invalid JSON from {url}: {exc}"
                    logger.error(message)
                    raise HttpFailure(message, url=url, retryable=False) from exc
                return HttpJson(
                    url=url,
                    status_code=response.status_code,
                    data=data,
                    fetched_at=fetched_at,
                )
            snippet = response.text[:300].replace("\n", " ")
            last_error = HttpFailure(
                f"HTTP {response.status_code} from {url}: {snippet}",
                url=url,
                retryable=_retryable_status(response.status_code),
            )
            retryable = _retryable_status(response.status_code)
            status_text = str(response.status_code)
        if attempt >= max_retries or not retryable:
            logger.error(
                "public data request failed url=%s attempts=%s status=%s error=%s",
                url,
                attempt + 1,
                status_text,
                last_error,
            )
            if isinstance(last_error, HttpFailure):
                raise last_error
            raise HttpFailure(str(last_error), url=url, retryable=retryable) from last_error
        delay = _retry_delay(attempt, response)
        logger.warning(
            "retrying public data request url=%s attempt=%s status=%s sleep_seconds=%s",
            url,
            attempt + 1,
            status_text,
            delay,
        )
        sleeper(delay)
    raise HttpFailure(f"request failed: {url}", url=url, retryable=True)


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=False,
    )
