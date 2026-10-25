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

`collect` writes `data/sollab.db` (gitignored). It pauses briefly between calls. `run-strategy` replays the stored hourly candles and replaces previous SMA simulation rows; prices stay. `pumpfun-collect` reads public pump.fun pool and account data into the same database. `pumpfun-run` replays `bonding_curve_momentum` on those rows and does not delete the SMA book. `report` prints provenance and both paper ledgers, and writes CSV/JSON tables under `data/exports/` (also gitignored). Curve math, fees, and the polling limit are in `docs/pumpfun.md`.

A small export of stored prices:

```bash
python -m sollab report \
  --sample-json data/samples/btc_sol_public_prices.json \
  --sample-csv data/samples/btc_sol_public_prices.csv \
  --sample-label REAL_PUBLIC_FETCH \
  --simulation-summary data/samples/simulated_replay_summary.json
```

Use `REAL_PUBLIC_FETCH` only for a database just filled by `collect`. Each price row still carries `source_name`, `endpoint`, `fetched_at` (when this process received the body), and `source_timestamp` (the venue's own time). The simulation summary is labeled `SIMULATED_REPLAY_NOT_LIVE_TRADES`.

## Data

| Source | What | Endpoint family |
| --- | --- | --- |
| `coinbase_exchange` | Spot ticker and closed 1h candles | `https://api.exchange.coinbase.com/products/{BTC,SOL}-USD/ticker` and `.../candles?granularity=3600` |
| `coingecko` | Spot simple price | `https://api.coingecko.com/api/v3/simple/price` |
| `kraken` | Closed 1h OHLC, only if Coinbase candles fail | `https://api.kraken.com/0/public/OHLC` |

The current hour bucket is not stored. Spot prints are evidence; the strategy uses one candle source per symbol, Coinbase first. HTTP 408, 429, and 5xx are retried with a wait capped at 10 seconds. Other client errors are not retried. Failures are logged and inserted into `errors`. Missing values are not invented.

URLs outside those read-only paths are refused before a request is sent.

## Strategy

`sma_crossover` version `1.0.0`. On closed hourly closes, a bullish cross is a 5-bar SMA moving from at or below the 20-bar SMA to above it. A bearish cross is the opposite. The full entry, exit, and rejection list is printed by `report` and stored in `strategy_versions`.

Portfolio limits for the paper account:

- 300 USD starting cash
- at most 10 USD notional, at least 1 USD
- one open position
- long and short, both cash-collateralized (a short does not increase cash)
- 0.6% taker-style fee on open and on close
- 5 bps of adverse slippage
- fill at the same candle's close after slippage
- realized P&L only on close; unrealized P&L marked separately
- holding period is exit candle time minus entry candle time

`run-strategy` is a replay of candles already stored. It is not a walk-forward test with a held-out period. See `ROADMAP.md`.

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
.github/       tests on push, collector on workflow_dispatch only
```

## Limitations

Same-bar close fills are optimistic versus trading the next bar. Windows count stored candles, so gaps are not clock hours. The fee is a research assumption, not a quote from an account. The short is collateral in this ledger, not a borrow and not a perpetual. One position means the other symbol waits. Coinbase, CoinGecko, and Kraken can rate-limit or change payloads; the collector records the failure instead of filling it in.
