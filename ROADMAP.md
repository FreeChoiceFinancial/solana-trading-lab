# Roadmap

This file is a research list. None of it is permission to trade live, sign a wallet, create a token, or store brokerage credentials. Later work stays paper-only unless a separate, explicit decision says otherwise.

## pump.fun research

`docs/pumpfun.md` records the bonding-curve quote, the fee disagreement between the old Global JSON and the 17 October 2026 fees page, and the keyless sources that actually returned data. `python -m sollab pumpfun-collect` stores those reads. `python -m sollab pumpfun-run` replays `bonding_curve_momentum` 1.0.0 on the stored rows. Still no wallet, no token creation, and no keyed pump.fun API. `.github/workflows/paper-hourly.yml` runs a short pump.fun burst every two hours (`15 */2 * * *`) and commits state to the `data` branch. The repository is public, so standard runner minutes are not billed. Each run still grows the `data` branch by about the size of `sollab.db` and polls public APIs, which is why the burst is two hours and not five minutes. Do not install `pump-fun-skills`.

## Precious metals

`docs/precious_metals.md` records how a long or a short would be held in spot quotes, ETFs, futures, and tokenized gold, and which keyless sources answered on 2026-10-25. `python -m sollab metals-collect` stores those prices. `python -m sollab metals-run` replays three 1.0.0 books on train, validation, and forward: buy-and-hold PAXG, a 5/20 daily SMA, and a one-leg gold/silver ratio. The ratio lost to buy-and-hold on every split. SMA realized P&L was negative on every split. Coinbase PAXG daily history in that collect starts 2025-05-08. Futures are stored and not traded. Contango is not charged. The 0.50% short borrow is a labeled assumption. Platinum and palladium wait on that single metals slot.

## Stocks and penny stocks

Add a separate data adapter only if a delayed or end-of-day source can be used without an API key or a paid plan. Penny stocks need a wider cost model than the 5 bps crypto assumption: spreads and lot size dominate a 10 USD position. Keep them in their own tables so crypto candles and equity candles are not mixed in one SMA series.

## Shorts and perpetuals

Crypto and pump.fun shorts lock cash as collateral. Their borrow rate stays at 0. The metals book uses the same collateral lock and adds a 0.50% annualized borrow on shorts, actual/365, subtracted from unrealized P&L and from cash at the close. There is still no funding payment, no liquidation, and no live borrow quote. A perpetual, if one is added later, has to come from a public mark or candle endpoint that this environment can actually read, and it has to stay inside the same notional cap. Binance returned HTTP 451 for PAXG on 2026-10-25. No exchange account.

## Backtesting splits

`sma_crossover` 1.1.0 fills at the next candle open. `run-strategy` stores train, validation, and forward as separate experiment books with a one-bar gap. The 5/20 parameters are fixed before the forward window and are not fit on it. Version 1.0.0 same-bar results stay labeled `cash_era` 300.

## Scheduled collector

`.github/workflows/paper-hourly.yml` collects BTC and SOL hourly, collects metals, replays the paper strategies, writes the report, and commits `sollab.db` plus the status files to the `data` branch. A metals failure is a warning and does not fail the BTC job. The job is labeled simulated and does not use a secret. `.github/workflows/collect.yml` remains manual.

## Dashboard

A local read-only page over `data/sollab.db`: latest provenance rows, open paper position, realized versus unrealized P&L, and the rejection counts. No order button. The page should show the fetch time and the venue time on every price.
