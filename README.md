# solana-trading-lab

Research and paper-trading lab for public BTC, SOL, pump.fun, and precious-metals prices. `sollab` reads keyless market-data APIs, stores what it received, and simulates small rules in a local ledger.

It does not place live orders, sign wallets, hold private keys, create tokens, or use brokerage credentials. Nothing in this repository is investment advice.

## Setup

Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Dependencies are pinned in `pyproject.toml`: `httpx==0.28.1` and, for tests, `pytest==8.3.5`. No API key is read.

## Commands

```bash
python -m sollab collect
python -m sollab run-strategy
python -m sollab pumpfun-collect
python -m sollab pumpfun-run
python -m sollab metals-collect
python -m sollab metals-run
python -m sollab report
```

`collect` writes `data/sollab.db` (gitignored). It pauses briefly between calls. `run-strategy` replays stored hourly candles as `sma_crossover` 1.1.0 and replaces only that version's current-era rows. `cash_era` 300 rows, including the preserved 1.0.0 book, stay. `pumpfun-collect` reads public pump.fun pool and account data into the same database. `pumpfun-run` replays `bonding_curve_momentum` on those rows and does not delete the SMA book or cash_era 300 pump rows. `metals-collect` stores keyless PAXG, XAUT, ETF, and futures bars in that same database. `metals-run` replays the metals baselines and does not delete the SMA or pump books. `report` prints a markdown summary and writes `data/exports/status.json` plus CSV/JSON tables. Curve math is in `docs/pumpfun.md`. Metals sources, costs, and the split results are in `docs/precious_metals.md`.

A small export of stored prices:

```bash
python -m sollab report \
  --sample-json data/samples/btc_sol_public_prices.json \
  --sample-csv data/samples/btc_sol_public_prices.csv \
  --sample-label REAL_PUBLIC_FETCH \
  --simulation-summary data/samples/simulated_replay_summary.json
```

