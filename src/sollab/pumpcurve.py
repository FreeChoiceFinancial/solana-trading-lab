"""Bonding-curve quotes, PDA derivation, and account decoding.

Buy math follows the `buy_exact_sol_in` quote in the public pump IDL.
Sell math is the paper model's constant-product inverse (`paper_sell_v1`);
the IDL page we read does not publish a numbered sell formula.
No transaction is built here.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from decimal import Decimal

from sollab.pumpconst import (
    EXTRA_SLIPPAGE_BPS,
    GLOBAL_PDA,
    INITIAL_REAL_TOKEN_RESERVES,
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    PUMP_PROGRAM,
    TOKEN_TOTAL_SUPPLY,
)

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {char: index for index, char in enumerate(_ALPHABET)}
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)
_GLOBAL_DISC = hashlib.sha256(b"account:Global").digest()[:8]
_CURVE_DISC = hashlib.sha256(b"account:BondingCurve").digest()[:8]


def b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    chars: list[str] = []
    while number:
        number, remainder = divmod(number, 58)
        chars.append(_ALPHABET[remainder])
    pad = 0
    for byte in raw:
        if byte == 0:
            pad += 1
        else:
            break
    encoded = "".join(reversed(chars)) if chars else ""
    return ("1" * pad) + encoded


def b58decode(text: str) -> bytes:
    number = 0
    for char in text:
        try:
            number = number * 58 + _INDEX[char]
        except KeyError as exc:
            raise ValueError(f"invalid base58: {text}") from exc
    if number.bit_length() > 256:
        raise ValueError("base58 value does not fit a 32-byte pubkey")
    return number.to_bytes(32, "big")


def _on_curve(pubkey: bytes) -> bool:
    y_full = int.from_bytes(pubkey, "little")
    sign = (y_full >> 255) & 1
    y = y_full & ((1 << 255) - 1)
    if y >= _P:
        return False
    y2 = (y * y) % _P
    u = (y2 - 1) % _P
    v = (_D * y2 + 1) % _P
    x2 = (u * pow(v, _P - 2, _P)) % _P
    if x2 == 0:
        return sign == 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = (x * _I) % _P
    if (x * x - x2) % _P != 0:
        return False
    if (x & 1) != sign:
        x = _P - x
    return True


def find_program_address(seeds: list[bytes], program: bytes) -> tuple[bytes, int]:
    """Solana PDA: sha256(seeds || bump || program || 'ProgramDerivedAddress'), off-curve."""
    for bump in range(255, -1, -1):
        digest = hashlib.sha256(b"".join(seeds) + bytes([bump]) + program + b"ProgramDerivedAddress").digest()
        if not _on_curve(digest):
            return digest, bump
    raise RuntimeError("no program derived address")


def bonding_curve_pda(mint: str) -> str:
    address, _bump = find_program_address(
        [b"bonding-curve", b58decode(mint)],
        b58decode(PUMP_PROGRAM),
    )
    return b58encode(address)


def global_pda() -> str:
    address, _bump = find_program_address([b"global"], b58decode(PUMP_PROGRAM))
    return b58encode(address)


def bonding_curve_market_cap_lamports(
    virtual_quote_reserves: int,
    virtual_token_reserves: int,
    mint_supply: int,
) -> int:
    """Market cap in quote lamports. Integer division, as in the fee-program docs."""
    if virtual_token_reserves <= 0 or virtual_quote_reserves < 0 or mint_supply < 0:
        raise ValueError("reserves must be positive")
    return virtual_quote_reserves * mint_supply // virtual_token_reserves


def documented_initial_market_cap_lamports() -> int:
    return bonding_curve_market_cap_lamports(
        INITIAL_VIRTUAL_SOL_RESERVES,
        INITIAL_VIRTUAL_TOKEN_RESERVES,
        TOKEN_TOTAL_SUPPLY,
    )


def _u64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


@dataclass(frozen=True)
class GlobalConfig:
    initial_virtual_token_reserves: int
    initial_virtual_quote_reserves: int
    initial_real_token_reserves: int
    token_total_supply: int
    fee_basis_points: int


def decode_global(data: bytes) -> GlobalConfig | None:
    """Decode the prefix of Global. Returns None if the discriminator or known initials moved."""
    if len(data) < 113 or data[:8] != _GLOBAL_DISC:
        return None
    config = GlobalConfig(
        initial_virtual_token_reserves=_u64(data, 73),
        initial_virtual_quote_reserves=_u64(data, 81),
        initial_real_token_reserves=_u64(data, 89),
        token_total_supply=_u64(data, 97),
        fee_basis_points=_u64(data, 105),
    )
    if (
        config.initial_virtual_token_reserves != INITIAL_VIRTUAL_TOKEN_RESERVES
        or config.initial_virtual_quote_reserves != INITIAL_VIRTUAL_SOL_RESERVES
        or config.initial_real_token_reserves != INITIAL_REAL_TOKEN_RESERVES
        or config.token_total_supply != TOKEN_TOTAL_SUPPLY
    ):
        return None
    if global_pda() != GLOBAL_PDA:
        return None
    return config


@dataclass(frozen=True)
class CurveAccount:
    virtual_token_reserves: int
    virtual_quote_reserves: int
    real_token_reserves: int
    real_quote_reserves: int
    token_total_supply: int
    complete: bool
    creator: str | None
    quote_mint: str | None
    quote_mint_is_native_sol: bool | None


def decode_bonding_curve(data: bytes) -> CurveAccount | None:
    """Decode BondingCurve. Missing trailing fields stay unknown instead of becoming zero pubkeys."""
    if len(data) < 49 or data[:8] != _CURVE_DISC:
        return None
    creator: str | None = None
    if len(data) >= 81:
        raw_creator = data[49:81]
        creator = None if raw_creator == bytes(32) else b58encode(raw_creator)
    quote_mint: str | None = None
    quote_native: bool | None = None
    if len(data) >= 115:
        raw_quote = data[83:115]
        quote_native = raw_quote == bytes(32)
        quote_mint = None if quote_native else b58encode(raw_quote)
    return CurveAccount(
        virtual_token_reserves=_u64(data, 8),
        virtual_quote_reserves=_u64(data, 16),
        real_token_reserves=_u64(data, 24),
        real_quote_reserves=_u64(data, 32),
        token_total_supply=_u64(data, 40),
        complete=bool(data[48]),
        creator=creator,
        quote_mint=quote_mint,
        quote_mint_is_native_sol=quote_native,
    )


@dataclass(frozen=True)
class MintAccount:
    decimals: int
    supply: int
    mint_authority: str | None
    freeze_authority: str | None
    token_program: str | None


def decode_mint(data: bytes, owner: str | None) -> MintAccount | None:
    """SPL and Token-2022 mints share the 82-byte prefix. Shorter data is unknown."""
    if len(data) < 82:
        return None
    mint_option = int.from_bytes(data[0:4], "little")
    freeze_option = int.from_bytes(data[46:50], "little")
    if mint_option not in {0, 1} or freeze_option not in {0, 1}:
        return None
    mint_authority = "none" if mint_option == 0 else b58encode(data[4:36])
    freeze_authority = "none" if freeze_option == 0 else b58encode(data[50:82])
    return MintAccount(
        decimals=data[44],
        supply=int.from_bytes(data[36:44], "little"),
        mint_authority=mint_authority,
        freeze_authority=freeze_authority,
        token_program=owner,
    )


def progress_ratio(
    real_token_reserves: int,
    initial_real_token_reserves: int,
    complete: bool,
) -> Decimal | None:
    """Fraction of the initial real token inventory sold. None when the inputs disagree."""
    del complete
    if initial_real_token_reserves <= 0 or real_token_reserves < 0:
        return None
    if real_token_reserves > initial_real_token_reserves:
        return None
    sold = initial_real_token_reserves - real_token_reserves
    return Decimal(sold) / Decimal(initial_real_token_reserves)


def ceil_div(numerator: int, denominator: int) -> int:
    if denominator <= 0 or numerator < 0:
        raise ValueError("ceil_div requires a non-negative numerator and a positive denominator")
    return (numerator + denominator - 1) // denominator


@dataclass(frozen=True)
class BuyQuote:
    spendable_lamports: int
    net_lamports: int
    curve_fee_lamports: int
    protocol_fee_lamports: int
    creator_fee_lamports: int
    tokens_out: int
    exceeds_real_reserves: bool


def quote_buy_exact_sol_in(
    *,
    virtual_token_reserves: int,
    virtual_quote_reserves: int,
    spendable_lamports: int,
    protocol_fee_bps: int,
    creator_fee_bps: int,
    real_token_reserves: int | None = None,
) -> BuyQuote:
    """IDL quote: fees come out of spendable SOL, then constant-product tokens with the -1 guard."""
    if virtual_token_reserves <= 0 or virtual_quote_reserves <= 0 or spendable_lamports <= 0:
        raise ValueError("buy quote requires positive reserves and spendable lamports")
    total_bps = protocol_fee_bps + creator_fee_bps
    if protocol_fee_bps < 0 or creator_fee_bps < 0 or total_bps >= 10_000:
        raise ValueError("fee bps out of range")
    net = (spendable_lamports * 10_000) // (10_000 + total_bps)
    protocol_fee = ceil_div(net * protocol_fee_bps, 10_000)
    creator_fee = ceil_div(net * creator_fee_bps, 10_000)
    if net + protocol_fee + creator_fee > spendable_lamports:
        net -= net + protocol_fee + creator_fee - spendable_lamports
    if net <= 1:
        tokens = 0
    else:
        tokens = ((net - 1) * virtual_token_reserves) // (virtual_quote_reserves + net - 1)
    exceeds = real_token_reserves is not None and tokens > real_token_reserves
    curve_fee = spendable_lamports - net if 0 <= net <= spendable_lamports else protocol_fee + creator_fee
    return BuyQuote(
        spendable_lamports=spendable_lamports,
        net_lamports=net,
        curve_fee_lamports=curve_fee,
        protocol_fee_lamports=protocol_fee,
        creator_fee_lamports=creator_fee,
        tokens_out=tokens,
        exceeds_real_reserves=exceeds,
    )


@dataclass(frozen=True)
class SellQuote:
    gross_lamports: int
    protocol_fee_lamports: int
    creator_fee_lamports: int
    net_lamports: int
    slipped_lamports: int
    model: str = "paper_sell_v1"


def quote_sell_exact_tokens_in(
    *,
    virtual_token_reserves: int,
    virtual_quote_reserves: int,
    tokens_in: int,
    protocol_fee_bps: int,
    creator_fee_bps: int,
    slippage_bps: int = EXTRA_SLIPPAGE_BPS,
) -> SellQuote:
    """paper_sell_v1: constant-product SOL out, fees taken from output, then extra slippage."""
    if virtual_token_reserves <= 0 or virtual_quote_reserves <= 0 or tokens_in <= 0:
        raise ValueError("sell quote requires positive reserves and tokens")
    if protocol_fee_bps < 0 or creator_fee_bps < 0 or slippage_bps < 0 or slippage_bps > 10_000:
        raise ValueError("bps out of range")
    if protocol_fee_bps + creator_fee_bps >= 10_000:
        raise ValueError("fee bps out of range")
    gross = (tokens_in * virtual_quote_reserves) // (virtual_token_reserves + tokens_in)
    protocol_fee = ceil_div(gross * protocol_fee_bps, 10_000)
    creator_fee = ceil_div(gross * creator_fee_bps, 10_000)
    net = gross - protocol_fee - creator_fee
    if net < 0:
        net = 0
    slipped = net * (10_000 - slippage_bps) // 10_000
    return SellQuote(
        gross_lamports=gross,
        protocol_fee_lamports=protocol_fee,
        creator_fee_lamports=creator_fee,
        net_lamports=net,
        slipped_lamports=slipped,
    )


def apply_buy_slippage(tokens_out: int, slippage_bps: int = EXTRA_SLIPPAGE_BPS) -> int:
    if tokens_out < 0 or slippage_bps < 0 or slippage_bps > 10_000:
        raise ValueError("slippage inputs out of range")
    return tokens_out * (10_000 - slippage_bps) // 10_000


def priority_fee_lamports(micro_lamports_per_cu: int, compute_units: int) -> int:
    if micro_lamports_per_cu < 0 or compute_units < 0:
        raise ValueError("priority fee inputs must be non-negative")
    return ceil_div(micro_lamports_per_cu * compute_units, 1_000_000)


def median_observed(values: list[int]) -> int | None:
    """Upper median, which is one of the observed samples."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def encode_curve_for_test(
    *,
    virtual_token: int,
    virtual_quote: int,
    real_token: int,
    real_quote: int,
    supply: int = TOKEN_TOTAL_SUPPLY,
    complete: bool = False,
    creator: bytes | None = None,
) -> bytes:
    """Minimal BondingCurve bytes through the creator field, for unit tests."""
    body = struct.pack(
        "<QQQQQ?",
        virtual_token,
        virtual_quote,
        real_token,
        real_quote,
        supply,
        complete,
    )
    # struct "? " does not insert alignment before the bool when we pack only trailing bool
    # after five Q values. Verify length is 41.
    if len(body) != 41:
        raise RuntimeError(f"unexpected curve prefix length {len(body)}")
    raw_creator = bytes(32) if creator is None else creator
    if len(raw_creator) != 32:
        raise ValueError("creator must be 32 bytes")
    return _CURVE_DISC + body + raw_creator


