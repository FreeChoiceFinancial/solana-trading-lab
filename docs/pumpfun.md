# pump.fun research notes

Accessed 2026-10-25. This file is research for a paper replay. `sollab` does not create coins, sign transactions, store private keys, or call a keyed pump.fun API.

`pump-fun/pump-fun-skills` was read as public documentation only. Its README describes coin creation, swaps, and creator-fee collection. The repository had no `LICENSE` file. Those scripts were not installed or executed. `pump-fun/pump-public-docs` also had no `LICENSE` file; the notes below quote published formulas and do not vendor the IDL.

## Bonding curve

Program: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`.

Global account: PDA seeds `["global"]`, address `4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf`. Confirmed by the public docs and by a local PDA derivation.

Bonding-curve account: PDA seeds `["bonding-curve", mint]`.

The public program README gives these initial parameters (the same values were still in the live Global account on 2026-10-25):

| Field | Raw units |
| --- | --- |
| initial virtual token reserves | 1,073,000,000,000,000 |
| initial virtual quote reserves | 30,000,000,000 lamports (30 SOL) |
| initial real token reserves | 793,100,000,000,000 |
| token total supply | 1,000,000,000,000,000 (1e9 tokens at 6 decimals) |

Spot price is the virtual-quote reserve divided by the virtual-token reserve. Market cap in lamports, from the fee-program docs, is:

```text
virtual_quote_reserves * mint_supply / virtual_token_reserves
```

With the initial reserves that is 27,958,993,476 lamports, about 27.959 SOL. A new coin therefore does not start at a zero price. The virtual reserves are synthetic. Real SOL reserves start at 0 and real token reserves start at the initial real inventory.

`complete` becomes true when a buy leaves `real_token_reserves == 0`. Migration is permissionless (`migrate`) and sends the curve's liquidity to PumpSwap. The LP tokens are burnt. The old withdraw-to-Raydium path is deprecated and disabled while `enable_migrate` is true. Graduation also costs 0.015 SOL, taken from a SOL curve or paid by the migrator for other quotes.

Later account fields (`creator`, mayhem, cashback, `quote_mint`, and others) are appended. A short account does not mean those fields are zero; this lab leaves them unknown unless the bytes are present. `quote_mint` of 32 zero bytes means native SOL.

### Buy quote used for paper fills

The public IDL documents `buy_exact_sol_in` as:

```text
net_sol = floor(spendable_sol_in * 10_000 / (10_000 + total_fee_bps))
fees = ceil(net_sol * protocol_fee_bps / 10_000) + ceil(net_sol * creator_fee_bps / 10_000)
if net_sol + fees > spendable_sol_in:
    net_sol = net_sol - (net_sol + fees - spendable_sol_in)
