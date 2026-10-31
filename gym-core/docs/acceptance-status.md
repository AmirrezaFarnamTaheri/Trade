# Workstation acceptance progress

Workstream A code and exit evidence are complete for the public-only slice. Longer live observation improves hour coverage but is not a release gate in the master plan. B1 has not started and no API key was used.

## Release gaps

| Criterion | State | Evidence and next action |
| --- | --- | --- |
| Session bars, section 15.1 | Done | `resolution="session"` bars are bounded by merged BLOCK_ALL TradingWindow closures (rule vintage at the bar's time) and Tehran midnight; a closure is its own period. Replay labels gaps inside closures `VENUE_CLOSED`, not `NO_OBSERVATIONS`. |
| DATA-01 | Improved | Padded zoned dates, malformed numeric CLI inputs, non-finite bar observations, invalid unflagged quotes, ranges, unsupported resolutions; LAST on quote history fails explicitly. |
| DATA-02 | Done (public metadata) | The collector stores each complete public Wallex symbol object in the existing as-observed validity history. `metadata_at` returns the point-in-time raw object, interval, source, SQLite version and SHA-256. Missing historical flags stay UNKNOWN. Account-specific fees remain a B1 read-only-account fact. |
| DATA-03 | Improved | Future-only FX is unavailable, never backdated. Engine version `paper-session/5`. |
| DATA-04 | Done (detector) | `domain/units.py` tracks the IRT-per-USDT rate implied by each asset; a 10^k jump (|k| 1..4, 15% tolerance) on at least two assets at once records `UNIT_DISCONTINUITY` and an INFERRED CurrencyUnit BLOCK_ENTRY rule for TMN. Exits and USDT pairs stay allowed; stored rows are unchanged; market moves and single-asset glitches do not trigger. Relabeling derived views under a new unit epoch is not implemented. |
| DATA-05 | Done with source limitation | Quote bars have streaming/batch parity. `gymctl candles` compares internal LAST bars with venue 1min candles. Pre-fix evidence exposed identical same-second public trades being collapsed. After preserving ambiguous identical prints, the post-fix probe had 11/11 BTCUSDT minutes AGREE with no divergence. Source retransmissions remain indistinguishable without venue trade IDs. |
| DATA-06 | Done (close clocks) | `CloseSubscriptions` deterministically merges availability-safe 1min/15min/1h/1day/session close events by timestamp, resolution rank and subscription order. Forming bars remain flagged. Replay and live CLI expose `--subscribe`; the primary `--res` alone drives the current EMA. Event/schedule/regime clocks wait for a strategy that needs them. |
| SIM-01/04 | Done | Latency, lifecycle, quotas, closures and PriceBand locks are nonfills with a reason. Reopening gaps are marked once (`session.reopenings`). The band reference is the first observed mid of the Tehran day, not a venue-published price. |
| SIM-02 | Deferred integration proof | No funded Executor exists. Prove isolation when B is integrated. |
| SIM-03 | Done | Matched-window results retain nominal quote net and use USDT-equivalent for active ranking when point-in-time FX exists. Zero-trade runs remain visible as abstainers and are excluded from active-trading rank. |
| EVAL-01 | Done (shared-engine diagnostic) | Repeatability, midpoint truncation and stream/replay parity include first divergences. Warmup has a passing genuine-prehistory fixture and reports NOT_RUN when unavailable. Cost stress scales observed spread, fees and latency drift at 0/1/1.25/2/3 on the matched fill path; it does not change fills/depth/decisions. |
| REG-01/02/05 | Improved | Scope, precedence, vintage, rollback, CurrencyUnit and PriceBand are executable. |
| REG-07 | Improved | Pair scope and quota work. The FX factor is `STALE_CLOSED` while USDT/IRT is closed in replay, reports, Markets API and UI. External-channel quota reconciliation belongs to the money path. |
| Measured costs, section 15.1 | Done for observed spreads | `gymctl spreads` reports exact-decimal distributions by pair/Tehran hour. The post-fix probe had 3,374 observations, zero excluded and 10 pair/hour groups. Unobserved hours remain absent rather than invented; fee, depth and latency evidence remain separate. |

## Verification evidence

- `uv run pytest -q`: **80 passed**. No new dependency.
- DEMO end-to-end: `gymctl paper BTCUSDT --demo --res 15min --subscribe 1h` produced run `bbcad5a794f2e363`; ranking retained `hold USDT` as an abstainer and diagnostics wrote an evidence report with no FAIL status.
- Earlier live spreads: `D:/GitHub/Trade/data/live/spreads-pre-b1.json`, 1,190 qualified observations, 19 excluded and 10 pair/hour groups; absent hours are explicitly absent.
- Pre-fix candles: `D:/GitHub/Trade/data/live/candle-crosscheck-pre-b1.json`, AGREE 25 / DIVERGENT 1 / NOT_COVERED 4. The 38.91 bps divergence led to the identical-print preservation fix.
- Post-fix interim candles: `D:/GitHub/Trade/data/live/candle-crosscheck-postfix-interim.json`, 11 AGREE / 0 DIVERGENT from `2026-10-31T08:54:00Z` to `09:32:00Z`.
- Post-fix interim spreads: `D:/GitHub/Trade/data/live/spreads-postfix-interim.json`, 3,374 observations / 0 excluded / 10 groups over the same 38-minute window.
## Next slice

B1 may start immediately, in parallel as specified by section 15.1. Executor scaffolding and Fake Venue work need no credential; provisioning and read-only account validation later require a locally stored API key.

Demo observations are not venue-cost evidence. No passing row grants trading authority.
