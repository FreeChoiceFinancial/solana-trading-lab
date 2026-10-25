"""Rug and liquidity flags. Every status is true, false, or unknown.

Unknown means a required input is missing from the stored snapshot. Aggregate
trade counts are never treated as a creator balance or a holder list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sollab.constants import MAX_NOTIONAL
from sollab.pumpconst import (
    PINNED_PROTOCOL_FEE_BPS,
    PUBLISHED_CREATOR_FEE_BPS,
    THIN_IMPACT,
    THIN_RESERVE_USD,
    WASH_MAX_BUYERS,
    WASH_MIN_BUYS,
    YOUNG_SECONDS,
)
from sollab.pumpcurve import quote_buy_exact_sol_in
from sollab.timeutil import parse_timestamp

VERY_YOUNG = "very_young"
WASH_TRADE_LIKE = "wash_trade_like"
THIN_LIQUIDITY = "thin_liquidity"
MINT_AUTHORITY_ACTIVE = "mint_authority_active"
FREEZE_AUTHORITY_ACTIVE = "freeze_authority_active"
CREATOR_HOLDING_PCT = "creator_holding_pct"
TOP_HOLDER_CONCENTRATION = "top_holder_concentration"
CREATOR_SELLING = "creator_selling"

BLOCKING_FLAGS = (
    VERY_YOUNG,
    WASH_TRADE_LIKE,
    THIN_LIQUIDITY,
    MINT_AUTHORITY_ACTIVE,
    FREEZE_AUTHORITY_ACTIVE,
)
INFORMATIONAL_FLAGS = (
    CREATOR_HOLDING_PCT,
    TOP_HOLDER_CONCENTRATION,
    CREATOR_SELLING,
)

VERY_YOUNG_RULE = (
    f"true when fetched_at minus created_at is under {YOUNG_SECONDS} seconds; "
    "unknown when either timestamp is missing or created_at is more than 5 seconds "
    "ahead of fetched_at; false otherwise."
)
WASH_RULE = (
    f"true when buyers_m5 <= {WASH_MAX_BUYERS} and buys_m5 >= {WASH_MIN_BUYS}; "
    "unknown when either count is missing; false otherwise. "
    "Aggregate sells are not used as a stand-in for unique buyers."
)
THIN_RULE = (
    f"true when a {MAX_NOTIONAL} USD spendable buy on the stored virtual reserves, "
    f"using {PINNED_PROTOCOL_FEE_BPS} bps protocol and {PUBLISHED_CREATOR_FEE_BPS} bps creator "
    f"before extra slippage, costs more than {THIN_IMPACT} above spot, returns zero tokens, "
    f"or asks for more tokens than real_token_reserves; if reserves or SOL/USD are missing and "
    f"reserve_usd < {THIN_RESERVE_USD}, true; unknown when impact cannot be computed and "
    "reserve_usd is missing or at least 10; false when the impact is computed and within the limit."
)
MINT_RULE = (
    "true when mint_authority is a pubkey; false when the stored value is none; "
    "unknown when the mint account was not decoded."
)
FREEZE_RULE = (
    "true when freeze_authority is a pubkey; false when the stored value is none; "
    "unknown when the mint account was not decoded."
)
CREATOR_HOLDING_RULE = (
    "unknown. No stored source includes the creator wallet's token balance, so a holding "
    "percent is not computed and is not inferred from trade counts."
)
TOP_HOLDER_RULE = (
    "unknown. No stored source includes a holder list or a top-holder percentage."
)
CREATOR_SELLING_RULE = (
    "unknown. No stored source includes per-wallet trades, so creator selling is not "
    "inferred from aggregate sell counts."
)


@dataclass(frozen=True)
class FlagResult:
    flag: str
    status: str
    rule: str
    inputs: dict[str, object]

    def inputs_json(self) -> str:
        return json.dumps(self.inputs, sort_keys=True, default=_json_default)


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"cannot encode {type(value).__name__}")


def _status_authority(value: str | None, *, flag: str, rule: str) -> FlagResult:
    if value is None or value == "":
        status = "unknown"
    elif value == "none":
        status = "false"
    else:
        status = "true"
    return FlagResult(flag, status, rule, {"authority": value})


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _dec_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return None
    return None


def _usd_to_lamports(usd: Decimal, sol_usd: Decimal) -> int:
    if sol_usd <= 0:
        raise ValueError("sol price must be positive")
    lamports = (usd / sol_usd) * Decimal(1_000_000_000)
    return int(lamports.to_integral_value(rounding="ROUND_DOWN"))


def compute_flags(snapshot: dict[str, object]) -> list[FlagResult]:
    """Compute the eight flags from one stored snapshot dict. Does not fetch."""
    return [
        _very_young(snapshot),
        _wash(snapshot),
        _thin(snapshot),
        _status_authority(snapshot.get("mint_authority"), flag=MINT_AUTHORITY_ACTIVE, rule=MINT_RULE),
        _status_authority(
            snapshot.get("freeze_authority"),
            flag=FREEZE_AUTHORITY_ACTIVE,
            rule=FREEZE_RULE,
        ),
        FlagResult(
            CREATOR_HOLDING_PCT,
            "unknown",
            CREATOR_HOLDING_RULE,
            {"creator": snapshot.get("creator"), "creator_balance": None},
        ),
        FlagResult(TOP_HOLDER_CONCENTRATION, "unknown", TOP_HOLDER_RULE, {"holder_list": None}),
        FlagResult(
            CREATOR_SELLING,
            "unknown",
            CREATOR_SELLING_RULE,
            {"creator_trades": None, "sells_m5": snapshot.get("sells_m5")},
        ),
    ]


def _very_young(snapshot: dict[str, object]) -> FlagResult:
    created = snapshot.get("created_at")
    fetched = snapshot.get("fetched_at")
    inputs: dict[str, object] = {"created_at": created, "fetched_at": fetched, "young_seconds": YOUNG_SECONDS}
    if not isinstance(created, str) or not isinstance(fetched, str):
        return FlagResult(VERY_YOUNG, "unknown", VERY_YOUNG_RULE, inputs)
    try:
        created_at = parse_timestamp(created)
        fetched_at = parse_timestamp(fetched)
    except (TypeError, ValueError):
        return FlagResult(VERY_YOUNG, "unknown", VERY_YOUNG_RULE, inputs)
    age = (fetched_at - created_at).total_seconds()
    inputs["age_seconds"] = age
    if age < -5:
        return FlagResult(VERY_YOUNG, "unknown", VERY_YOUNG_RULE, inputs)
    status = "true" if age < YOUNG_SECONDS else "false"
    return FlagResult(VERY_YOUNG, status, VERY_YOUNG_RULE, inputs)


def _wash(snapshot: dict[str, object]) -> FlagResult:
    buyers = _int_or_none(snapshot.get("buyers_m5"))
    buys = _int_or_none(snapshot.get("buys_m5"))
    inputs = {"buyers_m5": buyers, "buys_m5": buys}
    if buyers is None or buys is None:
        return FlagResult(WASH_TRADE_LIKE, "unknown", WASH_RULE, inputs)
    status = "true" if buyers <= WASH_MAX_BUYERS and buys >= WASH_MIN_BUYS else "false"
    return FlagResult(WASH_TRADE_LIKE, status, WASH_RULE, inputs)


def _thin(snapshot: dict[str, object]) -> FlagResult:
    reserve = _dec_or_none(snapshot.get("reserve_usd"))
    sol_usd = _dec_or_none(snapshot.get("sol_usd"))
    virtual_token = _int_or_none(snapshot.get("virtual_token_reserves"))
    virtual_quote = _int_or_none(snapshot.get("virtual_quote_reserves"))
    real_token = _int_or_none(snapshot.get("real_token_reserves"))
    decimals = _int_or_none(snapshot.get("decimals"))
    inputs: dict[str, object] = {
        "reserve_usd": None if reserve is None else format(reserve, "f"),
        "sol_usd": None if sol_usd is None else format(sol_usd, "f"),
        "virtual_token_reserves": virtual_token,
        "virtual_quote_reserves": virtual_quote,
        "real_token_reserves": real_token,
        "decimals": decimals,
        "notional_usd": format(MAX_NOTIONAL, "f"),
    }
    if (
        virtual_token
        and virtual_quote
        and decimals is not None
        and decimals >= 0
        and sol_usd is not None
        and sol_usd > 0
    ):
        spendable = _usd_to_lamports(MAX_NOTIONAL, sol_usd)
        inputs["spendable_lamports"] = spendable
        if spendable <= 0:
            return FlagResult(THIN_LIQUIDITY, "true", THIN_RULE, inputs)
        quote = quote_buy_exact_sol_in(
            virtual_token_reserves=virtual_token,
            virtual_quote_reserves=virtual_quote,
            spendable_lamports=spendable,
            protocol_fee_bps=PINNED_PROTOCOL_FEE_BPS,
            creator_fee_bps=PUBLISHED_CREATOR_FEE_BPS,
            real_token_reserves=real_token,
        )
        inputs["tokens_out"] = quote.tokens_out
        inputs["exceeds_real_reserves"] = quote.exceeds_real_reserves
        if quote.tokens_out <= 0 or quote.exceeds_real_reserves:
            return FlagResult(THIN_LIQUIDITY, "true", THIN_RULE, inputs)
        spot = Decimal(virtual_quote) * (Decimal(10) ** decimals) / Decimal(virtual_token)
        effective = Decimal(spendable) / (Decimal(quote.tokens_out) / (Decimal(10) ** decimals))
        impact = (effective / spot) - Decimal(1)
        inputs["impact"] = format(impact, "f")
        status = "true" if impact > THIN_IMPACT else "false"
        return FlagResult(THIN_LIQUIDITY, status, THIN_RULE, inputs)
    if reserve is not None and reserve < THIN_RESERVE_USD:
        return FlagResult(THIN_LIQUIDITY, "true", THIN_RULE, inputs)
    return FlagResult(THIN_LIQUIDITY, "unknown", THIN_RULE, inputs)


def age_seconds(created_at: datetime, fetched_at: datetime) -> float:
    return (fetched_at - created_at).total_seconds()
