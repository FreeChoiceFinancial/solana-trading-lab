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
from urllib.parse import unquote, urlparse

import httpx

from sollab.constants import USER_AGENT

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset(
    {
        "api.exchange.coinbase.com",
        "api.coingecko.com",
        "api.kraken.com",
        "api.geckoterminal.com",
        "api.dexscreener.com",
        "api.mainnet-beta.solana.com",
        "api.pump.fun",
        "frontend-api-v3.pump.fun",
        "query1.finance.yahoo.com",
    }
)

# Daily chart symbols. Futures use the Yahoo "=F" suffix. No other path is fetched.
YAHOO_CHART_SYMBOLS = frozenset(
    {
        "GLD",
        "SLV",
        "PPLT",
        "PALL",
        "GC=F",
        "SI=F",
        "PL=F",
        "PA=F",
    }
)

# Public Solana RPC methods. Anything that signs or submits a transaction is refused.
RPC_READ_METHODS = frozenset(
    {
        "getAccountInfo",
        "getMultipleAccounts",
        "getRecentPrioritizationFees",
    }
)

_B58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")

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


def _is_base58_pubkey(value: str) -> bool:
    return 32 <= len(value) <= 44 and bool(value) and all(char in _B58_ALPHABET for char in value)


def assert_allowed_rpc(url: str, body: dict[str, object]) -> None:
    """POST JSON-RPC only for account reads and recent priority fees."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.mainnet-beta.solana.com":
        raise ValueError(f"refusing RPC URL: {url}")
    if parsed.username or parsed.password:
        raise ValueError("refusing URL with embedded credentials")
    if parsed.path not in {"", "/"}:
        raise ValueError(f"refusing Solana RPC path: {parsed.path}")
    method = body.get("method")
    if not isinstance(method, str) or method not in RPC_READ_METHODS:
        raise ValueError(f"refusing Solana RPC method: {method}")


def assert_allowed_url(url: str) -> None:
    """Reject anything other than the read-only endpoints this lab calls."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing URL outside the public market-data allowlist: {url}")
    if parsed.username or parsed.password:
        raise ValueError("refusing URL with embedded credentials")
    path = parsed.path
    if parsed.hostname == "api.mainnet-beta.solana.com":
        raise ValueError("Solana RPC is POST-only and is not fetched with GET")
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
    if parsed.hostname == "api.geckoterminal.com":
        allowed = {
            "/api/v2/networks/solana/dexes/pump-fun/pools",
            "/api/v2/networks/solana/dexes/pumpswap/pools",
        }
        if path not in allowed:
            raise ValueError(f"refusing GeckoTerminal path: {path}")
        return
    if parsed.hostname == "api.dexscreener.com":
        if path == "/latest/dex/search":
            return
        prefix = "/latest/dex/tokens/"
        batch = "/tokens/v1/solana/"
        if path.startswith(prefix) and _is_base58_pubkey(path[len(prefix) :]):
            return
        if path.startswith(batch):
            parts = path[len(batch) :].split(",")
            if 1 <= len(parts) <= 30 and all(_is_base58_pubkey(part) for part in parts):
                return
        raise ValueError(f"refusing DexScreener path: {path}")
    if parsed.hostname == "api.pump.fun":
        if path != "/v1/users/search-v2":
            raise ValueError(f"refusing pump.fun API path: {path}")
        return
    if parsed.hostname == "frontend-api-v3.pump.fun":
        if path != "/coins":
            raise ValueError(f"refusing pump.fun frontend path: {path}")
        return
    if parsed.hostname == "query1.finance.yahoo.com":
        prefix = "/v8/finance/chart/"
        if not path.startswith(prefix):
            raise ValueError(f"refusing Yahoo path: {path}")
        symbol = unquote(path[len(prefix) :])
        if symbol not in YAHOO_CHART_SYMBOLS or "/" in symbol:
            raise ValueError(f"refusing Yahoo symbol: {symbol}")
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
    headers: dict[str, str] | None = None,
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
            response = client.get(url, headers=headers)
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


def post_json(
    client: httpx.Client,
    url: str,
    body: dict[str, object],
    *,
    max_retries: int = 3,
    sleeper: Sleeper = time.sleep,
    clock: Clock | None = None,
) -> HttpJson:
    """POST JSON for allowlisted Solana read methods. Same retry rule as GET."""
    assert_allowed_rpc(url, body)
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            response = client.post(url, json=body)
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
                return HttpJson(url=url, status_code=response.status_code, data=data, fetched_at=fetched_at)
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
