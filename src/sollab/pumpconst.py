"""Pinned pump.fun paper-model constants.

Protocol fee bps is checked against the decoded Global account at run time.
Creator fee bps is the published bonding-curve schedule; it is not a u64 we
found in that Global account. See docs/pumpfun.md.
"""

from decimal import Decimal

PUMP_STRATEGY_ID = "bonding_curve_momentum"
PUMP_STRATEGY_VERSION = "1.0.0"
PUMP_STRATEGY_NAME = "Bonding-curve momentum"
PUMP_MARKET = "pump.fun"

# https://pump.fun/docs/fees Last Updated 17 October 2026, accessed 2026-10-25.
# Bonding curve, SOL and USDC quotes: creator 0.300%, protocol 0.95%, LP 0%.
PUBLISHED_CREATOR_FEE_BPS = 30
PINNED_PROTOCOL_FEE_BPS = 95

EXTRA_SLIPPAGE_BPS = 50
EXECUTION_DELAY_SECONDS = 30
# Solana charges 5000 lamports per signature. The paper model assumes one signature.
BASE_SIGNATURE_LAMPORTS = 5000
# Not measured from a transaction. A documented compute-unit assumption for the priority fee.
ASSUMED_SWAP_COMPUTE_UNITS = 200_000

MIN_PROGRESS = Decimal("0.20")
MAX_PROGRESS = Decimal("0.90")
MIN_BUYS_M5 = 8
MIN_BUYERS_M5 = 4
YOUNG_SECONDS = 120
WASH_MAX_BUYERS = 2
WASH_MIN_BUYS = 15
THIN_IMPACT = Decimal("0.15")
THIN_RESERVE_USD = Decimal("10")
TAKE_PROFIT = Decimal("0.40")
STOP_LOSS = Decimal("0.20")
MAX_HOLD_SECONDS = 1200

WSOL_MINT = "So11111111111111111111111111111111111111112"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
GLOBAL_PDA = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"

# Documented initial curve parameters. Live Global is checked against these.
INITIAL_VIRTUAL_TOKEN_RESERVES = 1_073_000_000_000_000
INITIAL_VIRTUAL_SOL_RESERVES = 30_000_000_000
INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000
TOKEN_TOTAL_SUPPLY = 1_000_000_000_000_000

SIMULATED_LABEL = "SIMULATED_PUMPFUN_NOT_A_LIVE_TRADE"
