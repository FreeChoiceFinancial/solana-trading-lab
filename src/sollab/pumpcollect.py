"""Read-only pump.fun snapshots from public indexers and Solana account reads.

Token rows come from GeckoTerminal, DexScreener lookups of those mints, and
Solana RPC account data. pump.fun's own frontend and developer API are probed
only to record the response. Their bodies are not parsed into snapshots.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import httpx

from sollab.httpclient import HttpFailure, fetch_json, post_json
from sollab.pumpconst import (
    ASSUMED_SWAP_COMPUTE_UNITS,
    BASE_SIGNATURE_LAMPORTS,
    GLOBAL_PDA,
    INITIAL_REAL_TOKEN_RESERVES,
    PUMP_PROGRAM,
    WSOL_MINT,
)
from sollab.pumpcurve import (
    bonding_curve_pda,
    decode_bonding_curve,
    decode_global,
    decode_mint,
    median_observed,
    priority_fee_lamports,
    progress_ratio,
)
from sollab.pumpflags import compute_flags
from sollab.storage import dec_text, record_error
from sollab.timeutil import iso_z, parse_timestamp

logger = logging.getLogger(__name__)

GECKO_POOLS = "https://api.geckoterminal.com/api/v2/networks/solana/dexes/{dex}/pools?page=1"
GECKO_HEADERS = {"Accept": "application/json;version=20230203"}
DEX_BATCH = "https://api.dexscreener.com/tokens/v1/solana/{mints}"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
COINGECKO_SOL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
PUMP_API_PROBE = "https://api.pump.fun/v1/users/search-v2?q=test"
PUMP_FRONTEND_PROBE = (
    "https://frontend-api-v3.pump.fun/coins?offset=0&limit=1&sort=created_timestamp&order=DESC&includeNsfw=false"
)

DEX_PAGE = ("pump-fun", "pumpswap")
MINT_CAP = 60
RPC_CHUNK = 20

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


@dataclass
class PumpCollectSummary:
    polls: int
    snapshots: int = 0
    sources_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return self.snapshots > 0


def collect_pumpfun(
    conn: sqlite3.Connection,
    *,
    client: httpx.Client | None = None,
    polls: int = 1,
    interval_seconds: float = 35,
    pause_seconds: float = 0.5,
    max_retries: int = 2,
    clock: Clock | None = None,
    sleeper: Sleeper | None = None,
) -> PumpCollectSummary:
    """Fetch one or more read-only polls. Does not sign, spend, or send transactions."""
    if polls < 1:
        raise ValueError("polls must be at least 1")
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    if sleeper is None:
        import time

        sleeper = time.sleep
    owns_client = client is None
    if client is None:
        from sollab.httpclient import make_client

        client = make_client()
    summary = PumpCollectSummary(polls=polls)
    try:
        for index in range(polls):
            if index:
                sleeper(interval_seconds)
            _poll_once(
                conn,
                client,
                summary,
                pause_seconds=pause_seconds,
                max_retries=max_retries,
                clock=clock,
                sleeper=sleeper,
            )
        conn.commit()
    finally:
        if owns_client:
            client.close()
    return summary


def _poll_once(
    conn: sqlite3.Connection,
    client: httpx.Client,
    summary: PumpCollectSummary,
    *,
    pause_seconds: float,
    max_retries: int,
    clock: Clock,
    sleeper: Sleeper,
) -> None:
    collect_id = str(uuid.uuid4())
    errors: list[tuple[str, str]] = []

    def pause() -> None:
        if pause_seconds > 0:
            sleeper(pause_seconds)

    def remember(component: str, exc: Exception) -> None:
        message = str(exc)
        errors.append((component, message))
        summary.errors.append(f"{component}: {message}")
        logger.error("pumpfun collect %s failed: %s", component, message)

    gecko_rows: dict[str, dict[str, object]] = {}
    gecko_urls: list[str] = []
    market_fetched_at: datetime | None = None
    for dex in DEX_PAGE:
        url = GECKO_POOLS.format(dex=dex)
        pause()
        try:
            fetched = fetch_json(client, url, headers=GECKO_HEADERS, max_retries=max_retries, sleeper=sleeper, clock=clock)
        except HttpFailure as exc:
            remember(f"geckoterminal:{dex}", exc)
            continue
        market_fetched_at = fetched.fetched_at
        gecko_urls.append(fetched.url)
        if "geckoterminal" not in summary.sources_used:
            summary.sources_used.append("geckoterminal")
        parsed = _parse_gecko_pools(fetched.data, dex=dex, endpoint=fetched.url)
        for mint, row in parsed.items():
            gecko_rows.setdefault(mint, row)

    mints = list(gecko_rows)
    for prior in _prior_mints(conn):
        if prior not in gecko_rows and prior not in mints:
            mints.append(prior)
        if len(mints) >= MINT_CAP:
            break
    mints = mints[:MINT_CAP]

    dex_rows: dict[str, dict[str, object]] = {}
    dex_urls: list[str] = []
    for start in range(0, len(mints), 30):
        batch = mints[start : start + 30]
        url = DEX_BATCH.format(mints=",".join(batch))
        pause()
        try:
            fetched = fetch_json(client, url, max_retries=max_retries, sleeper=sleeper, clock=clock)
        except HttpFailure as exc:
            remember("dexscreener", exc)
            continue
        dex_urls.append(fetched.url)
        if "dexscreener" not in summary.sources_used:
            summary.sources_used.append("dexscreener")
        for mint, row in _parse_dexscreener(fetched.data, allowed=set(batch), endpoint=fetched.url).items():
            dex_rows[mint] = row

    sol_usd, sol_source, sol_endpoint = _sol_price(
        client,
        gecko_rows,
        pause=pause,
        max_retries=max_retries,
        sleeper=sleeper,
        clock=clock,
        remember=remember,
    )
    if sol_source and sol_source not in summary.sources_used:
        summary.sources_used.append(sol_source)

    pause()
    global_config = None
    global_error = None
    try:
        fetched = post_json(
            client,
            SOLANA_RPC,
            {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": [GLOBAL_PDA, {"encoding": "base64"}]},
            max_retries=max_retries,
            sleeper=sleeper,
            clock=clock,
        )
    except HttpFailure as exc:
        remember("solana_rpc:global", exc)
        global_error = str(exc)
        fetched = None
    else:
        if "solana_rpc" not in summary.sources_used:
            summary.sources_used.append("solana_rpc")
        global_config, global_error = _read_global(fetched.data)
        if global_config is None:
            remember("solana_rpc:global_decode", RuntimeError(global_error or "global_decode_failed"))

    curve_accounts: dict[str, dict[str, object]] = {}
    mint_accounts: dict[str, dict[str, object]] = {}
    if mints:
        wanted: list[tuple[str, str]] = []
        for mint in mints:
            try:
                wanted.append((mint, bonding_curve_pda(mint)))
            except ValueError as exc:
                remember("solana_rpc:pda", exc)
        raw_accounts = _fetch_accounts(
            client,
            [pda for _mint, pda in wanted] + mints,
            pause=pause,
            max_retries=max_retries,
            sleeper=sleeper,
            clock=clock,
            remember=remember,
        )
        if raw_accounts and "solana_rpc" not in summary.sources_used:
            summary.sources_used.append("solana_rpc")
        for mint, pda in wanted:
            payload = raw_accounts.get(pda)
            decoded = _decode_curve_payload(payload)
            if decoded is None and payload is not None and payload.get("present"):
                remember("solana_rpc:curve_decode", RuntimeError(f"curve_decode_failed mint={mint}"))
            if decoded is not None:
                curve_accounts[mint] = decoded
            mint_payload = raw_accounts.get(mint)
            mint_decoded = _decode_mint_payload(mint_payload)
            if mint_decoded is not None:
                mint_accounts[mint] = mint_decoded

    priority_micro, priority_count, priority_slot = _priority_fees(
        client,
        pause=pause,
        max_retries=max_retries,
        sleeper=sleeper,
        clock=clock,
        remember=remember,
    )
    priority_lamports = None
    if priority_micro is not None:
        priority_lamports = priority_fee_lamports(priority_micro, ASSUMED_SWAP_COMPUTE_UNITS)

    _probe(
        client,
        PUMP_API_PROBE,
        "pump_developer_api",
        pause=pause,
        sleeper=sleeper,
        clock=clock,
        remember=remember,
    )
    _probe(
        client,
        PUMP_FRONTEND_PROBE,
        "pump_frontend",
        pause=pause,
        sleeper=sleeper,
        clock=clock,
        remember=remember,
    )

    fetched_at = clock()
    initial_real = (
        global_config.initial_real_token_reserves if global_config is not None else None
    )
    fee_bps = global_config.fee_basis_points if global_config is not None else None
    inserted = 0
    for mint in mints:
        row = _merge_snapshot(
            mint=mint,
            gecko=gecko_rows.get(mint),
            dex=dex_rows.get(mint),
            curve=curve_accounts.get(mint),
            mint_account=mint_accounts.get(mint),
            sol_usd=sol_usd,
            sol_source=sol_source,
            fee_bps=fee_bps,
            initial_real=initial_real,
            fetched_at=fetched_at,
            collect_id=collect_id,
            gecko_urls=gecko_urls,
            dex_urls=dex_urls,
        )
        if row is None:
            continue
        save_snapshot(conn, row)
        inserted += 1
    summary.snapshots += inserted
    conn.execute(
        """
        INSERT INTO pump_network_fees (
            collect_id, fetched_at, endpoint, slot, base_fee_lamports,
            priority_micro_lamports_per_cu, priority_sample_count, assumed_compute_units,
            priority_fee_lamports, sol_usd, sol_usd_source, sol_usd_endpoint,
            global_fee_basis_points, global_decode_ok, initial_real_token_reserves, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            collect_id,
            iso_z(fetched_at),
            SOLANA_RPC,
            priority_slot,
            BASE_SIGNATURE_LAMPORTS,
            None if priority_micro is None else str(priority_micro),
            priority_count,
            ASSUMED_SWAP_COMPUTE_UNITS,
            None if priority_lamports is None else str(priority_lamports),
            dec_text(sol_usd),
            sol_source,
            sol_endpoint,
            fee_bps,
            1 if global_config is not None else 0,
            None if initial_real is None else str(initial_real),
            global_error,
        ),
    )
    recorded = clock()
    for component, message in errors:
        record_error(conn, component, message, collect_id, recorded)
    if market_fetched_at is not None:
        logger.info(
            "pumpfun poll collect_id=%s snapshots=%s market_fetched_at=%s",
            collect_id,
            inserted,
            iso_z(market_fetched_at),
        )


