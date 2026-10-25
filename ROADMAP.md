# Roadmap

This file is a research list. None of it is permission to trade live, sign a wallet, create a token, or store brokerage credentials. Later work stays paper-only unless a separate, explicit decision says otherwise.

## pump.fun research

Read public documentation only. Questions worth answering later: which fields describe bonding-curve state, how quotes are defined, and whether any keyless public market endpoint exists for prices. Do not install `pump-fun-skills`, do not send transactions, and do not create coins. `docs/reuse-evaluation.md` records why those repositories are not dependencies of this milestone.

## Stocks and penny stocks

Add a separate data adapter only if a delayed or end-of-day source can be used without an API key or a paid plan. Penny stocks need a wider cost model than the 5 bps crypto assumption: spreads and lot size dominate a 10 USD position. Keep them in their own tables so crypto candles and equity candles are not mixed in one SMA series.

## Shorts and perpetuals

The current short locks cash as collateral and has no funding, borrow fee, or liquidation. A later paper model can add those as explicit ledger events. Perpetual prices, if used, must come from a public mark or candle endpoint and must stay inside the same notional cap. No exchange account.

## Backtesting splits

The milestone replays the whole stored window. A later evaluator should split candles into train, validation, and forward segments by time, with a gap between them, and should score only the forward segment. Parameters chosen on the train window must be written down before the forward run. Same-bar close fills should be replaced by a next-bar fill before any performance claim.

## Scheduled collector

`.github/workflows/collect.yml` is `workflow_dispatch` only. A later schedule can run the same read-only `collect` command and upload the SQLite artifact. It should not run `run-strategy` unattended until the replay is idempotent in CI artifacts and clearly labeled as simulated. No secrets are required for the public endpoints.

## Dashboard

A local read-only page over `data/sollab.db`: latest provenance rows, open paper position, realized versus unrealized P&L, and the rejection counts. No order button. The page should show the fetch time and the venue time on every price.
