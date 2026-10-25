"""Fixed research defaults for the first paper-trading milestone."""

from decimal import Decimal

STRATEGY_ID = "sma_crossover"
STRATEGY_VERSION = "1.0.0"
STRATEGY_NAME = "Hourly SMA crossover"

FAST_WINDOW = 5
SLOW_WINDOW = 20
TIMEFRAME = "1h"

STARTING_CASH = Decimal("300")
MAX_NOTIONAL = Decimal("10")
MIN_NOTIONAL = Decimal("1")
# 0.6% taker-style fee. This is a configurable research assumption, not a live fee quote.
FEE_RATE = Decimal("0.006")
SLIPPAGE_BPS = Decimal("5")

SYMBOLS = ("BTC", "SOL")
SOURCE_PREFERENCE = ("coinbase_exchange", "kraken")

SOURCE_COINBASE = "coinbase_exchange"
SOURCE_COINGECKO = "coingecko"
SOURCE_KRAKEN = "kraken"

COINBASE_API = "https://api.exchange.coinbase.com"
COINGECKO_API = "https://api.coingecko.com"
KRAKEN_API = "https://api.kraken.com"

USER_AGENT = "sollab/0.1 (research paper-trading; read-only public market data)"

DISCLAIMER = (
    "Research and paper trading only. sollab does not place live orders, sign wallets, "
    "create tokens, or use brokerage credentials."
)
