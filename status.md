sollab status
Research and paper trading only. sollab does not place live orders, sign wallets, create tokens, or use brokerage credentials.

Account rules 4.0.0 — Shared paper cash stays 5000 USD and the per-position cap stays 10 USD. One open position per market now includes metals. Long and short are allowed. A metals short accrues a paper borrow rate; earlier books are not rewritten.
Shared cash free 4976.91525922 locked 19.99996459 equity 4997.65392868 realized -3.08477619 unrealized 0.73870487 fees 2.27881626
Current paper account starts at 5000 USD under account_rules 4.0.0. Open positions, locked notional, and P&L add every cash_era 5000 forward book, including the latest pump.fun book. Train, validation, and cash_era 300 stay out of these totals.
Current open positions:
- crypto_spot experiment sma_crossover 1.1.0 long SOL notional=9.99999987 opened_at=2026-10-26T13:00:00Z
- metals experiment metals_sma_trend 1.0.0 short PAXG notional=9.99996472 opened_at=2026-09-01T00:00:00Z

Historical cash era 300
Preserved paper results from the 300 USD account. Not recalculated at 5000 USD.
- cash_era=300 sma_crossover 1.0.0 period=full_window equity=297.07231211 realized=-2.82482382 unrealized=-0.10286407 open=short BTC
- open cash_era=300 crypto_spot short BTC notional=9.99974888

Backtest (cash era 5000)
- cash_era=5000 sma_crossover 1.1.0 period=train book=experiment equity=4997.73159822 realized=-2.24416309 unrealized=-0.02423869 fees=1.37954745 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=2.51822830 open=short BTC
- cash_era=5000 sma_crossover 1.1.0 period=validation book=experiment equity=4999.80733457 realized=-0.16895372 unrealized=-0.02371171 fees=0.17970187 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.38434449 open=long SOL
- cash_era=5000 metals_buy_hold 1.0.0 period=train book=experiment equity=5003.31218774 realized=3.31218774 unrealized=0 fees=0.14071733 win_rate=1.00000000 profit_factor=None max_drawdown=3.24808912 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=train book=experiment equity=4999.36640130 realized=-1.85916153 unrealized=1.22556283 fees=1.02530030 win_rate=0.12500000 profit_factor=0.06633499 max_drawdown=1.99125115 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=train book=experiment equity=4996.33334652 realized=-3.61379183 unrealized=-0.05286165 fees=3.30215514 win_rate=0.18518519 profit_factor=0.20991058 max_drawdown=4.35039723 open=short PAXG
- cash_era=5000 metals_buy_hold 1.0.0 period=validation book=experiment equity=4998.97360881 realized=-1.02639119 unrealized=0 fees=0.11452869 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.84375091 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=validation book=experiment equity=4999.22542280 realized=-0.54418768 unrealized=-0.23038952 fees=0.29816308 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.16377785 open=long PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=validation book=experiment equity=4998.20525886 realized=-1.79474114 unrealized=0 fees=1.43785513 win_rate=0.25000000 profit_factor=0.19628459 max_drawdown=2.12684109 open=None
Rollup closed=63 win_rate=0.15873016 profit_factor=0.37887172 realized=-7.93920244 by_direction={'short': {'closed_trades': 40, 'wins': 6, 'win_rate': '0.15000000', 'profit_factor': '0.14380272', 'realized_pnl': '-6.50292783'}, 'long': {'closed_trades': 23, 'wins': 4, 'win_rate': '0.17391304', 'profit_factor': '0.72308918', 'realized_pnl': '-1.43627461'}} by_market={'crypto_spot': {'closed_trades': 12, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-2.41311681'}, 'metals': {'closed_trades': 51, 'wins': 10, 'win_rate': '0.19607843', 'profit_factor': '0.46704613', 'realized_pnl': '-5.52608563'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 12, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-2.41311681'}, 'metals_buy_hold 1.0.0': {'closed_trades': 2, 'wins': 1, 'win_rate': '0.50000000', 'profit_factor': '3.22702277', 'realized_pnl': '2.28579655'}, 'metals_sma_trend 1.0.0': {'closed_trades': 10, 'wins': 1, 'win_rate': '0.10000000', 'profit_factor': '0.05209734', 'realized_pnl': '-2.40334921'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 39, 'wins': 8, 'win_rate': '0.20512821', 'profit_factor': '0.20544051', 'realized_pnl': '-5.40853297'}}