tokens_out = floor((net_sol - 1) * virtual_token_reserves / (virtual_quote_reserves + net_sol - 1))
```

`total_fee_bps` is protocol plus creator. The paper buy uses that formula on the fill snapshot's virtual reserves, then reduces `tokens_out` by the extra slippage below. If `tokens_out` is greater than `real_token_reserves`, the order is rejected. The lab does not model the synthetic last-buy that completes a curve into a PumpSwap pool.

### Sell quote

The IDL page that states the buy formula does not state a numbered sell formula. Sells in this lab use `paper_sell_v1`:

```text
gross = floor(tokens * virtual_quote_reserves / (virtual_token_reserves + tokens))
fees = ceil(gross * protocol_fee_bps / 10_000) + ceil(gross * creator_fee_bps / 10_000)
net = gross - fees
proceeds = floor(net * (10_000 - extra_slippage_bps) / 10_000)
```

That is a constant-product inverse with fees taken from the output. It is not claimed to be byte-identical to the on-chain sell instruction. A completed curve is not priced this way, and PumpSwap's signed `virtual_quote_reserves` adjustment is not applied.

Progress stored by the collector is `(initial_real_token_reserves - real_token_reserves) / initial_real_token_reserves` using the initial value decoded from Global on that poll. If the account does not match the documented initials, progress is left null.

## Fees

Two published numbers disagree, and the live account matched only one of them.

The program README's embedded Global JSON shows `fee_basis_points` 100 and `creator_fee` 0. That JSON is older than the fee schedule.

The fees page, last updated 17 October 2026, says a bonding-curve trade in a SOL or USDC quote is:

| Creator | Protocol | LP | Total |
| --- | --- | --- | --- |
| 0.300% | 0.95% | 0% | 1.25% |

On 2026-10-25 a `getAccountInfo` of the Global account (owner the pump program, discriminator `sha256("account:Global")[:8]`) had `fee_basis_points` at the documented offset equal to **95**, not 100. No u64 value 30 or 125 was present in that account. The creator fee is therefore taken from the fees page, not from a decoded Global field.

The paper model pins protocol 95 bps and creator 30 bps. `pumpfun-run` rejects entries when the stored Global decode is missing or is not 95. It does not silently replace a changed on-chain fee.

PumpSwap canonical pools use a market-cap ladder (0.300% to 1.250% total depending on the tier). Custom-pair coins are flat: 1.25% on the curve and 0.30% on a canonical PumpSwap pool. This strategy does not trade graduated pools, so those ladders are not applied.

From 17 October 2026 the pump.fun web and mobile apps add a platform fee of 0.45% (0.40% with a referral code). The fees page says that fee is not charged on Terminal or other interfaces. This lab models a direct curve trade and does not add the app platform fee.

Solana network fees are separate. The paper model adds 5,000 lamports for one signature plus a priority fee. The priority fee is the upper median of `getRecentPrioritizationFees` (micro-lamports per compute unit) times an assumed 200,000 compute units. The compute-unit count is an assumption, not a measured simulation of a pump instruction. Both pieces are converted to USD with the stored SOL price. If that price or the priority sample is missing, the fee is unknown and the fill is rejected.

## Read-only sources

| Source | What it provided on 2026-10-25 | Limit |
| --- | --- | --- |
| GeckoTerminal `GET /api/v2/networks/solana/dexes/{pump-fun,pumpswap}/pools?page=1` | Pool address, creation time, USD price, FDV, reserve USD, volume, buys/sells and unique buyers/sellers. Token mints are in the relationship id `solana_<mint>`. The free page does not inline token objects. | The public page says paid CoinGecko plans raise the cap from 10 calls/minute to 250. This lab stays on the free cap and requests two pool lists per poll. |
| DexScreener `GET /tokens/v1/solana/<mints>` | Price, liquidity USD, volume, buy/sell counts, pair creation time, market cap. No unique buyers and no creator balance. | Documented pair/token/search limit is 300 requests/minute. |
| Solana public RPC `https://api.mainnet-beta.solana.com` | `getAccountInfo` (Global), `getMultipleAccounts` (curve PDA and mint), `getRecentPrioritizationFees`. | No API key. The public node rate-limits and often rejects heavy scans. This lab does not call `getProgramAccounts` or any method that submits a transaction. |
| CoinGecko `simple/price` | SOL/USD for fee conversion. | Keyless public endpoint already used by the BTC/SOL collector. |
| `api.pump.fun` | Not used for rows. A keyless GET of `/v1/users/search-v2` returned HTTP 401 `API_KEY_REQUIRED` during research on 2026-10-25. | Developer docs describe a free key at about 2 requests/second, a 120-request per 60-second bucket, and 50,000 successful requests per UTC day. A key was not requested. |
| `frontend-api-v3.pump.fun` | Not used for rows. A keyless GET returned HTTP 403 and a Cloudflare challenge page. | The lab does not spoof headers or retry past the challenge. |

GeckoTerminal's `pump-fun` list is the bonding-curve dex. `pumpswap` is the graduated dex. A pool on that list is not always quoted in SOL; the first row observed during research was `BCT / WBTC`. SOL pairs are detected from the wrapped-SOL mint or from a native-SOL `quote_mint` on the curve account. Only SOL quotes are eligible for the paper strategy. USDC and custom pairs are stored and then rejected as `non_sol_quote`.

