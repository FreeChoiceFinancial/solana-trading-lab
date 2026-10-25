"""Fixed metals research defaults. Rates are documented assumptions, not live quotes."""

from decimal import Decimal

MARKET = "metals"
TRADED_SYMBOL = "PAXG"
TRADED_SOURCE = "coinbase_exchange"
SILVER_SYMBOL = "SI"
SILVER_SOURCE = "yahoo_chart"

SMA_STRATEGY_ID = "metals_sma_trend"
RATIO_STRATEGY_ID = "metals_gold_silver_ratio"
BENCHMARK_ID = "metals_buy_hold"
STRATEGY_VERSION = "1.0.0"

FAST_WINDOW = 5
SLOW_WINDOW = 20
# 0.50% annualized. Actual/365 on entry notional. Not a fetched borrow tape.
SHORT_BORROW_APR = Decimal("0.005")

# Coinbase returns at most 300 daily candles per request. 280-day steps stay under that.
BACKFILL_START = "2021-01-01T00:00:00Z"
CHUNK_DAYS = 280

YAHOO_BARS = (
    ("GLD", "GLD"),
    ("SLV", "SLV"),
    ("PPLT", "PPLT"),
    ("PALL", "PALL"),
    ("GC=F", "GC"),
    ("SI=F", "SI"),
    ("PL=F", "PL"),
    ("PA=F", "PA"),
)
KRAKEN_DAILY = (("PAXG", "PAXGUSD"), ("XAUT", "XAUTUSD"))
COINGECKO_METALS = {"pax-gold": "PAXG", "tether-gold": "XAUT"}