Forward paper
- cash_era=5000 sma_crossover 1.1.0 period=forward book=experiment equity=4999.43563673 realized=-0.37728339 unrealized=-0.18707988 fees=0.42009434 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.70186615 open=long SOL
- cash_era=5000 metals_buy_hold 1.0.0 period=forward book=experiment equity=4999.64100870 realized=-0.35899130 unrealized=0 fees=0.11855692 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.69563688 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=forward book=experiment equity=5000.77606283 realized=-0.14972192 unrealized=0.92578475 fees=0.18016781 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.38381990 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=forward book=experiment equity=4998.27311994 realized=-1.72688006 unrealized=0 fees=1.55898939 win_rate=0.15384615 profit_factor=0.15760372 max_drawdown=1.95689271 open=None
Rollup closed=18 win_rate=0.11111111 profit_factor=0.11004297 realized=-2.61287667 by_direction={'short': {'closed_trades': 4, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.52700531'}, 'long': {'closed_trades': 14, 'wins': 2, 'win_rate': '0.14285714', 'profit_factor': '0.13411702', 'realized_pnl': '-2.08587136'}} by_market={'crypto_spot': {'closed_trades': 3, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.37728339'}, 'metals': {'closed_trades': 15, 'wins': 2, 'win_rate': '0.13333333', 'profit_factor': '0.12626910', 'realized_pnl': '-2.23559328'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 3, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.37728339'}, 'metals_buy_hold 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.35899130'}, 'metals_sma_trend 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.14972192'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 13, 'wins': 2, 'win_rate': '0.15384615', 'profit_factor': '0.15760372', 'realized_pnl': '-1.72688006'}}

pump.fun
- run=2026-10-26T18:57:04.549706Z equity=4999.52810048 realized=-0.47189952 unrealized=0 fees=0.00100780 open=None

Metals
One metals slot on the shared 5000 USD account. Runs below are also inside backtest and forward.
- metals_buy_hold 1.0.0 period=train equity=5003.31218774 realized=3.31218774 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=train equity=4999.36640130 realized=-1.85916153 unrealized=1.22556283 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=train equity=4996.33334652 realized=-3.61379183 unrealized=-0.05286165 open=short PAXG
- metals_buy_hold 1.0.0 period=validation equity=4998.97360881 realized=-1.02639119 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=validation equity=4999.22542280 realized=-0.54418768 unrealized=-0.23038952 open=long PAXG
- metals_gold_silver_ratio 1.0.0 period=validation equity=4998.20525886 realized=-1.79474114 unrealized=0 open=None
- metals_buy_hold 1.0.0 period=forward equity=4999.64100870 realized=-0.35899130 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=forward equity=5000.77606283 realized=-0.14972192 unrealized=0.92578475 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=forward equity=4998.27311994 realized=-1.72688006 unrealized=0 open=None

Schedule UTC: hourly 7,37 * * * *; pump.fun burst 23 */2 * * *; pump.fun backup 53 */2 * * *
Completed runs in the last 24 hours: hourly 1 last 2026-10-26T19:11:11.312644Z; pump.fun 1 last 2026-10-26T18:57:04.716289Z
Gaps over 2 hours in the last 24 hours:
- hourly 2026-10-25T19:11:11.400983Z to 2026-10-26T19:11:11.312644Z (24.00 hours)
- pumpfun 2026-10-25T19:11:11.400983Z to 2026-10-26T18:57:04.716289Z (23.76 hours)
Last price collection 2026-10-26T19:11:11.007258Z
Last pump.fun collection 2026-10-26T18:57:04.418078Z
Last metals collection 2026-10-26T19:11:11.007258Z
Stored errors 16
- 2026-10-26T18:57:04.423577Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-26T18:57:04.423577Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-26T18:57:03.835Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-26T18:56:21.161904Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-26T18:56:21.161904Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-26T18:56:20.548Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-26T04:55:07.028047Z pump_frontend: unexpected HTTP 200; body not ingested