def _prior_mints(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT mint FROM pump_snapshots
        WHERE quote_is_sol = 1 AND IFNULL(curve_complete, 0) = 0
        ORDER BY fetched_at DESC, id DESC
        LIMIT 40
        """
    ).fetchall()
    seen: list[str] = []
    for row in rows:
        if row["mint"] not in seen:
            seen.append(row["mint"])
    return seen


def _parse_gecko_pools(payload: object, *, dex: str, endpoint: str) -> dict[str, dict[str, object]]:
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("data")
    if not isinstance(rows, list):
        return {}
    parsed: dict[str, dict[str, object]] = {}
    for pool in rows:
        if not isinstance(pool, dict):
            continue
        attributes = pool.get("attributes")
        relationships = pool.get("relationships")
        if not isinstance(attributes, dict) or not isinstance(relationships, dict):
            continue
        base = _related_id(relationships, "base_token")
        quote = _related_id(relationships, "quote_token")
        if base is None or not base.startswith("solana_"):
            continue
        mint = base[len("solana_") :]
        quote_mint = quote[len("solana_") :] if quote and quote.startswith("solana_") else None
        name = attributes.get("name") if isinstance(attributes.get("name"), str) else None
        symbol, quote_symbol = _split_pool_name(name)
        txns = attributes.get("transactions") if isinstance(attributes.get("transactions"), dict) else {}
        volume = attributes.get("volume_usd") if isinstance(attributes.get("volume_usd"), dict) else {}
        m5 = txns.get("m5") if isinstance(txns.get("m5"), dict) else {}
        h1 = txns.get("h1") if isinstance(txns.get("h1"), dict) else {}
        h24 = txns.get("h24") if isinstance(txns.get("h24"), dict) else {}
        created = attributes.get("pool_created_at")
        created_at = created if isinstance(created, str) else None
        parsed[mint] = {
            "mint": mint,
            "symbol": symbol,
            "name": name,
            "pool_address": attributes.get("address") if isinstance(attributes.get("address"), str) else None,
            "dex_id": dex,
            "quote_mint": quote_mint,
            "quote_symbol": quote_symbol,
            "created_at": created_at,
            "price_usd": _num_text(attributes.get("base_token_price_usd")),
            "market_cap_usd": _num_text(attributes.get("market_cap_usd")),
            "fdv_usd": _num_text(attributes.get("fdv_usd")),
            "reserve_usd": _num_text(attributes.get("reserve_in_usd")),
            "volume_m5_usd": _num_text(volume.get("m5")),
            "volume_h1_usd": _num_text(volume.get("h1")),
            "volume_h24_usd": _num_text(volume.get("h24")),
            "buys_m5": _int_text(m5.get("buys")),
            "sells_m5": _int_text(m5.get("sells")),
            "buyers_m5": _int_text(m5.get("buyers")),
            "sellers_m5": _int_text(m5.get("sellers")),
            "buys_h1": _int_text(h1.get("buys")),
            "sells_h1": _int_text(h1.get("sells")),
            "buyers_h1": _int_text(h1.get("buyers")),
            "sellers_h1": _int_text(h1.get("sellers")),
            "buys_h24": _int_text(h24.get("buys")),
            "sells_h24": _int_text(h24.get("sells")),
            "quote_token_price_usd": _num_text(attributes.get("quote_token_price_usd")),
            "endpoint": endpoint,
            "source_name": "geckoterminal",
        }
    return parsed


def _parse_dexscreener(
    payload: object,
    *,
    allowed: set[str],
    endpoint: str,
) -> dict[str, dict[str, object]]:
    pairs = _dex_pairs(payload)
    best: dict[str, tuple[Decimal, dict[str, object]]] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        if pair.get("chainId") not in {None, "solana"}:
            continue
        dex_id = pair.get("dexId")
        if dex_id not in {"pump-fun", "pumpswap"}:
            continue
        base = pair.get("baseToken") if isinstance(pair.get("baseToken"), dict) else {}
        quote = pair.get("quoteToken") if isinstance(pair.get("quoteToken"), dict) else {}
        mint = base.get("address")
        if not isinstance(mint, str) or mint not in allowed:
            continue
        liquidity = pair.get("liquidity") if isinstance(pair.get("liquidity"), dict) else {}
        reserve = _decimal(liquidity.get("usd")) or Decimal(0)
        current = best.get(mint)
        if current is not None and current[0] >= reserve:
            continue
        volume = pair.get("volume") if isinstance(pair.get("volume"), dict) else {}
        txns = pair.get("txns") if isinstance(pair.get("txns"), dict) else {}
        m5 = txns.get("m5") if isinstance(txns.get("m5"), dict) else {}
        h1 = txns.get("h1") if isinstance(txns.get("h1"), dict) else {}
        h24 = txns.get("h24") if isinstance(txns.get("h24"), dict) else {}
        created_at = _ms_to_iso(pair.get("pairCreatedAt"))
        row = {
            "mint": mint,
            "symbol": base.get("symbol") if isinstance(base.get("symbol"), str) else None,
            "name": base.get("name") if isinstance(base.get("name"), str) else None,
            "pool_address": pair.get("pairAddress") if isinstance(pair.get("pairAddress"), str) else None,
            "dex_id": dex_id,
            "quote_mint": quote.get("address") if isinstance(quote.get("address"), str) else None,
            "quote_symbol": quote.get("symbol") if isinstance(quote.get("symbol"), str) else None,
            "created_at": created_at,
            "price_usd": _num_text(pair.get("priceUsd")),
            "market_cap_usd": _num_text(pair.get("marketCap")),
            "fdv_usd": _num_text(pair.get("fdv")),
            "reserve_usd": _num_text(liquidity.get("usd")),
            "volume_m5_usd": _num_text(volume.get("m5")),
            "volume_h1_usd": _num_text(volume.get("h1")),
            "volume_h24_usd": _num_text(volume.get("h24")),
            "buys_m5": _int_text(m5.get("buys")),
            "sells_m5": _int_text(m5.get("sells")),
            "buys_h1": _int_text(h1.get("buys")),
            "sells_h1": _int_text(h1.get("sells")),
            "buys_h24": _int_text(h24.get("buys")),
            "sells_h24": _int_text(h24.get("sells")),
            "endpoint": endpoint,
            "source_name": "dexscreener",
        }
        best[mint] = (reserve, row)
    return {mint: row for mint, (_reserve, row) in best.items()}


def _dex_pairs(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        pairs = payload.get("pairs")
        if isinstance(pairs, list):
            return pairs
    return []


def _sol_price(
    client: httpx.Client,
    gecko_rows: dict[str, dict[str, object]],
    *,
    pause: Callable[[], None],
    max_retries: int,
    sleeper: Sleeper,
    clock: Clock,
    remember: Callable[[str, Exception], None],
) -> tuple[Decimal | None, str | None, str | None]:
    pause()
    try:
        fetched = fetch_json(client, COINGECKO_SOL, max_retries=max_retries, sleeper=sleeper, clock=clock)
    except HttpFailure as exc:
        remember("coingecko:sol", exc)
    else:
        if isinstance(fetched.data, dict):
            solana = fetched.data.get("solana")
            if isinstance(solana, dict):
                price = _decimal(solana.get("usd"))
                if price is not None and price > 0:
                    return price, "coingecko", fetched.url
    for row in gecko_rows.values():
        if row.get("quote_mint") == WSOL_MINT:
            price = _decimal(row.get("quote_token_price_usd"))
            if price is not None and price > 0:
                return price, "geckoterminal", str(row.get("endpoint"))
    return None, None, None


def _read_global(payload: object) -> tuple[object, str | None]:
    account = _account_bytes(_rpc_value(payload))
    if account is None:
        return None, "global_account_missing"
    config = decode_global(account)
    if config is None:
        return None, "global_decode_failed"
    return config, None


def _fetch_accounts(
    client: httpx.Client,
    pubkeys: list[str],
    *,
    pause: Callable[[], None],
    max_retries: int,
    sleeper: Sleeper,
    clock: Clock,
    remember: Callable[[str, Exception], None],
) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    unique = list(dict.fromkeys(pubkeys))
    for start in range(0, len(unique), RPC_CHUNK):
        chunk = unique[start : start + RPC_CHUNK]
        pause()
        try:
            fetched = post_json(
                client,
                SOLANA_RPC,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [chunk, {"encoding": "base64"}],
                },
                max_retries=max_retries,
                sleeper=sleeper,
                clock=clock,
            )
        except HttpFailure as exc:
            remember("solana_rpc:accounts", exc)
            continue
        values = _rpc_values(fetched.data)
        if values is None:
            remember("solana_rpc:accounts", RuntimeError("getMultipleAccounts returned no value list"))
            continue
        for pubkey, value in zip(chunk, values):
            raw = _account_bytes(value)
            owner = None
            if isinstance(value, dict):
                owner = value.get("owner") if isinstance(value.get("owner"), str) else None
            found[pubkey] = {"present": raw is not None, "data": raw, "owner": owner}
    return found


def _decode_curve_payload(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not payload or not payload.get("present"):
        return None
    if payload.get("owner") != PUMP_PROGRAM:
        return None
    data = payload.get("data")
    if not isinstance(data, bytes):
        return None
    curve = decode_bonding_curve(data)
    if curve is None:
        return None
    return {
        "virtual_token_reserves": str(curve.virtual_token_reserves),
        "virtual_quote_reserves": str(curve.virtual_quote_reserves),
        "real_token_reserves": str(curve.real_token_reserves),
        "real_quote_reserves": str(curve.real_quote_reserves),
        "token_total_supply": str(curve.token_total_supply),
        "curve_complete": 1 if curve.complete else 0,
        "creator": curve.creator,
        "curve_quote_mint": curve.quote_mint,
        "curve_quote_native": curve.quote_mint_is_native_sol,
    }


def _decode_mint_payload(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not payload or not payload.get("present"):
        return None
    data = payload.get("data")
    if not isinstance(data, bytes):
        return None
    owner = payload.get("owner") if isinstance(payload.get("owner"), str) else None
    mint = decode_mint(data, owner)
    if mint is None:
        return None
    return {
        "decimals": mint.decimals,
        "mint_authority": mint.mint_authority,
        "freeze_authority": mint.freeze_authority,
        "token_program": mint.token_program,
    }


def _priority_fees(
    client: httpx.Client,
    *,
    pause: Callable[[], None],
    max_retries: int,
    sleeper: Sleeper,
    clock: Clock,
    remember: Callable[[str, Exception], None],
) -> tuple[int | None, int | None, int | None]:
    pause()
    try:
        fetched = post_json(
            client,
            SOLANA_RPC,
            {"jsonrpc": "2.0", "id": 1, "method": "getRecentPrioritizationFees", "params": []},
            max_retries=max_retries,
            sleeper=sleeper,
            clock=clock,
        )
    except HttpFailure as exc:
        remember("solana_rpc:priority_fee", exc)
        return None, None, None
    result = fetched.data.get("result") if isinstance(fetched.data, dict) else None
    if not isinstance(result, list):
        remember("solana_rpc:priority_fee", RuntimeError("priority fee result was not a list"))
        return None, None, None
    samples: list[int] = []
    slot = None
    for item in result:
        if not isinstance(item, dict):
            continue
        fee = item.get("prioritizationFee")
        if isinstance(fee, int) and not isinstance(fee, bool):
            samples.append(fee)
        item_slot = item.get("slot")
        if isinstance(item_slot, int) and not isinstance(item_slot, bool):
            slot = item_slot if slot is None else max(slot, item_slot)
    median = median_observed(samples)
    if median is None:
        remember("solana_rpc:priority_fee", RuntimeError("priority fee sample was empty"))
    return median, len(samples), slot


def _probe(
    client: httpx.Client,
    url: str,
    component: str,
    *,
    pause: Callable[[], None],
    sleeper: Sleeper,
    clock: Clock,
    remember: Callable[[str, Exception], None],
) -> None:
    """Record the pump.fun response and do not parse it into token rows."""
    pause()
    try:
        fetched = fetch_json(client, url, max_retries=0, sleeper=sleeper, clock=clock)
    except HttpFailure as exc:
        remember(component, exc)
        return
    remember(component, RuntimeError(f"unexpected HTTP {fetched.status_code}; body not ingested"))


def _merge_snapshot(
    *,
    mint: str,
    gecko: dict[str, object] | None,
    dex: dict[str, object] | None,
    curve: dict[str, object] | None,
    mint_account: dict[str, object] | None,
    sol_usd: Decimal | None,
    sol_source: str | None,
    fee_bps: int | None,
    initial_real: int | None,
    fetched_at: datetime,
    collect_id: str,
    gecko_urls: list[str],
    dex_urls: list[str],
) -> dict[str, object] | None:
    if gecko is None and dex is None and curve is None and mint_account is None:
        return None
    sources: dict[str, str] = {}
    row: dict[str, object] = {"mint": mint, "collect_id": collect_id}
    market_fields = (
        "symbol",
        "name",
        "pool_address",
        "dex_id",
        "quote_mint",
        "quote_symbol",
        "created_at",
        "price_usd",
        "market_cap_usd",
        "fdv_usd",
        "reserve_usd",
        "volume_m5_usd",
        "volume_h1_usd",
        "volume_h24_usd",
        "buys_m5",
        "sells_m5",
        "buyers_m5",
        "sellers_m5",
        "buys_h1",
        "sells_h1",
        "buyers_h1",
        "sellers_h1",
        "buys_h24",
        "sells_h24",
    )
    for name in market_fields:
        gecko_value = None if gecko is None else gecko.get(name)
        dex_value = None if dex is None else dex.get(name)
        if gecko_value is not None:
            row[name] = gecko_value
            sources[name] = "geckoterminal"
        elif dex_value is not None:
            row[name] = dex_value
            sources[name] = "dexscreener"
        else:
            row[name] = None
    # DexScreener has no unique-buyer fields. Leave those null when only DexScreener filled trades.
    if gecko is None:
        for name in ("buyers_m5", "sellers_m5", "buyers_h1", "sellers_h1"):
            if name not in sources:
                row[name] = None
    curve_fields = (
        "virtual_token_reserves",
        "virtual_quote_reserves",
        "real_token_reserves",
        "real_quote_reserves",
        "token_total_supply",
        "curve_complete",
        "creator",
    )
    for name in curve_fields:
        if curve is not None and curve.get(name) is not None:
            row[name] = curve[name]
            sources[name] = "solana_rpc"
        else:
            row[name] = None
    if mint_account is not None:
        for name in ("decimals", "mint_authority", "freeze_authority", "token_program"):
            row[name] = mint_account.get(name)
            if mint_account.get(name) is not None:
                sources[name] = "solana_rpc"
    else:
        row["decimals"] = None
        row["mint_authority"] = None
        row["freeze_authority"] = None
        row["token_program"] = None
    row["quote_is_sol"] = _quote_is_sol(row, curve)
    if row["quote_is_sol"] is not None:
        sources["quote_is_sol"] = "solana_rpc" if curve and curve.get("curve_quote_native") is not None else sources.get("quote_mint", "geckoterminal")
    complete = row.get("curve_complete")
    if complete == 1:
        row["graduation_status"] = "graduated"
        sources["graduation_status"] = "solana_rpc"
    elif complete == 0:
        row["graduation_status"] = "on_curve"
        sources["graduation_status"] = "solana_rpc"
    elif row.get("dex_id") == "pumpswap":
        row["graduation_status"] = "graduated"
        sources["graduation_status"] = sources.get("dex_id", "dexscreener")
    else:
        row["graduation_status"] = "unknown"
    progress = None
    real_token = _int_text(row.get("real_token_reserves"))
    if real_token is not None and initial_real is not None:
        ratio = progress_ratio(real_token, initial_real, complete == 1)
        if ratio is not None:
            progress = format(ratio, "f")
            sources["progress"] = "solana_rpc"
    row["progress"] = progress
    row["global_fee_basis_points"] = fee_bps
    row["initial_real_token_reserves"] = None if initial_real is None else str(initial_real)
    if fee_bps is not None:
        sources["global_fee_basis_points"] = "solana_rpc"
    row["sol_usd"] = dec_text(sol_usd)
    row["sol_usd_source"] = sol_source
    if sol_source:
        sources["sol_usd"] = sol_source
    endpoints = []
    if gecko is not None:
        endpoints.append(str(gecko.get("endpoint")))
    elif gecko_urls and mint in []:
        endpoints.extend(gecko_urls)
    if dex is not None:
        endpoints.append(str(dex.get("endpoint")))
    elif dex_urls and curve is not None:
        endpoints.append(SOLANA_RPC)
    if curve is not None or mint_account is not None:
        if SOLANA_RPC not in endpoints:
            endpoints.append(SOLANA_RPC)
    if not endpoints and gecko_urls:
        endpoints.extend(gecko_urls)
    source_names = []
    for name in ("geckoterminal", "dexscreener", "solana_rpc"):
        if name in sources.values() or (gecko is not None and name == "geckoterminal") or (
            dex is not None and name == "dexscreener"
        ) or ((curve is not None or mint_account is not None) and name == "solana_rpc"):
            source_names.append(name)
    row["field_sources_json"] = _json_sources(sources)
    row["source_name"] = "+".join(source_names) if source_names else "none"
    row["endpoint"] = " ".join(endpoints) if endpoints else SOLANA_RPC
    row["fetched_at"] = iso_z(fetched_at)
    row["source_timestamp"] = None
    return row


def _quote_is_sol(row: dict[str, object], curve: dict[str, object] | None) -> int | None:
    if curve is not None and curve.get("curve_quote_native") is True:
        return 1
    curve_quote = None if curve is None else curve.get("curve_quote_mint")
    if isinstance(curve_quote, str):
        return 1 if curve_quote == WSOL_MINT else 0
    quote = row.get("quote_mint")
    if quote == WSOL_MINT:
        return 1
    if isinstance(quote, str) and quote:
        return 0
    return None


def save_snapshot(conn: sqlite3.Connection, row: dict[str, object]) -> int:
    """Store one snapshot and the flags computed from that row. Used by tests and the collector."""
    snapshot_id = _insert_snapshot(conn, row)
    for flag in compute_flags(row):
        conn.execute(
            """
            INSERT INTO pump_flags (
                snapshot_id, mint, flag, status, rule, inputs_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                row["mint"],
                flag.flag,
                flag.status,
                flag.rule,
                flag.inputs_json(),
                row["fetched_at"],
            ),
        )
    return snapshot_id


