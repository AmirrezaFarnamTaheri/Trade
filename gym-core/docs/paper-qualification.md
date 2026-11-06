# Recorded-data paper campaigns

## Whole-market extension — 6 November 2026

The expanded historical campaign is **running**, not complete. Its immutable
definition is `.pi/market-campaign/20261106/plan.json`. All 373 eligible spot
pairs receive the same 401-case definition: 149,573 historical cases in total.
The retained 469-row catalogue also exposes 96 rows that the venue does not
mark as spot markets. Risk flags, thin liquidity, missing observations and
unready indicators do not remove an eligible pair from the definition.

For every eligible pair, ten strategies use 1min/5min/15min bars, default and
fixed alternative parameters where supported, two chronological windows and
four fee/delay/outage scenarios (384 cases). EMA 2/5 covers the other eight
fixed timeframes over both windows (16 cases). One EMA 2/5 five-minute survey
completes the 401 cases. This is a current-listing survey of recorded history;
it does not reconstruct delisted markets or invent unavailable older quotes.

The first historical controller's 1,200-second per-market limit proved too
short for this matrix. Its workers were stopped and their original checkpoints
preserved. Recovery inspected native immutable experiment events and verified
available saved runs before registering `historical-continuation/plan.json`:
144,285 cases, including 30 explicitly repeated partial groups. Original
attempts, possible orphan artifacts and repeat links remain visible. The new
controller uses six direct base-interpreter workers, a six-hour worker bound
and a 5-GiB free-disk reserve. Interruption kills active children and cancels
queued work; a timeout remains unresolved evidence rather than a success.

Both prospective strategies were attempted on every pair: 746 cases per
cohort, 900 running seconds after actual warmup, with an 1,800-second wall cap.
The original cohort retained 735 aborts and 11 ended sessions. It exposed an
ordering defect: a reader could advance past rows from an incompletely
published 373-market collector tick. Schema 4 now commits the entire tick and
its publication watermark together. Watches read a consistent snapshot,
advance quiet scans only through that watermark, cap trading scans at the
running deadline and await committed publication before claiming completion.
Legacy stores without a watermark use disclosed quote-driven quiet scans.
Collector rollback also restores cached publication state.

The replacement cohort retained **670 ENDED and 76 ABORTED** artifacts across
all 373 pairs. Both strategies ended on 335 markets; neither ended on the
other 38. Audit of all 746 artifacts verified their digests and case identity,
with zero decisions after the 900-second deadline and zero recorded ordering
errors or backward clocks. Of the aborts, 56 had no qualified observations,
two did not finish warmup and 18 warmed up too late to complete 900 seconds
before the wall cap. Those are readiness failures, not venue exclusions.
The frozen retry engine predates the additional quiet-scan deadline cap; its
actual artifacts were separately checked for that edge case and had zero
violations. Saved artifacts were not rewritten to claim the later version.

The old retry engine calls any cancellation “Operator interrupted (Ctrl+C).”
All 76 aborts occurred at the runner wall cap; the independent audit preserves
the raw wording and explains that limitation. Current code instead propagates
the runner's explicit “Campaign wall limit reached” cancellation reason and
uses a neutral default for other cancellations.

The public margin catalogue returned 36 markets. All 72 LONG/SHORT directions
were attempted: 61 usable previews and 11 unavailable previews from network
failures or HTTP 422 validation rejection. A 422 is not evidence that the
market lacks margin eligibility; one retained investigation found an entry
price outside the venue's permitted band. The first replay set retains all
432 cases (three holding periods, two exit-fee assumptions per direction):
202 CLOSED, 116 OPEN, six CLOSE_PENDING, 42 ENTRY_PENDING and 66 with no usable
preview. A separately registered retry covers all 11 failed public previews
with new observed prices; the original failures remain. No entry, exit,
credential, loan, account permission or settlement is synthesized.

That retry recovered four usable public previews and retained seven HTTP 422
rejections. Its 66 replay cases retained four CLOSED, eight OPEN, 12 ENTRY_PENDING
and 42 without a usable preview at their declared cutoff. Longer requested
holdings do not become completed exits merely because calculation finished.

`report.html`, `results.csv` and `coverage.json` expose every catalogue row,
every historical definition including repeats, prospective outcomes and
margin states. Reports are dated snapshots. NOT_REPORTED may include a group
that is running or committed without a checkpoint; it never proves absence.
Native worker digest checks do not constitute independent accounting or
profitability qualification of this expanded campaign. Regenerate locally:

```powershell
rtk proxy gym-core/.venv/Scripts/python.exe gym-core/scripts/market_campaign.py report --output .pi/market-campaign/20261106
```

The collector was restarted after a stopped-source SQLite backup and now serves
all 373 spot pairs. HTTP verification at 15:56 UTC found all 469 catalogue rows
and 373 selected pairs, with 300 qualified at that instant. Selection coverage
does not promise continuously usable data on every market.

## Earlier completed baseline campaign

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