Holder count, top-holder percent, and the creator's token balance were not in these payloads. Those flags stay `unknown`.

`source_timestamp` is null on pump snapshots. These HTTP payloads did not include a per-pool quote time. `created_at` is the indexer's pool creation time. `fetched_at` is the local UTC time when the poll finished. GeckoTerminal's free responses are an index, not a tick tape. Curve reserves come from the RPC read in the same poll, which is the clock the fill uses.

## Terms and other limits

pump.fun Terms of Use section 6.1 allows automated access only where the terms expressly permit it, and section 21(h) prohibits crawlers, bots, spiders, and similar devices against the Pump Platform except as section 6.1 permits. This lab does not crawl pump.fun pages and does not parse a pump.fun API body into the database. The two probe URLs above are recorded as errors so the block is visible.

Public Solana account data is chain state read with `getAccountInfo` / `getMultipleAccounts`. GeckoTerminal and DexScreener are third-party market APIs used at low volume for research storage in this repo. This is not a legal opinion, and it is not permission to resell their data or to bypass a challenge.

The official developer API's own terms, as published on docs.pump.fun, restrict bulk collection and say the API is not primarily a market-data feed. It also requires a key. Neither is used here.

What the stored rows cannot support:

- creator holding percent, top-holder concentration, and creator-sell detection
- a byte-exact PumpSwap quote after graduation
- a sub-second trade tape (indexer windows are m5 and longer)
- proof that a mint or freeze authority is absent when the mint account read failed

## Paper strategy

`bonding_curve_momentum` version `1.0.0`. Long only, market `pump.fun`.

Enter when a stored snapshot is on the SOL bonding curve, progress is at least 0.20 and below 0.90, the m5 window has at least 8 buys and 4 buyers, buys exceed sells, and every blocking flag is the stored value `false`. Blocking flags: `very_young` (under 120 seconds), `wash_trade_like` (at most 2 buyers and at least 15 buys in m5), `thin_liquidity` (a $10 buy moves the curve price more than 15% from spot, or indexed reserve USD is under 10 when the curve quote cannot be computed), `mint_authority_active`, and `freeze_authority_active`. A true flag rejects as `red_flag:<name>`. An unknown blocking flag rejects as `flag_unknown:<name>`. The three holder/creator flags above are informational and do not block, because the input is absent rather than safe.

One open position in market `pumpfun`. An open `crypto_spot` position does not take that slot. A current-era open `pumpfun` position rejects a new entry with `blocked_by_open_position`. Spendable cash starts at the cash_era 5000 book's free cash when that book exists, otherwise 5000 USD. The maximum notional stays 10 USD and the minimum stays 1 USD. `cash_era` 300 rows, including the preserved BTC short, stay stored and do not fund or block this market.

The fill is the first later snapshot of that mint at least 30 seconds after the signal. Price impact is the buy formula on that later snapshot. Exit signals are take profit at +40% of curve proceeds versus entry notional, stop at -20%, 1,200 seconds after the fill, or graduation. The exit fill uses `paper_sell_v1` on a later on-curve snapshot. Graduation does not invent a PumpSwap exit price; the close is rejected as `graduated_no_curve_quote` and the position stays open with an unknown mark if the curve can no longer be quoted.

Every fill row is labeled `SIMULATED_PUMPFUN_NOT_A_LIVE_TRADE`.

## Polling cadence

Hourly collection is too slow for this market. Coins move through the first page of new pools in minutes, and the paper rule needs two snapshots at least 30 seconds apart before it will fill.

This repository is private. GitHub's free plan includes 2,000 Actions minutes per month for private repositories. The shortest cron interval GitHub accepts is 5 minutes, and scheduled workflows can be delayed or disabled after 60 days without repository activity. A 5-minute schedule is about 8,640 runs a month. Even a one-minute job would spend more than the free private quota. An hourly job of about two minutes is inside the quota (roughly 1,500 minutes) and still misses the launches this strategy is about.

