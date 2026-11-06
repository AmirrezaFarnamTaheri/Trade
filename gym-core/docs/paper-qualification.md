# Recorded-data paper campaign

Completed 2026-11-06 (Asia/Tehran). All orders and balances below are simulated.
No exchange account read, order, loan or transfer was made by this campaign.
These exploratory results do not qualify a strategy or complete the funded plan.

## Coverage and retained outcomes

The definition was saved before calculation. It registered 525 experiment groups
and 1,973 attempts through the existing experiment registry. Public normalized
market observations were frozen in a SQLite backup; the complete Python engine
source was retained and matched the registered engine digest. Definitions,
attempts, failures and saved run artifacts remain visible through the native
registry and saved-run interfaces.

| Set | Cases | Results |
| --- | ---: | --- |
| Strategy/cost/outage comparisons | 1,536 | All completed |
| Additional fixed-timeframe coverage | 64 | All completed |
| Recorded 373-market universe survey | 373 | 345 completed; 28 incomplete with `NO_QUALIFIED_DATA` |
| Public-preview margin supplement | 12 | All reached a modeled cash exit |
| Prospective watches | 5 attempts | Four ended; one original startup failure retained |

The comparison set covers BTCUSDT, ETHUSDT, BTCTMN and USDTTMN, all ten native
strategies, default/fixed alternative parameters where supported, two disjoint
chronological windows, and four cost/feed scenarios. Timeframe coverage spans
all eleven fixed resolutions from one minute to one day. The survey applies one
fixed EMA configuration to each actually recorded market; it is not a historical
listing census or a strategy search over all markets.

Chronological windows are 2026-11-05 15:30–18:00 UTC and 2026-11-05 22:00 through
2026-11-06 05:00 UTC. The universe survey uses 2026-11-06 00:00–05:00 UTC.
The scenarios assume fee rates 0/0.001/0.002 with delays 0/500/2,000 ms;
the fourth repeats the middle assumptions with two declared 15-minute feed
removals. Zero fees are a diagnostic case. Initial virtual cash is 1,000 USDT
or 300,000,000 TMN. Independent accounts/currencies are never summed as portfolio
profit. Windows were selected for recorded coverage, not observed returns;
they still are not untouched final evaluation periods.

Of the 1,945 completed historical runs, 1,223 contain modeled fills and 722 have
none. There are 1,052 stale final marks. Only 756 runs have both fills and a mark
no more than 120 seconds old at the endpoint. Insufficient indicator history,
closed markets, missing observations and unexecuted intents are retained; a
completed replay does not mean every strategy had enough warmup to trade.

## Prospective results

Every completed watch ran for 15 minutes after actual warmup. These short
sessions are operational evidence, not sustained performance qualification.

| Market / strategy | Qualified observations | Modeled fills | Net in quote currency |
| --- | ---: | ---: | ---: |
| BTCUSDT / EMA 2,5 | 256 | 4 | -7.33162813 USDT |
| ETHUSDT / EMA 2,5 | 397 | 3 | -6.91238188 USDT |
| BTCUSDT / SMA reversion 5,50 | 256 | 0 | 0 USDT |
| BTCTMN / EMA 2,5, retry | 256 | 3 | +19409.16471845 TMN |

The original BTCTMN watch aborted before receiving data because Windows returned
the same timestamp twice at startup. A test reproduced the failure; the shared
live watcher now skips an empty read interval while still aborting backward
clocks. A new definition was recorded before the successful retry. Both attempts
remain available. BTC/ETH watches ran 10:42–10:57 UTC; BTCTMN ran 11:39–11:54 UTC,
so their market periods differ. Assumed fee rate is 0.001 and delay is 500 ms.

Margin cases replay previously retained actual public LONG/SHORT previews at
Wallex credit ratio 2, collateral 100 USDT, holding periods 120/900/3,600 seconds
and exit-fee assumptions 0.001/0.002. Entry and close depth failures remain
recorded. The longer replay lets the formerly unmatched LONG limit encounter
later actual quotes; no entry is synthesized. No borrowing is performed.
Extension-fee accrual and liquidation are not exercised by these short cases.

## Verification and limits

Every available run passed the native input/output digest checks. A separate
Decimal audit reconstructs balances from postings, reconciles ending bid-marked
equity and checks the rounded cost waterfall exactly. Its asset-specific balance
tolerance is the larger of `1e-24` units and `1e-26` times gross posted amounts
plus starting cash, allowing accumulated 28-significant-digit arithmetic.
Maximum observed balance residual was `5.78e-18` asset units; maximum equity
residual was `4.879e-20` quote units. Rounded reported net is checked within
`0.000000005` quote units. Each run retains its actual residual/tolerance.
Closed margin cases separately check zero debt and cash/equity agreement;
they do not have the spot posting waterfall.

The first completed attempt for each of the ten strategies was repeated from
the same frozen data and engine. All serialized outputs matched exactly.
This deterministic regression is not independent economic validation.

The campaign exposed and fixed an experiment budget error: unrelated collected
markets no longer exhaust a single instrument's budget. Main, baseline, FX and
configured-reference observations still count, with boundary regressions.
Prospective artifacts now pass the shared verified-run reader and decision
debugger; absent prospective baselines remain unavailable rather than invented.

Depth beyond the observed top, queue position, real fill latency, charged fees,
account ownership, venue settlement and independent source custody remain
unqualified. Data gaps prevent a continuity claim, and short history prevents
full warmup/strategy qualification at higher timeframes. No positive exchange
loss budget exists. Executor admission and real protection remain unfinished.

## Local evidence

Directory: `.pi/paper-campaign/20261106T102617Z/` at the repository root.

- `report.html`: portable, searchable full result table; no remote dependencies.
- `results.csv` and `audit.json`: all historical attempts, prospective attempts,
  costs, exact balances, baselines, mark ages and audit checks.
- `plan.json`, `results.json`, `groups/`, `prospective-*.json`, `retry-plan.json`,
  `margin-plan.json`, `margin-results.json` and `repeatability.json`: definitions
  and retained receipts. Run artifacts and registry events are in `data/live`.
- `market.db`: 546,615,296-byte public normalized snapshot. Compressed raw audit
  archives were not duplicated into the campaign.
- `engine/` and `engine-manifest.json`: exact source used by historical workers.

Snapshot SHA256: `0b17bcf725a855991c9a9f3f4dc3863abe93dc6d288c7649f114dbe3b8fe2723`.
Historical engine digest: `e3be229198e4833ab1e3aad968cf2196191e781909bac9097ada8db647fdd119`.
The retry records its later source digest separately. Local hashes detect
inconsistent copies; they do not establish independent custody.
