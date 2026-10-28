sollab status
Research and paper trading only. sollab does not place live orders, sign wallets, create tokens, or use brokerage credentials.

Account rules 4.0.0 — Shared paper cash stays 5000 USD and the per-position cap stays 10 USD. One open position per market now includes metals. Long and short are allowed. A metals short accrues a paper borrow rate; earlier books are not rewritten.
Shared cash free 4961.36870721 locked 29.99996377 equity 4991.44371603 realized -8.63132902 unrealized 0.07504505 fees 2.40156613
Current paper account starts at 5000 USD under account_rules 4.0.0. Open positions, locked notional, and P&L add every cash_era 5000 forward book, including the latest pump.fun book. Train, validation, and cash_era 300 stay out of these totals.
Current open positions:
- crypto_spot experiment sma_crossover 1.1.0 long SOL notional=9.99999913 opened_at=2026-10-27T15:00:00Z
- metals experiment metals_sma_trend 1.0.0 short PAXG notional=9.99996472 opened_at=2026-09-01T00:00:00Z
- pumpfun forward bonding_curve_momentum 1.0.0 long DRWVgsA24hK1WE9Xh9j6wPgpaBZsL34FvPxCkagfpump notional=9.99999992 opened_at=2026-10-28T08:40:31.554029Z

Historical cash era 300
Preserved paper results from the 300 USD account. Not recalculated at 5000 USD.
- cash_era=300 sma_crossover 1.0.0 period=full_window equity=297.07231211 realized=-2.82482382 unrealized=-0.10286407 open=short BTC
- open cash_era=300 crypto_spot short BTC notional=9.99974888

Backtest (cash era 5000)
- cash_era=5000 sma_crossover 1.1.0 period=train book=experiment equity=4997.27086188 realized=-2.72913812 unrealized=0 fees=1.56100641 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=2.91361667 open=None
- cash_era=5000 sma_crossover 1.1.0 period=validation book=experiment equity=4999.90231582 realized=-0.09768418 unrealized=0 fees=0.35811947 win_rate=0.33333333 profit_factor=0.37585978 max_drawdown=0.38895362 open=None
- cash_era=5000 metals_buy_hold 1.0.0 period=train book=experiment equity=5003.02399347 realized=3.02399347 unrealized=0 fees=0.13897772 win_rate=1.00000000 profit_factor=None max_drawdown=3.45242625 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=train book=experiment equity=4999.55402481 realized=-1.85916153 unrealized=1.41318634 fees=1.02530030 win_rate=0.12500000 profit_factor=0.06633499 max_drawdown=1.99125115 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=train book=experiment equity=4996.54856112 realized=-3.61379183 unrealized=0.16235295 fees=3.30215514 win_rate=0.18518519 profit_factor=0.20991058 max_drawdown=4.35039723 open=short PAXG
- cash_era=5000 metals_buy_hold 1.0.0 period=validation book=experiment equity=4999.12639357 realized=-0.87360643 unrealized=0 fees=0.11545055 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.88454715 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=validation book=experiment equity=4999.17524870 realized=-0.54418768 unrealized=-0.28056362 fees=0.29816308 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.16377785 open=long PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=validation book=experiment equity=4998.99085207 realized=-0.92923679 unrealized=-0.07991114 fees=1.37761496 win_rate=0.45454545 profit_factor=0.24434699 max_drawdown=1.24993947 open=short PAXG
Rollup closed=66 win_rate=0.19696970 profit_factor=0.36992741 realized=-7.62281309 by_direction={'short': {'closed_trades': 55, 'wins': 12, 'win_rate': '0.21818182', 'profit_factor': '0.15573773', 'realized_pnl': '-7.86867093'}, 'long': {'closed_trades': 11, 'wins': 1, 'win_rate': '0.09090909', 'profit_factor': '1.08849742', 'realized_pnl': '0.24585784'}} by_market={'crypto_spot': {'closed_trades': 16, 'wins': 1, 'win_rate': '0.06250000', 'profit_factor': '0.02038565', 'realized_pnl': '-2.82682230'}, 'metals': {'closed_trades': 50, 'wins': 12, 'win_rate': '0.24000000', 'profit_factor': '0.47941309', 'realized_pnl': '-4.79599079'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 16, 'wins': 1, 'win_rate': '0.06250000', 'profit_factor': '0.02038565', 'realized_pnl': '-2.82682230'}, 'metals_buy_hold 1.0.0': {'closed_trades': 2, 'wins': 1, 'win_rate': '0.50000000', 'profit_factor': '3.46150551', 'realized_pnl': '2.15038704'}, 'metals_sma_trend 1.0.0': {'closed_trades': 10, 'wins': 1, 'win_rate': '0.10000000', 'profit_factor': '0.05209734', 'realized_pnl': '-2.40334921'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 38, 'wins': 10, 'win_rate': '0.26315789', 'profit_factor': '0.21720722', 'realized_pnl': '-4.54302862'}}