def _insert_snapshot(conn: sqlite3.Connection, row: dict[str, object]) -> int:
    columns = (
        "collect_id",
        "mint",
        "symbol",
        "name",
        "creator",
        "pool_address",
        "dex_id",
        "quote_mint",
        "quote_symbol",
        "created_at",
        "graduation_status",
        "price_usd",
        "market_cap_usd",
        "fdv_usd",
        "reserve_usd",
        "volume_m5_usd",
        "volume_h1_usd",
        "volume_h24_usd",
        "buys_m5",
        "sells_m5",
        "buyers_m5",
        "sellers_m5",
        "buys_h1",
        "sells_h1",
        "buyers_h1",
        "sellers_h1",
        "buys_h24",
        "sells_h24",
        "virtual_token_reserves",
        "virtual_quote_reserves",
        "real_token_reserves",
        "real_quote_reserves",
        "token_total_supply",
        "curve_complete",
        "progress",
        "decimals",
        "mint_authority",
        "freeze_authority",
        "token_program",
        "quote_is_sol",
        "global_fee_basis_points",
        "initial_real_token_reserves",
        "sol_usd",
        "sol_usd_source",
        "field_sources_json",
        "source_name",
        "endpoint",
        "fetched_at",
        "source_timestamp",
    )
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO pump_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row.get(column) for column in columns),
    )
    snapshot_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return int(snapshot_id)


