# Trial log

One question governs every entry: is there a net edge on Wallex after costs, against holding USDT?

Each hypothesis is written here with its data and pass mark **before** it is run. The result is added afterwards and
the pass mark is never edited. A new idea is a new entry, so the count of things tried stays honest.

Costs used throughout, per side: the account rate read from `/v1/account/fee` (0.10%), and the published level-1
rates from `/v2/structured-fee` (Toman markets 0.25% maker, 0.30% taker; USDT markets 0.10% maker, 0.13% taker).

| ID | Registered | Hypothesis | Data | Pass mark | Result |
| --- | --- | --- | --- | --- | --- |
| T1 | 2026-11-13 | Intraday mean reversion on USDTTMN beats holding USDT (Version 1; 12 settings per fee rate). | 1-minute venue candles, 1,096 sessions before 2026; 308 later sessions held out. | Deflated Sharpe probability at least 0.95 on the ranking sessions, then the held-out sessions scored once. | **FAIL** (2026-11-14). Best 0.001. Held-out sessions not scored. `scripts/usdttmn_v1.py --bars`. |
| T2 | 2026-11-14 | In some Wallex market, resting orders on both sides earn more than they cost. | Recorded quotes and trades, all watched markets, from 2026-10-30. | A market qualifies only if all hold: median spread at least 0.40%; at least 50 trades a day; median touch at least 50 USDT; and the maker's result per trade, measured against the mid five minutes later and charged two maker fees, has a positive mean with t at least 4 on at least 500 trades over at least 5 days. | **FAIL** (2026-11-14). 333 markets; 319 have a spread of 0.40% or more, 13 of those are liquid enough, and in 12 of the 13 the resting side loses after fees (prices move against it). Nearest misses: POLTMN (+0.34% a trade, t 8.6) and IOTMN (+0.52%, t 7.3) at the account fee, both failing on touch size (15 and 32 USDT). |
| T3 | 2026-11-14 | The USDT/Toman rate implied by BTC or ETH (coin/TMN divided by coin/USDT) departs from USDTTMN by more than three taker fees. | Recorded quotes for the three markets of each triangle, in the USDTTMN session, on a one-minute grid. | The gap at executable prices, after 0.30% in fees, is positive in at least 1% of minutes and on at least 5 days. | **FAIL** (2026-11-14). 3,211 minutes on 10 days. Median gap after 0.30% fees: BTC -0.36%, ETH -0.46%. Positive in 0.37% and 0.19% of minutes, on 2 days and 1 day (the 10 November crash). |
| T4 | 2026-11-14 | Holding BTCUSDT or ETHUSDT only while the daily close is above its moving average beats holding USDT (averages of 50, 100 and 200 days; 6 settings). | Venue daily candles; settings ranked on days before 2024-01-01. | Deflated Sharpe probability at least 0.95 on the ranking days; then days from 2024-01-01 scored once for the best setting, where the probability that its Sharpe is above zero must be at least 0.90. | **FAIL** (2026-11-14). Best deflated probability 0.852 (BTCUSDT, 200-day, yearly Sharpe 1.52 on 520 ranking days). Days from 2024-01-01 not scored and still unseen. The venue's daily history before October 2021 has no traded volume, so the ranking period is short. |
| T5 | 2026-11-14 | The zero-fee market (USDSUSDT) moves enough inside a day to pay for crossing its spread. | Recorded quotes from 2026-10-30. | Median over days of the best same-day round trip at the touch (perfect foresight, no fee) at least 0.20%, with median touch at least 100 USDT. This is an upper bound: a pass only earns a real rule its own entry. | **FAIL** (2026-11-14). 9 days. Median spread 0.97%, median touch 63 USDT, median best round trip -0.53%: the spread is wider than the daily movement. |
| T6 | 2026-11-14 | The same trend rule as T4, with its six settings ranked on a longer history from another exchange. | Binance daily candles for BTCUSDT and ETHUSDT from 2017-08 for ranking (days before 2024-01-01); Wallex daily candles from 2024-01-01 for the one scoring. | Same marks as T4: deflated Sharpe probability at least 0.95 on the ranking days; then the Wallex days from 2024-01-01 scored once for the best setting, where the probability that its Sharpe is above zero must be at least 0.90. A pass earns a prospective paper run, not a claim of an edge. | **PASS, narrowly** (2026-11-14). Ranking: BTCUSDT 50-day, deflated 0.998 on 2,278 Binance days. Wallex days from 2024-01-01, 1,049 days at the account cost: +80.6%, yearly Sharpe 0.80, probability 0.917 against 0.90 (published cost: +76.8%, 0.910). Holding BTC over the same days made +56.3%. By year: 2024 +76.1%, 2025 -2.5%, 2026 +5.3%, so one year carries the result. Largest fall 31.1%; in the market 584 of 1,049 days; 71 switches. **The scoring was run twice.** The first run (+110.7%, 0.972) used venue candles with a 202-day hole left by the backfill; the hole was found by checking the day count, the backfill was fixed, and this is the result on the repaired data. The pass mark was not changed. Not yet replayed in the exact paper engine. |
| T7 | 2026-11-14 | The instant-trade (OTC) price and the order book disagree by more than the fees, so buying on one and selling on the other pays. | 15 paired samples a minute apart for BTCTMN and USDTTMN: the OTC quote for each side and the order book's best bid and ask read within the same second. One paired look was taken before this entry was written (OTC sell 1.6% below the book bid). | In at least 2 of 15 samples, OTC sell is above the book ask or OTC buy is below the book bid by more than 0.20% (two account fees). | pending |

## Method notes

- T2 to T6 are screens on tables, run by `scripts/edge_screen.py`. Nothing is fitted.
- T2 looks at every watched market, so its bar is t at least 4, not 2.
- T6 trades at the daily close with an assumed 0.10% for half the spread. The rule family (trend on the two largest coins) was chosen in 2026 by someone who knows those coins rose; the trial count does not correct for that.
- The screens use floating point. Anything that passes is replayed in the exact paper engine before it counts.

## Forward record

T6 earned a prospective paper run, which started on 2026-11-14 for BTCUSDT with 1,000 USDT of paper cash:
`gymctl allocate BTCUSDT --vol-target 5 --band 0`, once a day, installed by `scripts/windows/Install-AllocationJournal.ps1`.
Decisions append to `<data>/live/allocation/journal.jsonl` and cannot be re-decided. The first decision was to stay
in USDT (close 68,175 against a 50-day average of 80,495). This record, not the backtest, is the evidence that counts.