Forward paper
- cash_era=5000 sma_crossover 1.1.0 period=forward book=experiment equity=4999.39521269 realized=-0.75839011 unrealized=0.15360280 fees=0.54013731 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.81742577 open=long SOL
- cash_era=5000 metals_buy_hold 1.0.0 period=forward book=experiment equity=4999.83687354 realized=-0.16312646 unrealized=0 fees=0.11973942 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=1.65685907 open=None
- cash_era=5000 metals_sma_trend 1.0.0 period=forward book=experiment equity=5000.64048263 realized=-0.14972192 unrealized=0.79020455 fees=0.18016781 win_rate=0.00000000 profit_factor=0.00000000 max_drawdown=0.38381990 open=short PAXG
- cash_era=5000 metals_gold_silver_ratio 1.0.0 period=forward book=experiment equity=4998.27311994 realized=-1.72688006 unrealized=0 fees=1.55898939 win_rate=0.15384615 profit_factor=0.15760372 max_drawdown=1.95689271 open=None
Rollup closed=19 win_rate=0.10526316 profit_factor=0.10351197 realized=-2.79811855 by_direction={'short': {'closed_trades': 4, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.66177849'}, 'long': {'closed_trades': 15, 'wins': 2, 'win_rate': '0.13333333', 'profit_factor': '0.13136486', 'realized_pnl': '-2.13634006'}} by_market={'crypto_spot': {'closed_trades': 4, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.75839011'}, 'metals': {'closed_trades': 15, 'wins': 2, 'win_rate': '0.13333333', 'profit_factor': '0.13673616', 'realized_pnl': '-2.03972844'}} by_strategy={'sma_crossover 1.1.0': {'closed_trades': 4, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.75839011'}, 'metals_buy_hold 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.16312646'}, 'metals_sma_trend 1.0.0': {'closed_trades': 1, 'wins': 0, 'win_rate': '0.00000000', 'profit_factor': '0.00000000', 'realized_pnl': '-0.14972192'}, 'metals_gold_silver_ratio 1.0.0': {'closed_trades': 13, 'wins': 2, 'win_rate': '0.15384615', 'profit_factor': '0.15760372', 'realized_pnl': '-1.72688006'}}

pump.fun
- run=2026-10-28T08:41:15.764883Z equity=4993.29802723 realized=-5.83321047 unrealized=-0.86876230 fees=0.00253220 open=DRWVgsA24hK1WE9Xh9j6wPgpaBZsL34FvPxCkagfpump

Metals
One metals slot on the shared 5000 USD account. Runs below are also inside backtest and forward.
- metals_buy_hold 1.0.0 period=train equity=5003.02399347 realized=3.02399347 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=train equity=4999.55402481 realized=-1.85916153 unrealized=1.41318634 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=train equity=4996.54856112 realized=-3.61379183 unrealized=0.16235295 open=short PAXG
- metals_buy_hold 1.0.0 period=validation equity=4999.12639357 realized=-0.87360643 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=validation equity=4999.17524870 realized=-0.54418768 unrealized=-0.28056362 open=long PAXG
- metals_gold_silver_ratio 1.0.0 period=validation equity=4998.99085207 realized=-0.92923679 unrealized=-0.07991114 open=short PAXG
- metals_buy_hold 1.0.0 period=forward equity=4999.83687354 realized=-0.16312646 unrealized=0 open=None
- metals_sma_trend 1.0.0 period=forward equity=5000.64048263 realized=-0.14972192 unrealized=0.79020455 open=short PAXG
- metals_gold_silver_ratio 1.0.0 period=forward equity=4998.27311994 realized=-1.72688006 unrealized=0 open=None

Schedule UTC: hourly 7,37 * * * *; pump.fun burst 23 */2 * * *; pump.fun backup 53 */2 * * *
Completed runs in the last 24 hours: hourly 5 last 2026-10-28T11:34:38.016393Z; pump.fun 5 last 2026-10-28T08:41:15.948814Z
Gaps over 2 hours in the last 24 hours:
- hourly 2026-10-27T11:34:38.147416Z to 2026-10-27T14:52:50.606655Z (3.30 hours)
- hourly 2026-10-27T14:52:50.606655Z to 2026-10-27T20:01:45.830987Z (5.15 hours)
- hourly 2026-10-27T20:01:45.830987Z to 2026-10-27T23:43:35.361454Z (3.70 hours)
- hourly 2026-10-27T23:43:35.361454Z to 2026-10-28T05:27:12.990272Z (5.73 hours)
- hourly 2026-10-28T05:27:12.990272Z to 2026-10-28T11:34:38.016393Z (6.12 hours)
- pumpfun 2026-10-27T12:22:27.172986Z to 2026-10-27T18:07:18.471553Z (5.75 hours)
- pumpfun 2026-10-27T18:07:18.471553Z to 2026-10-27T22:22:05.900286Z (4.25 hours)
- pumpfun 2026-10-27T22:22:05.900286Z to 2026-10-28T01:28:50.480460Z (3.11 hours)
- pumpfun 2026-10-28T01:28:50.480460Z to 2026-10-28T08:41:15.948814Z (7.21 hours)
- pumpfun 2026-10-28T08:41:15.948814Z to 2026-10-28T11:34:38.147416Z (2.89 hours)
Last price collection 2026-10-28T11:34:37.503265Z
Last pump.fun collection 2026-10-28T08:41:15.598812Z
Last metals collection 2026-10-28T11:34:37.503265Z
Stored errors 44
- 2026-10-28T08:41:15.606550Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-28T08:41:15.606550Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-28T08:41:14.878Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-28T08:40:31.563284Z pump_frontend: unexpected HTTP 200; body not ingested
- 2026-10-28T08:40:31.563284Z pump_developer_api: HTTP 401 from https://api.pump.fun/v1/users/search-v2?q=test: {"statusCode":401,"timestamp":"2026-10-28T08:40:30.864Z","path":"/users/search-v2?q=test","error":"API_KEY_REQUIRED","message":"Send Authorization: Bearer <key> or x-api-key: <key>"}
- 2026-10-28T01:28:50.204660Z pump_frontend: unexpected HTTP 200; body not ingested
