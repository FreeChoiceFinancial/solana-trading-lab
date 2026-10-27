sollab status
Research and paper trading only. sollab does not place live orders, sign wallets, create tokens, or use brokerage credentials.

Account rules 4.0.0 — Shared paper cash stays 5000 USD and the per-position cap stays 10 USD. One open position per market now includes metals. Long and short are allowed. A metals short accrues a paper borrow rate; earlier books are not rewritten.
Shared cash free 4981.27709776 locked 9.99996472 equity 4992.18934833 realized -8.72293752 unrealized 0.91228585 fees 2.33989811
Current paper account starts at 5000 USD under account_rules 4.0.0. Open positions, locked notional, and P&L add every cash_era 5000 forward book, including the latest pump.fun book. Train, validation, and cash_era 300 stay out of these totals.
Current open positions:
- metals experiment metals_sma_trend 1.0.0 short PAXG notional=9.99996472 opened_at=2026-09-01T00:00:00Z

Historical cash era 300
Preserved paper results from the 300 USD account. Not recalculated at 5000 USD.
- cash_era=300 sma_crossover 1.0.0 period=full_window equity=297.07231211 realized=-2.82482382 unrealized=-0.10286407 open=short BTC
- open cash_era=300 crypto_spot short BTC notional=9.99974888

Backtest (cash era 5000)
- cash_era=5000 sma_crossover 1.1.0 period=train book=experiment equity=4997.45988848 realized=-2.54011152 unrealized=0 fees=1.44059472 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=2.72459007 open=None
- cash_era=5000 sma_crossover 1.1.0 period=validation book=experiment equity=4999.96806689 realized=-0.27635369 unrealized=0.24442058 fees=0.41918510 win_rate=0.33333333 profit_factor=0.17550539 max_drawdown=0.38895362 open=short SOL
- cash_era=5000 metals_buy_hold 1.0.0 period=train book=experiment equity=5003.02399347 realized=3.02399347 unrealized=0 fees=0.13897772 win_rate=1.00000000 profit_factor=None max_drawdown=3.45242625 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=train book=experiment equity=4999.55402481 realized=-1.85916153 unrealized=1.41318634 fees=1.02530030 win_rate=0.12500000 profit_factor=0.06633499 max_drawdown=1.99125115 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=train book=experiment equity=4996.54856112 realized=-3.61379183 unrealized=0.16235295 fees=3.30215514 win_rate=0.18518519 profit_factor=0.20991058 max_drawdown=4.35039723 open=short PAXG
- cash_era=5000 metals_buy_hold 1.0.0 period=validation book=experiment equity=4999.12639357 realized=-0.87360643 unrealized=0 fees=0.11545055 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.88454715 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=validation book=experiment equity=4999.17524870 realized=-0.54418768 unrealized=-0.28056362 fees=0.29816308 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.16377785 open=long PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=validation book=experiment equity=4998.99085207 realized=-0.92923679 unrealized=-0.07991114 fees=1.37761496 win_rate=0.45454545 profit_factor=0.24434699 max_drawdown=1.24993947 open=short PAXG
Rollup closed=65 win_rate=0.20000000 profit_factor=0.37024437 realized=-7.61245600 by_direction={'short': {'closed_trades': 54, 'wins': 12, 'win_rate': '0.22222222', 'profit_factor': '0.15591099', 'realized_pnl': '-7.85831384'}, 'long': {'closed_trades': 11, 'wins': 1, 'win_rate': '0.09090909', 'profit_factor': '1.08849742', 'realized_pnl': '0.24585784'}} by_market={'crypto_spot': {'closed_trades': 15, 'wins': 1, 'win_rate': '0.06666667', 'profit_factor': '0.02045908', 'realized_pnl': '-2.81646521'}, 'metals': {'closed_trades': 50, 'wins': 12, 'win_rate': '0.24000000', 'profit_factor': '0.47941309', 'realized_pnl': '-4.79599079'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 15, 'wins': 1, 'win_rate': '0.06666667', 'profit_factor': '0.02045908', 'realized_pnl': '-2.81646521'}, 'metals_buy_hold 1.0.0': {'closed_trades': 2, 'wins': 1, 'win_rate': '0.50000000', 'profit_factor': '3.46150551', 'realized_pnl': '2.15038704'}, 'metals_sma_trend 1.0.0': {'closed_trades': 10, 'wins': 1, 'win_rate': '0.10000000', 'profit_factor': '0.05209734', 'realized_pnl': '-2.40334921'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 38, 'wins': 10, 'win_rate': '0.26315789', 'profit_factor': '0.21720722', 'realized_pnl': '-4.54302862'}}

