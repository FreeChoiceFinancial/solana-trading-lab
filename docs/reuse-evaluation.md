# Reuse evaluation

Checked on 2026-10-25 from public GitHub repository metadata and README pages. These repositories were not cloned, installed, imported, or executed for this milestone. `sollab` does not vendor their code.

## freqtrade/freqtrade

- URL: https://github.com/freqtrade/freqtrade
- License reported by GitHub: GPL-3.0. A `LICENSE` file is present.
- What it is: a Python crypto trading bot with exchange connectors, SQLite persistence, a dry-run mode, candle download, backtesting, and strategy classes. The README states it is educational and that dry-run should come before any money.

Useful ideas, not code:

- Separate "download data" from "simulate" from "trade".
- Store candles and trades in SQLite.
- Model fees inside the simulation.
- Treat lookahead as a defect. Freqtrade even ships lookahead checks.

Do not copy or import freqtrade here. GPL-3.0 would apply to a distributed derivative that includes its code. The bot can also send live exchange orders once keys are configured, which this lab does not do. Its Python, TA-Lib, and exchange surface is far larger than this milestone.

## TauricResearch/TradingAgents

- URL: https://github.com/TauricResearch/TradingAgents
- License reported by GitHub: Apache-2.0. A `LICENSE` file is present.
- What it is: a multi-agent research framework. Analyst and risk roles debate a ticker, and the README describes a simulated exchange plus a date-grid backtest. It says it is not investment advice. Recent release notes emphasize point-in-time data and scoring a decision from a later close.

Useful later, under Apache-2.0's attribution and notice requirements if any of its code is actually copied:

- Write the decision, the data timestamp, and the holding window before scoring it.
- Keep a forward segment that the rule was not tuned on.
- Say clearly when a result is simulated.

Not used now. Running it needs paid or account-backed model APIs, which this milestone does not use. Outputs are not deterministic. It is not a BTC/SOL candle collector.

## pump-fun/pump-fun-skills

- URL: https://github.com/pump-fun/pump-fun-skills
- License: GitHub reports no license, and the repository root listing on 2026-10-25 had no `LICENSE` file. Without a license, the code cannot be copied.
- What it is: agent skills whose README describes creating coins, swapping, collecting creator fees, and tokenized-agent payments, including wallet and RPC setup.

Nothing here is reusable for this lab. Those skills exist to sign and submit on-chain actions. That includes token creation and live swaps, which are out of scope. Do not install the npm packages and do not run the scripts.

## pump-fun/pump-public-docs

- URL: https://github.com/pump-fun/pump-public-docs
- License: GitHub reports no license, and the root listing on 2026-10-25 had no `LICENSE` file. Do not vendor the IDL or the docs.
- What it is: public notes on pump.fun program instructions: coin creation, bonding-curve trades, PumpSwap, fee sweeps, and quote accounts.

It is not a BTC or SOL candle API. `docs/pumpfun.md` records the bonding-curve and fee notes taken from it. The IDL is not vendored. Reading those notes is not permission to build a transaction. The pump.fun collector reads public account data with `getAccountInfo` and `getMultipleAccounts` only. It does not sign.

## What this repository actually uses

Public GET requests to Coinbase Exchange, CoinGecko, and Kraken for BTC and SOL. For pump.fun, public GeckoTerminal and DexScreener GETs plus Solana JSON-RPC reads listed in `docs/pumpfun.md`. The paper ledgers, both strategy rules, and the SQLite schema are local code. pump-fun-skills is not installed. Related-project ideas above are notes, not dependencies.
