# Precious metals research notes

Accessed 2026-10-25. This file is research for a paper replay. `sollab` does not place live orders, sign wallets, hold private keys, borrow real metal, open a futures account, or call a paid data API.

The traded paper book is one `metals` slot: at most 10 USD of PAXG, long or short, on the shared 5000 USD account (`account_rules` 4.0.0). Platinum, palladium, ETFs, and futures are collected as context. They are not orders.

## Ways to be long or short

### Spot quotes (XAU, XAG, XPT, XPD)

A spot quote is a dollar price per troy ounce. It is not itself a position. A long is allocated metal, an unallocated dealer credit, or one of the products below. A short at a dealer is a loan of metal that has to be returned, with a lease or borrow fee, or a forward that settles later.

London spot and the LBMA fixes are the usual reference prints. This lab did not find a keyless CSV of those prints. Stooq's `xauusd` and `gld.us` download pages returned a JavaScript browser check at 2026-10-25T22:16:20Z, so no rows were parsed.

### Listed ETFs

| Product | What a long holds | A short | Cost observed on 2026-10-25 |
| --- | --- | --- | --- |
| GLD (SPDR Gold Shares) | A share of a trust that holds gold | Borrow the shares, or use an inverse fund | Expense ratio 0.40% on the SSGA product page |
| SLV (iShares Silver Trust) | A share of a trust that holds silver | Same | Sponsor fee 0.50% in the iShares page JSON-LD |
| PPLT, PALL (abrdn platinum and palladium) | Shares of physically backed trusts | Same | Daily bars stored. Expense ratio not extracted; see below |
| GLL, ZSL (ProShares) | A daily -2x target versus a gold or silver subindex | The product is already short and leveraged | Expense ratio 0.95% on each ProShares page. Not collected and not traded |

The expense ratio is taken out of fund assets, so the share price lags the metal by about that rate each year, plus any premium or discount to NAV. A stock-loan short of GLD or SLV pays a borrow fee on top of that drag. This lab has no keyless borrow tape for those tickers. The 0.50% APR below is a research assumption for the paper PAXG short, not a quote from a securities lender.

GLL and ZSL reset every day. A -2x fund that is held across many days does not deliver -2 times the period return. Volatility decay is an extra cost. They are documented here and left out of the collector allowlist.

PPLT and PALL bars come from the Yahoo chart endpoint. Aberdeen product HTML URLs returned 404 in the earlier pass the same evening, and the factsheet PDF (`editionid=f759aacf-4314-41c1-b8b3-3e02c2967aed`) was binary and was not decoded (`pdftotext` is not installed). No platinum or palladium expense ratio is cited, and the ledger does not charge one.

### Futures (GC, SI, PL, PA)

CME standard sizes are 100 troy ounces of gold (GC), 5,000 of silver (SI), 50 of platinum (PL), and 100 of palladium (PA). Micro gold (MGC) is 10 ounces and micro silver (SIL) is 1,000 ounces. At the 2026-10-23 front-month closes stored below, one standard gold contract is on the order of 400,000 USD and one micro gold contract is on the order of 40,000 USD. A 10 USD paper slot cannot hold any of them. The lab does not model margin, leverage, or liquidation.

Yahoo `GC=F`, `SI=F`, `PL=F`, and `PA=F` are front-month chart series. They are not a rolled total-return index. When the curve is in contango, a long that rolls pays the upward spread and a short that rolls receives it. Backwardation reverses that. Gold's curve is often near the interest rate minus the gold lease rate. This replay does not measure the curve and does not charge roll.

### Tokenized gold (PAXG, XAUT)

PAXG (Paxos) and XAUT (Tether Gold) are tokens intended to track about one troy ounce of allocated gold. A long is a spot purchase on an exchange. Creation and redemption fees apply to the institutional bar process. They are not a daily expense ratio, and the paper book does not charge one.

A short on a crypto venue would be a margin loan or a perpetual. Binance spot and USDT-M `PAXGUSDT` returned HTTP 451 from this environment (`Service unavailable from a restricted location`) at 2026-10-25T22:15:49Z. No perpetual funding rate was stored. The paper short is the ledger's own collateral model: the 10 USD notional stays locked, cash does not increase, and a borrow rate accrues. That is not a venue position.

Coinbase Exchange lists `PAXG-USD`. `XAUT-USD` returned HTTP 404 at 2026-10-25T22:15:49Z. XAUT daily bars come from Kraken. CoinGecko returns a spot for both.

## Costs the paper book actually charges