Forward paper
- cash_era=5000 sma_crossover 1.1.0 period=forward book=experiment equity=4999.28201332 realized=-0.71798668 unrealized=0 fees=0.47978139 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.71798668 open=None
- cash_era=5000 metals_buy_hold 1.0.0 period=forward book=experiment equity=4999.70486161 realized=-0.29513839 unrealized=0 fees=0.11894257 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.68980750 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=forward book=experiment equity=5000.76256393 realized=-0.14972192 unrealized=0.91228585 fees=0.18016781 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.38381990 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=forward book=experiment equity=4998.27311994 realized=-1.72688006 unrealized=0 fees=1.55898939 win_rate=0.15384615 profit_factor=0.15760372 max_drawdown=1.95689271 open=None
Rollup closed=19 win_rate=0.10526316 profit_factor=0.10056048 realized=-2.88972705 by_direction={'long': {'closed_trades': 16, 'wins': 2, 'win_rate': '0.12500000', 'profit_factor': '0.11873614', 'realized_pnl': '-2.39792289'}, 'short': {'closed_trades': 3, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.49180416'}} by_market={'crypto_spot': {'closed_trades': 4, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.71798668'}, 'metals': {'closed_trades': 15, 'wins': 2, 'win_rate': '0.13333333', 'profit_factor': '0.12950086', 'realized_pnl': '-2.17174037'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 4, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.71798668'}, 'metals_buy_hold 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.29513839'}, 'metals_sma_trend 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.14972192'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 13, 'wins': 2, 'win_rate': '0.15384615', 'profit_factor': '0.15760372', 'realized_pnl': '-1.72688006'}}

pump.fun
- run=2026-10-27T22:22:05.593796Z equity=4994.16678953 realized=-5.83321047 unrealized=0 fees=0.00201695 open=None

Metals
One metals slot on the shared 5000 USD account. Runs below are also inside backtest and forward.
- metals_buy_hold 1.0.0 period=train equity=5003.02399347 realized=3.02399347 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=train equity=4999.55402481 realized=-1.85916153 unrealized=1.41318634 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=train equity=4996.54856112 realized=-3.61379183 unrealized=0.16235295 open=short PAXG
- metals_buy_hold 1.0.0 period=validation equity=4999.12639357 realized=-0.87360643 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=validation equity=4999.17524870 realized=-0.54418768 unrealized=-0.28056362 open=long PAXG
- metals_gold_silver_ratio 1.0.0 period=validation equity=4998.99085207 realized=-0.92923679 unrealized=-0.07991114 open=short PAXG
- metals_buy_hold 1.0.0 period=forward equity=4999.70486161 realized=-0.29513839 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=forward equity=5000.76256393 realized=-0.14972192 unrealized=0.91228585 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=forward equity=4998.27311994 realized=-1.72688006 unrealized=0 open=None

Schedule UTC: hourly 7,37 * * * *; pump.fun burst 23 */2 * * *; pump.fun backup 53 */2 * * *
Completed runs in the last 24 hours: hourly 5 last 2026-10-27T23:43:35.361454Z; pump.fun 5 last 2026-10-27T22:22:05.900286Z
Gaps over 2 hours in the last 24 hours:
- hourly 2026-10-26T23:43:35.489200Z to 2026-10-27T02:22:56.199252Z (2.66 hours)
- hourly 2026-10-27T02:22:56.199252Z to 2026-10-27T08:20:14.367933Z (5.96 hours)
- hourly 2026-10-27T08:20:14.367933Z to 2026-10-27T14:52:50.606655Z (6.54 hours)
- hourly 2026-10-27T14:52:50.606655Z to 2026-10-27T20:01:45.830987Z (5.15 hours)
- hourly 2026-10-27T20:01:45.830987Z to 2026-10-27T23:43:35.361454Z (3.70 hours)
- pumpfun 2026-10-26T23:56:57.924266Z to 2026-10-27T05:14:23.916839Z (5.29 hours)
- pumpfun 2026-10-27T05:14:23.916839Z to 2026-10-27T12:22:27.172986Z (7.13 hours)
- pumpfun 2026-10-27T12:22:27.172986Z to 2026-10-27T18:07:18.471553Z (5.75 hours)
- pumpfun 2026-10-27T18:07:18.471553Z to 2026-10-27T22:22:05.900286Z (4.25 hours)
Last price collection 2026-10-27T23:43:34.851090Z
Last pump.fun collection 2026-10-27T22:22:05.415898Z
Last metals collection 2026-10-27T23:43:34.851090Z
Stored errors 36
- 2026-10-27T22:22:05.421878Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-27T22:22:05.421878Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-27T22:22:04.789Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-27T22:21:21.786597Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-27T22:21:21.786597Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-27T22:21:21.130Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-27T18:07:18.155657Z pump_frontend: unexpected HTTP 200; body not ingested
