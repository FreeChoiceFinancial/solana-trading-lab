# Roadmap

This file is a research list. None of it is permission to trade live, sign a wallet, create a token, or store brokerage credentials. Later work stays paper-only unless a separate, explicit decision says otherwise.

## pump.fun research

`docs/pumpfun.md` records the bonding-curve quote, the fee disagreement between the old Global JSON and the 17 October 2026 fees page, and the keyless sources that actually returned data. `python -m sollab pumpfun-collect` stores those reads. `python -m sollab pumpfun-run` replays `bonding_curve_momentum` 1.0.0 on the stored rows. Still no wallet, no token creation, and no keyed pump.fun API. `.github/workflows/paper-hourly.yml` runs a short pump.fun burst every six hours and commits state to the `data` branch. A five-minute cron still does not fit the free private minute quota or this market's speed. Do not install `pump-fun-skills`.

## Stocks and penny stocks

Add a separate data adapter only if a delayed or end-of-day source can be used without an API key or a paid plan. Penny stocks need a wider cost model than the 5 bps crypto assumption: spreads and lot size dominate a 10 USD position. Keep them in their own tables so crypto candles and equity candles are not mixed in one SMA series.

## Shorts and perpetuals

The current short locks cash as collateral and has no funding, borrow fee, or liquidation. A later paper model can add those as explicit ledger events. Perpetual prices, if used, must come from a public mark or candle endpoint and must stay inside the same notional cap. No exchange account.

## Backtesting splits

`sma_crossover` 1.1.0 fills at the next candle open. `run-strategy` stores train, validation, and forward as separate experiment books with a one-bar gap. The 5/20 parameters are fixed before the forward window and are not fit on it. Version 1.0.0 same-bar results stay labeled `cash_era` 300.

## Scheduled collector

`.github/workflows/paper-hourly.yml` collects BTC and SOL hourly, replays the paper strategy, writes the report, and commits `sollab.db` plus the status files to the `data` branch. The job is labeled simulated and does not use a secret. `.github/workflows/collect.yml` remains manual.

## Dashboard

A local read-only page over `data/sollab.db`: latest provenance rows, open paper position, realized versus unrealized P&L, and the rejection counts. No order button. The page should show the fetch time and the venue time on every price.
