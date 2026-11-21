# TradingGYM historical replay financial audit

## Decision

The hourly EMA 8/21 lost quote-currency capital in 320 of the 337 markets where it traded during November 14–21, 2026. The five scheduled receipts also contain fills too large for the displayed price level. On this evidence, reject promotion of this configuration to funded execution. The experiment measures one strategy during one market week. Other strategies need their own evidence.

## Population and capital

The live research ledger had five enabled single-symbol jobs and seven disabled jobs at inspection. The enabled jobs all scheduled the same EMA every hour with a seven-day lookback. Adjacent windows share 167 hours. Each replay restarts with fresh cash and strategy state. Combining their P&Ls over time would count the same price movements repeatedly. The five enabled markets represent four underlying assets because BTC is quoted twice.

For the window from November 14 at 22:00 UTC through November 21 at 22:00 UTC (exclusive), the collector had observations for 373 markets. A complete exploratory sweep returned 342 markets with qualified data. Of these, five had zero fills and 337 traded. All 31 remaining markets had no qualifying observations. The five scheduled net amounts matched the sweep to the stored decimal precision.

| Quote currency | Traded | Positive | Negative | Median return | Worst | Best |
|---|---:|---:|---:|---:|---:|---:|
| TMN | 173 | 12 | 161 | −9.73% | −53.80% | +119.62% |
| USDT | 164 | 5 | 159 | −11.15% | −66.65% | +114.11% |

Each market received 1,000 USDT or 300 million TMN independently. The portfolio service has a shared cash book and reservations. The sweep calls the single-market simulator. These returns cannot be added to obtain the return on one funded account. MMT occupied both top spots through its TMN and USDT pairs, so even the two strongest observations share underlying risk.

## Five scheduled receipts

All monetary columns below use the market's quote currency. Each sensitivity changed one input and replayed the same quotes. The entry cap used 25% of available cash per purchase. The separate displayed-size run allowed up to 100% of the visible touch quantity. Neither setting was selected prospectively.

| Market | Original net | Hold base | 25% entry net | Displayed-size net | Original fills larger than touch |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | −53.46 | −69.29 | −13.57 | −23.05 | 5/8 |
| ETHUSDT | −47.45 | −67.11 | −11.97 | −12.53 | 3/4 |
| SOLUSDT | −50.35 | −13.34 | −12.69 | −10.50 | 8/8 |
| BTCTMN | −9,986,232 | −17,846,157 | −2,517,434 | −935,746 | 5/6 |
| USDTTMN | +61,389 | +3,555,300 | +16,314 | +204,412 | 3/3 |

**Exposure.** The original EMA could spend nearly the full cash balance on entry. Reducing the per-entry fraction reduced both the four losses and the one gain, with identical fill counts in that sensitivity. This shows how position size magnified outcomes. It supplies no evidence of an improved signal.

**Execution capacity.** Joining each original fill to its exact market and availability timestamp shows 24 of 29 quantities exceeded the displayed size on their side. One BTCTMN fill was about 7,700 times the displayed quantity. The default simulator credited the whole quantity at the touch. The displayed-size run changed cash deployed, inventory, subsequent orders and sometimes fill counts. It still assumes access to the displayed liquidity. Real queue competition, cancellations, depth, price impact and exchange acknowledgments require separate measurement.

**Loss attribution.** For BTCUSDT, the modeled waterfall was −41.48 directional, −4.28 spread, −7.77 fees and +0.07 latency. ETHUSDT was mainly directional (−40.51). On SOLUSDT, spread alone cost 20.49 USDT and fees cost 7.77 against a 50.35 USDT total loss. For the broader traded universe the median per-market spread debit was 4.87% of starting cash in TMN and 7.53% in USDT. Median directional debits were 2.95% and 2.51%, respectively. Medians of components need not sum to the median return. “Directional” is the simulator's balancing residual after explicit costs. It cannot isolate alpha, beta, basis, timing and marking effects.

