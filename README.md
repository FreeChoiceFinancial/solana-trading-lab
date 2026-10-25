# solana-trading-lab

Research and paper-trading lab for public BTC and SOL prices. `sollab` reads keyless market-data APIs, stores what it received, and simulates one small momentum rule in a local ledger.

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
python -m sollab report
```

`collect` writes `data/sollab.db` (gitignored on this branch). It pauses briefly between calls. `run-strategy` replays stored hourly candles as `sma_crossover` 1.1.0 and replaces only that version's current-era rows. `cash_era` 300 rows, including the preserved 1.0.0 book, stay. `pumpfun-collect` reads public pump.fun pool and account data into the same database. `pumpfun-run` replays `bonding_curve_momentum` on those rows and does not delete the SMA book or cash_era 300 pump rows. `report` prints a markdown summary and writes `data/exports/status.json` plus CSV/JSON tables. Curve math, fees, and the polling limit are in `docs/pumpfun.md`.

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
| `kraken` | Closed 1h OHLC, only if Coinbase candles fail | `https://api.kraken.com/0/public/OHLC` |

The current hour bucket is not stored. Spot prints are evidence; the strategy uses one candle source per symbol, Coinbase first. HTTP 408, 429, and 5xx are retried with a wait capped at 10 seconds. Other client errors are not retried. Failures are logged and inserted into `errors`. Missing values are not invented.

URLs outside those read-only paths are refused before a request is sent.

## Strategy

`sma_crossover` version `1.1.0`. On closed hourly closes, a bullish cross is a 5-bar SMA moving from at or below the 20-bar SMA to above it. A bearish cross is the opposite. The signal is the close of candle t. The fill is the next candle's open, after adverse slippage. Version 1.0.0 filled the same bar's close. Those rows stay in the database with `cash_era` 300.

`run-strategy` splits the stored timestamps into train (first 60%), validation (next 20%), and forward (the rest), with one unscored bar between each scored window. The 5/20 windows are fixed in code. They are not fit on validation or forward. A series too short for that split is stored as one `full_window` run. Each period is its own experiment book.

Portfolio limits for new paper books (`account_rules` 3.0.0):

- 5000 USD starting cash, shared across markets
- at most 10 USD notional per position, at least 1 USD
- one open position per market: `crypto_spot`, `pumpfun`, and `stocks` (reserved, no stock data and no stock orders)
- BTC and SOL share the `crypto_spot` slot
- long and short, both cash-collateralized (a short does not increase cash)
- 0.6% taker-style fee on open and on close
- 5 bps of adverse slippage
- realized P&L only on close; unrealized P&L marked separately
- holding period is exit fill time minus entry fill time

`config_journal` keeps account_rules 1.0.0 and 2.0.0, both at 300 USD. A 1.1.0 rerun does not delete `cash_era` 300 rows. The preserved 1.0.0 BTC short stays in that book.

## Durable state

GitHub Actions artifacts expire, and the Actions cache can be evicted. The scheduled workflow commits `sollab.db`, `status.json`, and `status.md` to the `data` branch. That branch is not a pull request. Binary SQLite does not diff cleanly, so the branch history grows by about the size of the database each hour. The status files are the readable snapshot. Pushes to `data` do not run the test workflow.

Private repositories get 2,000 Actions minutes per month. `.github/workflows/paper-hourly.yml` estimates:

| Job | Cadence | Runs / month | Expected minutes | Monthly minutes |
| --- | --- | --- | --- | --- |
| BTC/SOL collect, replay, report | hourly | 720 | 1.0–1.5 | 720–1,080 |
| pump.fun burst, 2 polls, 35s apart | every 6 hours | 120 | 2.0–2.5 | 240–300 |

Scheduled total is about 960–1,380 minutes, leaving a few hundred minutes for tests and manual runs. Each job's timeout is 8 minutes so a hung run cannot consume the default six-hour job limit. The schedule starts once this workflow file is on the repository's default branch. `workflow_dispatch` can run it from `dev` before that.

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

Version 1.0.0 same-bar close fills are kept and labeled, and they are optimistic versus the 1.1.0 next-open fill. Windows count stored candles, so gaps are not clock hours. The fee is a research assumption, not a quote from an account. The short is collateral in this ledger, not a borrow and not a perpetual. One position per market means the other symbol in that market waits. Coinbase, CoinGecko, and Kraken can rate-limit or change payloads; the collector records the failure instead of filling it in.