`metals_sma_trend`, `metals_gold_silver_ratio`, and `metals_buy_hold` share these fills:

- 0.6% taker-style fee on the open and again on the close
- 5 bps of adverse slippage
- short borrow of 0.50% annualized (`SHORT_BORROW_APR = 0.005`), actual/365, on the entry notional
- longs accrue no borrow
- crypto and pump.fun books keep `borrow_apr` at 0, so older SMA and pump rows are unchanged

Accrued borrow is subtracted from unrealized P&L while the short is open, and from realized P&L and cash when it closes. One day on a 10 USD short at 0.50% is about 0.014 cents. Over the windows below, fees and slippage dominate that borrow.

## Drivers, and what the baselines use

Real yields. Gold has no coupon, so a higher real yield is a higher opportunity cost of holding it. FRED `DFII10` (10-year TIPS) was 2.64 on 2026-10-22, with 2.77 and 2.76 on the two prior business days. CSV fetched 2026-10-25T22:15:39Z from `fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10`. The collector does not store FRED, and neither strategy uses it.

The dollar. Metals are usually quoted in dollars, and a stronger dollar often coincides with a lower dollar price. Two different indexes were read and must not be mixed:

- FRED `DTWEXBGS` (nominal broad dollar) 121.4048 on 2026-10-16. Same fetch time as DFII10.
- ICE `DX-Y.NYB` via the Yahoo chart endpoint, regular-market price 101.752 at source time 2026-10-23T20:59:59Z. Fetched 2026-10-25T22:15:49Z. This symbol is not in the collector allowlist.

The gold/silver ratio. Ounces of silver per ounce of gold. A high ratio is the usual "gold rich versus silver" reading, and a mean-reversion rule fades it. That rule is the second baseline. It lost to buy-and-hold on every split after costs.

## Free sources that returned data

Collector run `collected_at` 2026-10-25T22:12:29Z, rows received around 2026-10-25T22:13:00Z. Sample: `data/samples/metals_public_prices.json`, label `REAL_PUBLIC_FETCH`. The database `data/metals.db` is gitignored. The hourly workflow writes the shared `data/sollab.db` on the `data` branch once this code is on `main`. It is not on `main` yet.

| Source | Series | What came back |
| --- | --- | --- |
| Coinbase Exchange | `PAXG-USD` ticker | 4002.89, venue time 2026-10-25T22:11:47.222898Z |
| Coinbase Exchange | `PAXG-USD` daily candles, granularity 86400, requested from 2021-01-01 in 280-day chunks | 535 closed days, 2025-05-08 through 2026-10-24. Older chunks were empty. This is the traded series. Latest close 3998.65 |
| Kraken public OHLC, interval 1440 | `PAXGUSD` | 720 bars, the API cap, 2024-11-04 through 2026-10-24. Close 3998.49 on the last bar. Stored, not traded. The replay stays on Coinbase so the book is not switched after seeing P&L |
| Kraken | `XAUTUSD` | 408 bars, 2025-09-12 through 2026-10-24. Last close 3988.7 |
| CoinGecko `simple/price`, no key | `pax-gold`, `tether-gold` | 4006.26 and 3995.77, `last_updated_at` 2026-10-25T22:12:29Z |
| Yahoo chart `query1.finance.yahoo.com/v8/finance/chart`, no key | GLD, SLV, PPLT, PALL, GC=F, SI=F, PL=F, PA=F, `range=5y&interval=1d` | About 1,255 to 1,258 daily bars from 2021-10-25, plus one spot print. Timestamps are session starts (ETFs 13:30 UTC, futures 04:00 UTC), not the close time. A bar still inside its 86400-second window is dropped |

Latest stored daily closes from that collect:

| Symbol | Close | Bar timestamp |
| --- | --- | --- |
| GLD | 366.6099853515625 | 2026-10-23T13:30:00Z |
| SLV | 48.720001220703125 | 2026-10-23T13:30:00Z |
| PPLT | 14.050000190734863 | 2026-10-23T13:30:00Z |
| PALL | 18.940000534057617 | 2026-10-23T13:30:00Z |
| GC | 4007.89990234375 | 2026-10-23T04:00:00Z |
| SI | 53.71099853515625 | 2026-10-23T04:00:00Z |
| PL | 1554.199951171875 | 2026-10-23T04:00:00Z |
| PA | 1046.5999755859375 | 2026-10-23T04:00:00Z |

The allowlist accepts `query1.finance.yahoo.com` only for `/v8/finance/chart/{symbol}` and only for those eight symbols. `=` is percent-encoded on the wire and checked after decoding. Other hosts and other Yahoo paths are refused before the request.

