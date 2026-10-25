"""Fixed research defaults for the first paper-trading milestone."""

from decimal import Decimal

STRATEGY_ID = "sma_crossover"
STRATEGY_VERSION = "1.1.0"
STRATEGY_NAME = "Hourly SMA crossover"
FILL_MODEL = "next_candle_open"

# account_rules 1.0.0 was one open position and 300 USD.
# account_rules 2.0.0 is one open position per market, still 300 USD.
# account_rules 3.0.0 raises the shared paper cash to 5000 USD. The 10 USD cap is unchanged.
# account_rules 4.0.0 adds the metals market. Cash and the 10 USD cap stay the same.
ACCOUNT_RULES_ID = "account_rules"
ACCOUNT_RULES_VERSION = "4.0.0"
PREVIOUS_ACCOUNT_RULES_VERSION = "3.0.0"
CASH_ERA_PRIOR = "300"
CASH_ERA_CURRENT = "5000"
MARKET_CRYPTO = "crypto_spot"
MARKET_PUMPFUN = "pumpfun"
MARKET_STOCKS = "stocks"
MARKET_METALS = "metals"
MARKETS = (MARKET_CRYPTO, MARKET_PUMPFUN, MARKET_STOCKS, MARKET_METALS)

FAST_WINDOW = 5
SLOW_WINDOW = 20
TIMEFRAME = "1h"

STARTING_CASH = Decimal("5000")
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
