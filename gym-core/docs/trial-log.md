# Trial log

One question governs every entry: is there a net edge on Wallex after costs, against holding USDT?

Each hypothesis is written here with its data and pass mark **before** it is run. The result is added afterwards and
the pass mark is never edited. A new idea is a new entry, so the count of things tried stays honest.

Costs used throughout, per side: the account rate read from `/v1/account/fee` (0.10%), and the published level-1
rates from `/v2/structured-fee` (Toman markets 0.25% maker, 0.30% taker; USDT markets 0.10% maker, 0.13% taker).

| ID | Registered | Hypothesis | Data | Pass mark | Result |
| --- | --- | --- | --- | --- | --- |
| T1 | 2026-11-13 | Intraday mean reversion on USDTTMN beats holding USDT (Version 1; 12 settings per fee rate). | 1-minute venue candles, 1,096 sessions before 2026; 308 later sessions held out. | Deflated Sharpe probability at least 0.95 on the ranking sessions, then the held-out sessions scored once. | **FAIL** (2026-11-14). Best 0.001. Held-out sessions not scored. `scripts/usdttmn_v1.py --bars`. |
| T2 | 2026-11-14 | In some Wallex market, resting orders on both sides earn more than they cost. | Recorded quotes and trades, all watched markets, from 2026-10-30. | A market qualifies only if all hold: median spread at least 0.40%; at least 50 trades a day; median touch at least 50 USDT; and the maker's result per trade, measured against the mid five minutes later and charged two maker fees, has a positive mean with t at least 4 on at least 500 trades over at least 5 days. | pending |
| T3 | 2026-11-14 | The USDT/Toman rate implied by BTC or ETH (coin/TMN divided by coin/USDT) departs from USDTTMN by more than three taker fees. | Recorded quotes for the three markets of each triangle, in the USDTTMN session, on a one-minute grid. | The gap at executable prices, after 0.30% in fees, is positive in at least 1% of minutes and on at least 5 days. | pending |
| T4 | 2026-11-14 | Holding BTCUSDT or ETHUSDT only while the daily close is above its moving average beats holding USDT (averages of 50, 100 and 200 days; 6 settings). | Venue daily candles; settings ranked on days before 2024-01-01. | Deflated Sharpe probability at least 0.95 on the ranking days; then days from 2024-01-01 scored once for the best setting, where the probability that its Sharpe is above zero must be at least 0.90. | pending |
| T5 | 2026-11-14 | The zero-fee market (USDSUSDT) moves enough inside a day to pay for crossing its spread. | Recorded quotes from 2026-10-30. | Median over days of the best same-day round trip at the touch (perfect foresight, no fee) at least 0.20%, with median touch at least 100 USDT. This is an upper bound: a pass only earns a real rule its own entry. | pending |

## Method notes

- T2 to T5 are screens on tables, run by `scripts/edge_screen.py`. Nothing is fitted.
- T2 looks at every watched market, so its bar is t at least 4, not 2.
- The screens use floating point. Anything that passes is replayed in the exact paper engine before it counts.
