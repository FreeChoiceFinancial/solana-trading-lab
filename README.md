# Paper state

This branch holds the simulated research database. It is not application code and it is not a pull request.

- `sollab.db` is the SQLite book. `cash_era` 300 rows are the earlier 300 USD account, including the preserved sma_crossover 1.0.0 BTC short. Current paper books use account_rules 3.0.0: 5000 USD shared cash, one open position per market, 10 USD notional cap.
- `status.json` and `status.md` are the latest `python -m sollab report` output.
- `.github/workflows/paper-hourly.yml` on `dev` updates these files. Pushes here do not run the test workflow.

No live orders, keys, or brokerage credentials are stored.