def _json_sources(sources: dict[str, str]) -> str:
    import json

    return json.dumps(sources, sort_keys=True)


def _related_id(relationships: dict[str, object], name: str) -> str | None:
    node = relationships.get(name)
    if not isinstance(node, dict):
        return None
    data = node.get("data")
    if not isinstance(data, dict):
        return None
    token_id = data.get("id")
    return token_id if isinstance(token_id, str) else None


def _split_pool_name(name: str | None) -> tuple[str | None, str | None]:
    if not name or " / " not in name:
        return None, None
    left, right = name.split(" / ", 1)
    return left.strip() or None, right.strip() or None


def _num_text(value: object) -> str | None:
    number = _decimal(value)
    if number is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return format(number, "f")


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except Exception:
            return None
    return None


def _int_text(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _ms_to_iso(value: object) -> str | None:
    number = _int_text(value)
    if number is None:
        if isinstance(value, Decimal):
            number = int(value)
        else:
            return None
    if number > 10**12:
        number = number // 1000
    try:
        return iso_z(parse_timestamp(number))
    except (TypeError, ValueError, OSError):
        return None


def _rpc_value(payload: object) -> object:
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    return result.get("value")


def _rpc_values(payload: object) -> list[object] | None:
    value = _rpc_value(payload)
    if isinstance(value, list):
        return value
    return None


def _account_bytes(value: object) -> bytes | None:
    if not isinstance(value, dict):
        return None
    data = value.get("data")
    if isinstance(data, list) and data and isinstance(data[0], str):
        try:
            return base64.b64decode(data[0])
        except Exception:
            return None
    return None