**Benchmarks and FX.** Across traded markets, 157 beat holding their base asset, 17 gained in local quote currency, 15 gained in USDT-equivalent value and 12 beat both holding the base and zero USDT-equivalent return. A local cash benchmark gives 13 wins against both base and cash. For USDTTMN the small local gain translated to a 6.16 USDT-equivalent loss. The two boundary FX marks were recorded approximately eight and 37 minutes before the boundaries and carried STALE_CLOSED status. The conversions use mid-prices and cannot establish executable proceeds. The paper service applies the same sizing and cost model to its passive trades. A capped passive result therefore measures a capped purchase.

## Modeling and framework findings

| Priority | Finding and consequence | Disposition |
|---|---|---|
| High | Five independently capitalized single-market replays cannot answer what one portfolio would have earned. Shared cash, cross-pair BTC exposure, currency conversion, correlated drawdowns and simultaneous fills change that answer. | Use the shared-account portfolio path and reconcile booked cash, asset quantities, fees and final liquidation by currency before making a portfolio claim. This audit supplies no shared-account result. |
| High | The default historical touch model systematically exceeded displayed liquidity in these receipts. Flat fees of 0.1% per side and fees in the received asset were modeled. Start-of-window precision and minimum order sizes were unknown in the receipts. | Scheduled jobs can now declare the engine's entry and participation limits. The original five receipts and jobs retain their assumptions. Qualification still needs dated venue rules, actual fee tier, execution reports and fill reconciliation. |
| High | The fixed seven-day jobs produced only 98–106 hourly bars apiece in 168 elapsed hours. EMA periods count observed bars. Closure, missing data and warm-up can produce a materially different clock from a continuously traded hourly model. | Compare genuine closure calendars with missing capture intervals. Use pre-window warm-up and contiguous out-of-sample evaluation for a deployable policy. |
| High | Sweeps previously accepted explicit symbols without observations by silently dropping them. Reusing a larger sweep file for a smaller universe could mix an old universe's rows with the new market count. | Missing requested symbols and out-of-universe cached results now raise explicit errors. |
| High | Sweep attempts with different fees or starting sizes previously had the same trial identity. Historical experiment counts may understate model selection. | New non-default cost and capital variants receive distinct identities. Old ledgers alone cannot reconstruct undocumented variants. Reconcile archived sweep inputs before a selection-adjusted claim. |
| Medium | A final bid mark values inventory at the displayed price. A fee-adjusted liquidation estimate still assumes sufficient depth. The difference between these estimates and settled cash matters on thin books. | Keep booked cash, marked equity and estimated net liquidation distinct. Stress the residual position through executable levels and closures. |
| Medium | The sweep ranked absolute USDT-equivalent amounts across unequal starting values and called a zero USDT-equivalent benchmark “hold cash.” Missing comparison values appeared as numeric zeros. | Corrected the benchmark label, missing-value display and hardcoded capital caption. Use within-currency percentage returns for cross-market comparisons. |
| High | One realized week gives one common market regime. An hourly restart is heavily dependent on prior runs. Markets share assets, venue outages, liquidity and FX. A Benjamini–Hochberg adjustment across strategy/resolution cells does not correct the independence assumption of the underlying cross-market sign test. | Reserve disjoint future time blocks and freeze universe, execution assumptions, benchmark and sizing in advance. Include failures, delistings and idle markets in the coverage denominator. |

The original run IDs were 68bc3292d508c04e (BTCUSDT), 460902c6cad87718 (ETHUSDT), f9fa8c30ab208ad7 (SOLUSDT), 5ef62afe48acbbc0 (BTCTMN) and 71ba3147b0373fa9 (USDTTMN). The underlying receipts are in `data/live/runs`. The complete compact output is `data/live/sweeps/2026-11-21-hourly-ema-universe.sqlite3`. It can be inspected using `gymctl --data ../data paper-sweep --from 2026-11-14T22:00:00Z --to 2026-11-21T22:00:00Z --res 1h --strategies ema-trend --fee 0.001 --out ../data/live/sweeps/2026-11-21-hourly-ema-universe.sqlite3 --report` from `gym-core`.
