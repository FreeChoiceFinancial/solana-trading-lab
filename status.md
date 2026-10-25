sollab status
Research and paper trading only. sollab does not place live orders, sign wallets, create tokens, or use brokerage credentials.

Account rules 3.0.0 — Shared paper cash is 5000 USD. One open position per market still holds, and the per-position cap stays 10 USD. Earlier 300 USD books stay stored with cash_era 300 and are not recalculated.
Shared cash free 5000 locked 0 equity 5000 realized 0 unrealized 0 fees 0
Current paper account starts at 5000 USD under account_rules 3.0.0. The cap is still 10 USD notional per market. cash_era 300 results are preserved and are not part of this cash balance.
Current open positions:
- none

Historical cash era 300
Preserved paper results from the 300 USD account. Not recalculated at 5000 USD.
- cash_era=300 sma_crossover 1.0.0 period=full_window equity=297.07231211 realized=-2.82482382 unrealized=-0.10286407 open=short BTC
- open cash_era=300 crypto_spot short BTC notional=9.99974888

Backtest (cash era 5000)
- cash_era=5000 sma_crossover 1.1.0 period=train book=experiment equity=4997.67552245 realized=-2.24416309 unrealized=-0.08031446 fees=1.37954745 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=2.50895610 open=short BTC
- cash_era=5000 sma_crossover 1.1.0 period=validation book=experiment equity=4999.64037113 realized=-0.35962887 unrealized=0 fees=0.23927524 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.35962887 open=None
Rollup closed=13 win_rate=0.00000000 profit_factor=0.00000000 realized=-2.60379196 by_direction={'short': {'closed_trades': 5, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-1.02997447'}, 'long': {'closed_trades': 8, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-1.57381749'}} by_market={'crypto_spot': {'closed_trades': 13, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-2.60379196'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 13, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-2.60379196'}}

Forward paper
- cash_era=5000 sma_crossover 1.1.0 period=forward book=experiment equity=4999.61297523 realized=-0.38702477 unrealized=0 fees=0.23910572 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.39883804 open=None
Rollup closed=2 win_rate=0.00000000 profit_factor=0.00000000 realized=-0.38702477 by_direction={'long': {'closed_trades': 2, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.38702477'}} by_market={'crypto_spot': {'closed_trades': 2, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.38702477'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 2, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.38702477'}}

pump.fun
- run=2026-10-25T16:49:38.138288Z equity=287.11542881 realized=0 unrealized=0 fees=0.00000000 open=None

Last price collection 2026-10-25T19:53:13.866350Z
Last pump.fun collection 2026-10-25T16:49:32.334254Z
Stored errors 4
- 2026-10-25T16:49:32.338329Z pump_frontend: HTTP 403 from https://frontend-api-v3.pump.fun/coins?offset=0&limit=1&sort=created_timestamp&order=DESC&includeNsfw=false: <!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><meta http-equiv="X-UA-Compatible" content="IE=Edge"><meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scal
- 2026-10-25T16:49:32.338329Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-25T16:49:31.745Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-25T16:48:50.250134Z pump_frontend: HTTP 403 from https://frontend-api-v3.pump.fun/coins?offset=0&limit=1&sort=created_timestamp&order=DESC&includeNsfw=false: <!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><meta http-equiv="X-UA-Compatible" content="IE=Edge"><meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scal
- 2026-10-25T16:48:50.250134Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-25T16:48:49.678Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