`.github/workflows/paper-hourly.yml` runs a two-poll burst every six hours (`--polls 2 --interval 35`) and commits the database to the `data` branch. That is about 120 runs a month. At roughly two to two and a half minutes each, it is about 240–300 minutes, on top of the hourly BTC/SOL job. Together they stay inside the 2,000-minute private free tier if the jobs stay near those durations. It is still not a sub-second tape. The manual workflow remains `workflow_dispatch` with one poll. A local `python -m sollab pumpfun-collect --polls 2 --interval 35` is the same burst.

## Collection on 2026-10-25

`python -m sollab pumpfun-collect --polls 2 --interval 35` stored 80 snapshots in two polls, `fetched_at` `2026-10-25T16:48:50.245934Z` and `2026-10-25T16:49:32.334254Z`. GeckoTerminal, DexScreener, CoinGecko, and the public Solana RPC all returned data. CoinGecko SOL/USD was 101.3 then 101.33. Global decoded with `fee_basis_points` 95. `getRecentPrioritizationFees` returned 150 samples whose upper median was 0 micro-lamports, so the stored priority fee for those polls is 0 and the base fee stays 5,000 lamports. 76 snapshots had a decoded bonding-curve account. Mint and freeze authorities decoded as `none` on all 80. Creator balance, holder lists, and creator trades were absent on all 80.

The keyless developer API returned HTTP 401 `API_KEY_REQUIRED` at `2026-10-25T16:48:49.678Z` and again at `2026-10-25T16:49:31.745Z`. The frontend coins URL returned HTTP 403 with a Cloudflare "Just a moment..." page both times. Those bodies were not parsed into rows.

`pumpfun-run` at `2026-10-25T16:49:38.138288Z` produced no simulated fills. Of 80 decisions, 52 were `already_graduated`, 10 `progress_below_threshold`, 8 `buy_flow_below_threshold`, 8 `non_sol_quote`, and 2 `red_flag:wash_trade_like` (BRAVE, 77 buys and 1 buyer). None passed the entry filters. The cash_era 300 book still had an open BTC short. Under account_rules 3.0.0 that short stays in the 300 USD book and does not block a pump.fun entry. A small labeled subset is in `data/samples/pumpfun_public_tokens.json`.

## Sources

- https://github.com/pump-fun/pump-public-docs/blob/master/docs/PUMP_PROGRAM_README.md accessed 2026-10-25
- https://github.com/pump-fun/pump-public-docs/blob/master/docs/FEE_PROGRAM_README.md accessed 2026-10-25
- https://github.com/pump-fun/pump-public-docs/blob/master/idl/pump.json `buy_exact_sol_in` quote, accessed 2026-10-25
- https://github.com/pump-fun/pump-public-docs accessed 2026-10-25 (PumpSwap migration, deprecated Raydium withdraw)
- https://github.com/pump-fun/pump-fun-skills accessed 2026-10-25 (README only; scripts not run)
- https://pump.fun/docs/fees last updated 17 October 2026, accessed 2026-10-25
- https://pump.fun/docs/terms-and-conditions sections 6.1 and 21(h), accessed 2026-10-25
- https://docs.pump.fun developer API limits, accessed 2026-10-25; keyless probe returned HTTP 401 `API_KEY_REQUIRED`
- https://www.geckoterminal.com/dex-api accessed 2026-10-25 (free tier 10 calls/minute)
- https://docs.dexscreener.com/api/reference accessed 2026-10-25 (300 requests/minute on token and pair routes)
- Solana public RPC `https://api.mainnet-beta.solana.com`, Global account read on 2026-10-25, `fee_basis_points` 95
- https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule and GitHub Actions billing for private minutes, accessed 2026-10-25. Repository visibility checked the same day: private.