Use `REAL_PUBLIC_FETCH` only for a database just filled by `collect`. Each price row still carries `source_name`, `endpoint`, `fetched_at` (when this process received the body), and `source_timestamp` (the venue's own time). The checked-in simulation summary is the cash_era 300 replay and is labeled `SIMULATED_REPLAY_NOT_LIVE_TRADES`. Do not overwrite it with a 5000 USD run.

## Data

| Source | What | Endpoint family |
| --- | --- | --- |
| `coinbase_exchange` | Spot ticker and closed 1h candles | `https://api.exchange.coinbase.com/products/{BTC,SOL}-USD/ticker` and `.../candles?granularity=3600` |
| `coingecko` | Spot simple price | `https://api.coingecko.com/api/v3/simple/price` |
| `kraken` | Closed 1h OHLC, only if Coinbase candles fail. Daily PAXG and XAUT for metals | `https://api.kraken.com/0/public/OHLC` |
| `yahoo_chart` | Daily GLD, SLV, PPLT, PALL, GC, SI, PL, PA | `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}` |

The current hour bucket is not stored. Spot prints are evidence; the BTC/SOL strategy uses one candle source per symbol, Coinbase first. The metals book trades Coinbase PAXG daily bars and reads Yahoo silver only as a signal. HTTP 408, 429, and 5xx are retried with a wait capped at 10 seconds. Other client errors are not retried. Failures are logged and inserted into `errors`. Missing values are not invented.

URLs outside those read-only paths are refused before a request is sent.

## Strategy

`sma_crossover` version `1.1.0`. On closed hourly closes, a bullish cross is a 5-bar SMA moving from at or below the 20-bar SMA to above it. A bearish cross is the opposite. The signal is the close of candle t. The fill is the next candle's open, after adverse slippage. Version 1.0.0 filled the same bar's close. Those rows stay in the database with `cash_era` 300.

`run-strategy` splits the stored timestamps into train (first 60%), validation (next 20%), and forward (the rest), with one unscored bar between each scored window. The 5/20 windows are fixed in code. They are not fit on validation or forward. A series too short for that split is stored as one `full_window` run. Each period is its own experiment book.

Portfolio limits for new paper books (`account_rules` 4.0.0):

- 5000 USD starting cash, shared across markets
- at most 10 USD notional per position, at least 1 USD
- one open position per market: `crypto_spot`, `pumpfun`, `stocks` (reserved, no stock data and no stock orders), and `metals`
- BTC and SOL share the `crypto_spot` slot
- gold, silver, platinum, and palladium share the one `metals` slot. The baselines trade PAXG only
- long and short, both cash-collateralized (a short does not increase cash)
- 0.6% taker-style fee on open and on close
- 5 bps of adverse slippage
- a metals short also accrues 0.50% annualized borrow, actual/365, on the entry notional. Crypto and pump.fun books keep borrow at 0
- realized P&L only on close; unrealized P&L marked separately, with accrued borrow subtracted while a metals short is open
- holding period is exit fill time minus entry fill time

`config_journal` keeps account_rules 1.0.0 and 2.0.0 at 300 USD, and 3.0.0 at 5000 USD without the metals market. A rerun does not delete `cash_era` 300 rows. The preserved 1.0.0 BTC short stays in that book.

`metals-run` stores `metals_buy_hold`, `metals_sma_trend`, and `metals_gold_silver_ratio`, each 1.0.0, on train, validation, and forward. Fills are the next daily open. The 5/20 windows are fixed. Silver enters the ratio rule only when its bar timestamp is at or before the PAXG bar.

## Durable state

GitHub Actions artifacts expire, and the Actions cache can be evicted. The scheduled workflow commits `sollab.db`, `status.json`, and `status.md` to the `data` branch. That branch is not a pull request. Binary SQLite does not diff cleanly, so the branch history grows by about the size of the database each hour. The status files are the readable snapshot. Pushes to `data` do not run the test workflow.

The repository is public, so standard GitHub-hosted minutes are not billed. Usage still matters because every successful job commits `sollab.db` to `data` and calls public APIs. `.github/workflows/paper-hourly.yml` estimates:

| Job | Cadence | Runs / month | Expected minutes | Monthly minutes |
| --- | --- | --- | --- | --- |
| BTC/SOL collect, metals collect, replays, report | hourly | 720 | 1.0–1.5 | 720–1,080 |
| pump.fun burst, 2 polls, 35s apart | every 2 hours (`15 */2 * * *`) | 360 | 2.0–2.5 | 720–900 |

Scheduled total is about 1,440–1,980 minutes of runner time. The two-hour burst, rather than a five-minute cron, is the cap that keeps the `data` branch and the public API calls from growing with every short pump.fun window. Each job's timeout is 8 minutes. GitHub registers both the schedule and `workflow_dispatch` only after `paper-hourly.yml` is on the default branch (`main`). A dispatch from another branch is not available before that.

## Tests

```bash
python -m pytest
```

Offline:

```bash
SOLLAB_SKIP_NETWORK=1 python -m pytest
```

The `network` test calls the public APIs. Skip it with `-m "not network"` as well.

## Layout

```text
src/sollab/    collector, strategy, paper ledger, SQLite, CLI
tests/         rules, accounting, storage, parsers, live API
data/samples/  small exported evidence
docs/          notes on related projects (not installed)
.github/       tests on code pushes; paper-hourly writes the data branch
```

## Limitations

Version 1.0.0 same-bar close fills are kept and labeled, and they are optimistic versus the 1.1.0 next-open fill. Windows count stored candles, so gaps are not clock hours. The fee is a research assumption, not a quote from an account. Crypto and pump.fun shorts are collateral in this ledger, with borrow left at zero. A metals short adds the 0.50% research borrow and is still not a perpetual and not a located stock loan. One position per market means the other symbol in that market waits. Coinbase daily PAXG history returned by the public candles API starts on 2025-05-08. Coinbase, CoinGecko, Kraken, and Yahoo can rate-limit or change payloads; the collector records the failure instead of filling it in.