def encode_global_for_test(fee_basis_points: int = 95) -> bytes:
    raw = bytearray(113)
    raw[:8] = _GLOBAL_DISC
    raw[8] = 1
    struct.pack_into("<Q", raw, 73, INITIAL_VIRTUAL_TOKEN_RESERVES)
    struct.pack_into("<Q", raw, 81, INITIAL_VIRTUAL_SOL_RESERVES)
    struct.pack_into("<Q", raw, 89, INITIAL_REAL_TOKEN_RESERVES)
    struct.pack_into("<Q", raw, 97, TOKEN_TOTAL_SUPPLY)
    struct.pack_into("<Q", raw, 105, fee_basis_points)
    return bytes(raw)


def encode_mint_for_test(*, decimals: int = 6, authority: bytes | None = None, freeze: bytes | None = None) -> bytes:
    raw = bytearray(82)
    if authority is None:
        struct.pack_into("<I", raw, 0, 0)
    else:
        struct.pack_into("<I", raw, 0, 1)
        raw[4:36] = authority
    struct.pack_into("<Q", raw, 36, TOKEN_TOTAL_SUPPLY)
    raw[44] = decimals
    raw[45] = 1
    if freeze is None:
        struct.pack_into("<I", raw, 46, 0)
    else:
        struct.pack_into("<I", raw, 46, 1)
        raw[50:82] = freeze
    return bytes(raw)
