# Workstation acceptance progress

Workstream A is not release-complete. Passing tests and CLI probes prove only the cases they cover. B1 has not started.

## Release gaps

| Criterion | State | Evidence and next action |
| --- | --- | --- |
| Session bars, section 15.1 | Done | `resolution="session"` bars are bounded by merged BLOCK_ALL TradingWindow closures (rule vintage at the bar's time) and Tehran midnight; a closure is its own period. Replay labels gaps inside closures `VENUE_CLOSED`, not `NO_OBSERVATIONS`. |
| DATA-01 | Improved | Padded zoned dates, malformed numeric CLI inputs, non-finite bar observations, invalid unflagged quotes, ranges, unsupported resolutions; LAST on quote history fails explicitly. |
| DATA-02 | Partial | Precision has historical lookup; historical fee and asset-flag availability remain incomplete. |
| DATA-03 | Improved | Future-only FX is unavailable, never backdated. Engine version `paper-session/3`. |
| DATA-04 | Done (detector) | `domain/units.py` tracks the IRT-per-USDT rate implied by each asset; a 10^k jump (|k| 1..4, 15% tolerance) on at least two assets at once records `UNIT_DISCONTINUITY` and an INFERRED CurrencyUnit BLOCK_ENTRY rule for TMN. Exits and USDT pairs stay allowed; stored rows are unchanged; market moves and single-asset glitches do not trigger. Relabeling derived views under a new unit epoch is not implemented. |
| DATA-05 | Partial | Quote bars have streaming/batch parity. `gymctl candles` compares internal LAST bars (venue event time) with venue 1min candles: AGREE / DIVERGENT / MISSING_INTERNAL / MISSING_VENUE / NOT_COVERED; `--record` writes `CROSS_FEED_DIVERGENCE`. The collector refreshes the last two hours of candles every 5 minutes. Live: 3 of 3 compared BTCUSDT minutes agreed. Venue daily candles answer `no_data`. |
| DATA-06 | Partial | Closed versus flagged forming bars are tested. Multi-timeframe subscriptions need coverage. |
| SIM-01/04 | Done | Latency, lifecycle, quotas, closures and PriceBand locks are nonfills with a reason. Reopening gaps are marked once (`session.reopenings`). The band reference is the first observed mid of the Tehran day, not a venue-published price. |
| SIM-02 | Deferred integration proof | No funded Executor exists. Prove isolation when B is integrated. |
| SIM-03 | Partial | Matched-window baselines exist. No ranking surface yet. |
| EVAL-01 | Partial | Repeatability, truncation and shared-engine parity exist. Warmup may be NOT_RUN. Stress changes fees only. |
| REG-01/02/05 | Partial | Scope, precedence, vintage, rollback; CurrencyUnit now executable. PriceBand is still informational. |
| REG-07 | Improved | Pair scope and quota work. The FX factor is `STALE_CLOSED` while USDT/IRT is closed: in replay results, reports, the Markets API and the UI badge. External-channel quota reconciliation belongs to the money path. |
| Measured costs, section 15.1 | Partial | `gymctl spreads` reports exact-decimal distributions by pair/Tehran hour; only a few minutes of real data exist. Fee, depth and latency evidence are separate. |

## Verification evidence

- `uv run pytest -q`: **73 passed**. No new dependency.
- `gymctl --data D:/GitHub/Trade/data candles BTCUSDT --from 2026-10-30T21:00:00Z --to 2026-10-30T21:20:00Z --fetch`:
  fetched 21 real venue candles; `AGREE 3` (the only minutes the collector observed).
- Earlier: `gymctl spreads` on the live store (105 observations, Tehran hour 00 only); demo replay and evidence report.

## Next blocking slice

A long real collection run (full Tehran day) for
spreads and the candle cross-check, then the remaining DATA-02/06 and EVAL-01 items. B1 waits on that.

Demo observations are not venue-cost evidence. No passing row grants trading authority.
