sollab status
Research and paper trading only. sollab does not place live orders, sign wallets, create tokens, or use brokerage credentials.

Account rules 4.0.0 — Shared paper cash stays 5000 USD and the per-position cap stays 10 USD. One open position per market now includes metals. Long and short are allowed. A metals short accrues a paper borrow rate; earlier books are not rewritten.
Shared cash free 5000 locked 0 equity 5000 realized 0 unrealized 0 fees 0
Current paper account starts at 5000 USD under account_rules 4.0.0. The cap is still 10 USD notional per market, including metals. cash_era 300 results are preserved and are not part of this cash balance.
Current open positions:
- none

Historical cash era 300
Preserved paper results from the 300 USD account. Not recalculated at 5000 USD.
- cash_era=300 sma_crossover 1.0.0 period=full_window equity=297.07231211 realized=-2.82482382 unrealized=-0.10286407 open=short BTC
- open cash_era=300 crypto_spot short BTC notional=9.99974888

Backtest (cash era 5000)
- cash_era=5000 sma_crossover 1.1.0 period=train book=experiment equity=4997.71498064 realized=-2.24416309 unrealized=-0.04085627 fees=1.37954745 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=2.50895610 open=short BTC
- cash_era=5000 sma_crossover 1.1.0 period=validation book=experiment equity=4999.46518557 realized=-0.67351449 unrealized=0.13870006 fees=0.30258556 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.68476215 open=short SOL
- cash_era=5000 metals_buy_hold 1.0.0 period=train book=experiment equity=5003.31218774 realized=3.31218774 unrealized=0 fees=0.14071733 win_rate=1.00000000 profit_factor=None max_drawdown=3.24808912 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=train book=experiment equity=4999.36640130 realized=-1.85916153 unrealized=1.22556283 fees=1.02530030 win_rate=0.12500000 profit_factor=0.06633499 max_drawdown=1.99125115 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=train book=experiment equity=4996.33334652 realized=-3.61379183 unrealized=-0.05286165 fees=3.30215514 win_rate=0.18518519 profit_factor=0.20991058 max_drawdown=4.35039723 open=short PAXG
- cash_era=5000 metals_buy_hold 1.0.0 period=validation book=experiment equity=4998.97360881 realized=-1.02639119 unrealized=0 fees=0.11452869 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.84375091 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=validation book=experiment equity=4999.22542280 realized=-0.54418768 unrealized=-0.23038952 fees=0.29816308 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.16377785 open=long PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=validation book=experiment equity=4998.20525886 realized=-1.79474114 unrealized=0 fees=1.43785513 win_rate=0.25000000 profit_factor=0.19628459 max_drawdown=2.12684109 open=None
Rollup closed=64 win_rate=0.15625000 profit_factor=0.36448386 realized=-8.44376321 by_direction={'short': {'closed_trades': 42, 'wins': 6, 'win_rate': '0.14285714', 'profit_factor': '0.13208941', 'realized_pnl': '-7.17644232'}, 'long': {'closed_trades': 22, 'wins': 4, 'win_rate': '0.18181818', 'profit_factor': '0.74743611', 'realized_pnl': '-1.26732089'}} by_market={'crypto_spot': {'closed_trades': 13, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-2.91767758'}, 'metals': {'closed_trades': 51, 'wins': 10, 'win_rate': '0.19607843', 'profit_factor': '0.46704613', 'realized_pnl': '-5.52608563'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 13, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-2.91767758'}, 'metals_buy_hold 1.0.0': {'closed_trades': 2, 'wins': 1, 'win_rate': '0.50000000', 'profit_factor': '3.22702277', 'realized_pnl': '2.28579655'}, 'metals_sma_trend 1.0.0': {'closed_trades': 10, 'wins': 1, 'win_rate': '0.10000000', 'profit_factor': '0.05209734', 'realized_pnl': '-2.40334921'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 39, 'wins': 8, 'win_rate': '0.20512821', 'profit_factor': '0.20544051', 'realized_pnl': '-5.40853297'}}

Forward paper
- cash_era=5000 sma_crossover 1.1.0 period=forward book=experiment equity=4999.49868090 realized=-0.38702477 unrealized=-0.11429433 fees=0.29910558 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.51313237 open=long BTC
- cash_era=5000 metals_buy_hold 1.0.0 period=forward book=experiment equity=4999.62819179 realized=-0.37180821 unrealized=0 fees=0.11847955 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.70845379 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=forward book=experiment equity=5000.78809956 realized=-0.14972192 unrealized=0.93782148 fees=0.18016781 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.38381990 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=forward book=experiment equity=4998.27311994 realized=-1.72688006 unrealized=0 fees=1.55898939 win_rate=0.15384615 profit_factor=0.15760372 max_drawdown=1.95689271 open=None
Rollup closed=17 win_rate=0.11764706 profit_factor=0.10920391 realized=-2.63543496 by_direction={'long': {'closed_trades': 16, 'wins': 2, 'win_rate': '0.12500000', 'profit_factor': '0.11502499', 'realized_pnl': '-2.48571304'}, 'short': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.14972192'}} by_market={'crypto_spot': {'closed_trades': 2, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.38702477'}, 'metals': {'closed_trades': 15, 'wins': 2, 'win_rate': '0.13333333', 'profit_factor': '0.12563975', 'realized_pnl': '-2.24841019'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 2, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.38702477'}, 'metals_buy_hold 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.37180821'}, 'metals_sma_trend 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.14972192'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 13, 'wins': 2, 'win_rate': '0.15384615', 'profit_factor': '0.15760372', 'realized_pnl': '-1.72688006'}}

pump.fun
- run=2026-10-25T20:52:47.478364Z equity=5000.00000000 realized=0 unrealized=0 fees=0.00000000 open=None

Metals
One metals slot on the shared 5000 USD account. Runs below are also inside backtest and forward.
- metals_buy_hold 1.0.0 period=train equity=5003.31218774 realized=3.31218774 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=train equity=4999.36640130 realized=-1.85916153 unrealized=1.22556283 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=train equity=4996.33334652 realized=-3.61379183 unrealized=-0.05286165 open=short PAXG
- metals_buy_hold 1.0.0 period=validation equity=4998.97360881 realized=-1.02639119 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=validation equity=4999.22542280 realized=-0.54418768 unrealized=-0.23038952 open=long PAXG
- metals_gold_silver_ratio 1.0.0 period=validation equity=4998.20525886 realized=-1.79474114 unrealized=0 open=None
- metals_buy_hold 1.0.0 period=forward equity=4999.62819179 realized=-0.37180821 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=forward equity=5000.78809956 realized=-0.14972192 unrealized=0.93782148 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=forward equity=4998.27311994 realized=-1.72688006 unrealized=0 open=None

Schedule UTC: hourly 0 * * * *; pump.fun burst 15 */2 * * *
Last price collection 2026-10-25T23:00:14.993395Z
Last pump.fun collection 2026-10-25T20:52:47.323916Z
Last metals collection 2026-10-25T23:00:14.993395Z
Stored errors 8
- 2026-10-25T20:52:47.331339Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-25T20:52:47.331339Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-25T20:52:46.783Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-25T20:52:04.846004Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-25T20:52:04.846004Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-25T20:52:04.273Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-25T16:49:32.338329Z pump_frontend: HTTP 403 from https://frontend-api-v3.pump.fun/coins?offset=0&limit=1&sort=created_timestamp&order=DESC&includeNsfw=false: <!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><meta http-equiv="X-UA-Compatible" content="IE=Edge"><meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scal