## Baselines

All three are version 1.0.0, book `experiment`, `cash_era` 5000, fill model `next_candle_open`. Parameters are fixed in code. They are not fit on validation or forward. Splits follow `plan_splits`: train 60%, validation 20%, forward the rest, one unscored bar between scored windows. Each period is its own book starting at 5000 USD. `reset_strategy_version` runs once per strategy, then all three windows are stored.

`metals_buy_hold` buys 10 USD of PAXG at the first open inside the scored window and sells at the last bar's close. It is the benchmark.

`metals_sma_trend` is a 5/20 SMA crossover on Coinbase PAXG daily closes. A bullish cross queues a long. A bearish cross queues a short. The fill is the next bar's open. An opposite signal closes the open position and does not reverse on the same bar. A signal with no later bar is `no_next_candle`.

`metals_gold_silver_ratio` uses one PAXG leg. Silver is a signal, not a second position, because the metals market has one slot. The ratio is the PAXG close divided by the latest `SI=F` close whose bar timestamp is at or before that PAXG bar. Futures bars are stamped 04:00 UTC and PAXG bars 00:00 UTC, so the silver print used at a PAXG bar is the prior session. A cross of the ratio above its own 20-bar mean queues a short. A cross below queues a long. Same fill and no same-bar reversal as the SMA rule.

Replay recorded at 2026-10-25T22:13:10.238644Z. 535 PAXG daily bars, 1,257 silver daily bars. Exact rows: `data/samples/metals_replay_summary.json`, label `SIMULATED_REPLAY_NOT_LIVE_TRADES`.

| Period | Window (signal) | Strategy | Ending equity | Realized | Unrealized | Closed (wins) | Open at end |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train | 2025-05-08 to 2026-03-24 | buy-and-hold | 5003.31218774 | +3.31218774 | 0 | 1 (1) | flat |
| train | same | SMA 5/20 | 4999.36640130 | -1.85916153 | +1.22556283 | 8 (1) | short PAXG |
| train | same | gold/silver ratio | 4996.33334652 | -3.61379183 | -0.05286165 | 27 (5) | short PAXG |
| validation | 2026-03-26 to 2026-07-10 | buy-and-hold | 4998.97360881 | -1.02639119 | 0 | 1 (0) | flat |
| validation | same | SMA 5/20 | 4999.22542280 | -0.54418768 | -0.23038952 | 2 (0) | long PAXG |
| validation | same | gold/silver ratio | 4998.20525886 | -1.79474114 | 0 | 12 (3) | flat |
| forward | 2026-07-12 to 2026-10-24 | buy-and-hold | 4999.62819179 | -0.37180821 | 0 | 1 (0) | flat |
| forward | same | SMA 5/20 | 5000.78809956 | -0.14972192 | +0.93782148 | 1 (0) | short PAXG |
| forward | same | gold/silver ratio | 4998.27311994 | -1.72688006 | 0 | 13 (2) | flat |

A win is a closed position with realized P&L above zero.

Reading that table without smoothing it:

- Buy-and-hold made money only on the train window. Validation and forward buy-and-hold lost money after the round-trip fee and slippage. The position is 10 USD, so a few dollars of P&L is a large percentage of the position and a small fraction of the 5000 USD book.
- The ratio rule lost to buy-and-hold on train, validation, and forward. Closed-trade win rates were 5/27, 3/12, and 2/13. Costs on that many turns are the result.
- SMA realized P&L is negative on every split. Train equity is below buy-and-hold. Validation equity is 0.25 above a losing buy-and-hold, with realized still negative and an open long. Forward equity is above 5000 only because the open short has unrealized gain. That open short is not closed alpha.

Coinbase history starts on 2025-05-08, so this is about seventeen months, not the five years the Yahoo charts cover. Kraken's longer PAXG series was not substituted after the fact.

## Scheduled run

`.github/workflows/paper-hourly.yml` still fires hourly (`0 * * * *`) and the pump.fun burst every six hours (`15 */6 * * *`). The hourly job runs `metals-collect` and `metals-run` after the BTC/SOL replay. A metals failure is a warning. It does not fail the BTC job. `report` then includes a Metals section in `status.md` and a `metals` object in `status.json`.

The repository is public, so standard GitHub-hosted minutes are not billed. The cadence stays. Each successful job commits `sollab.db` to `data`, and that history grows by about the database size every time. The job also calls public APIs. Those two limits are why the pump.fun burst was not shortened in this change.
