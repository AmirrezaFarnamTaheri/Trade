# Workstation acceptance progress

Public data, paper simulation, merged PRs and a running Windows service do **not** prove funded safety.
B/C remain **IN PROGRESS / NOT CERTIFIED**, and the application remains **DISARMED**.
No funded submission, certified venue stop, hung-service containment or independent-machine recovery is claimed.

## Current implementation and evidence — 2026-11-03

- **B1:** authenticated independent STOP listener, SCM-pinned clients, explicit OS-derived operator/user-logon binding, protected helpers, separate elevated-admin provisioning and service-context DPAPI custody are implemented. `gym-account-read balances|fees|known-client-order <id>` now has a service-owned, fixed-origin, bounded WinHTTP GET path. Its output is **RAW_UNPARSED**, not a normalized money posting. Key permissions remain **UNVERIFIED**; a successful GET is not proof that a key cannot trade. Explicit SCM recovery-only provisioning preserves ledger history and rejects account reads. These new service paths have build/unit checks, not a successful installed-host/live-venue drill.
- **B2:** the real durable order journal now composes fake approval/preflight, atomic reservations, first-byte retry rules, unknown-order holds, STOP gates, partial fills, received-asset fees and restart/reconciliation. Regressions cover zero-fill cancellation, disjoint protective-sale credits during an unknown buy, idempotent settlement and unexplained-credit refusal. The separate actual Python R0 AppContainer launcher, protected runtime/public-snapshot packaging and real-child probes are implemented. Installed-worker isolation remains unverified; an ordinary account named `worker` is not SEC-02 proof.
- **B3:** the previous verified Windows-to-WSL restore remains same-hardware portability evidence only. DPAPI ciphertext is host/account bound: restored credential metadata needs explicit reprovisioning, not a copied plaintext key. Recovery-only startup fixes the missing/nonportable-ciphertext bootstrap; its installed-host drill remains unverified.
- **D/local research:** four version-pinned strategies, matched comparisons, higher-timeframe/reference inputs, closure-aware periods, paper market/expiry models, persistent hypotheses/shadow positions, retry-aware scheduled research/alerts, and a fixed three-tool read-only MCP stdio interface are implemented. These are limited **PAPER_ONLY/R0** features, not an assertion that every original D backlog item is accepted.
- **UI:** all nine destinations, a real paired comparison, persisted inputs, EN/FA RTL, light/dark, keyboard focus and 1440px/390px overflow were exercised in actual Edge. Screenshots/report: `.pi/ui-verification/`. The user's reference image is not a generated test artifact.
- **Verified current local regression:** **490 Python passed, 5 skipped, 39 subtests passed** (36.71 s); the complete Rust workspace test command also exited **0**, including the new custody/read/recovery/worker slices. The five Windows symlink checks skip where the OS cannot create symlinks. This is unit/simulation/build evidence, not installed-service, real-worker-boundary or funded certification.

The optional trusted-host model gateway is now included: Pi-backed provider/OAuth catalogs, environment-key rotation and portable presets, with **21 native SDK tests passed / 1 Windows symlink-privilege skip** in the canonical checkout. It remains disabled by default, outside R0, with no trading tools or account attachments. Live OAuth/entitlements and paid model requests were not exercised.

### Actual paper evidence and capital decision

The public BTCUSDT store has **3,152 observations over 50.736 elapsed hours** on three calendar dates, with **11.5-hour and 35-hour gaps**. That is **not** a continuous multi-day collection or paper session. The only older saved run was a three-minute replay, not a completed live session. No missing interval was filled with synthetic observations.

Two genuinely observed windows were replayed with identical data/decision snapshots, 1-minute decisions, 1,000 USDT per independent account, 0.1% modeled fee per side, and the existing hold-cash/hold-BTC baselines. All eight runs passed repeatability, midpoint lookahead, streaming/replay and warmup diagnostics (shared engine, not an independent oracle).

| Strategy | Oct 31 08:42–10:15 UTC net USDT | Nov 1 21:18–23:53 UTC net USDT |
| --- | ---: | ---: |
| EMA trend, 2/5 | -18.21265924 | -28.10436819 |
| SMA reversion, 5/50 bps | 0 (no trades; abstainer) | 0 (no trades; abstainer) |
| EMA with 15-minute confirmation, 2/5 | -12.17713545 | -24.03851159 |
| Relative momentum, 5 / ETHUSDT | -42.28850413 | -57.59977897 |
| Hold BTC baseline | -1.22205210 | 1.57382639 |
| Hold USDT baseline | 0 | 0 |

All eight immutable decisions are **NONE, full-loss ceiling 0 USDT**, never execution authority. Machine reports: `.pi/paper-collection-coverage.json` and `.pi/observed-window-evidence.json`; per-run evidence and decisions are in `data/live/runs/`. Short, dependent in-sample windows do not justify promotion or real capital.

## Workstream B offline exit evidence (2026-11-02)

- **B2:** seeded Fake Venue (`executor/exec-core/src/fake_venue.rs`, 12 fixtures
  incl. lost ack, reset-after-write, cancel/fill race, partial cancel, delayed and
  expired unblock, unknown status) drives the real order/reservation model.
  `cargo run -p exec-svc --bin gym-chaos -- data/chaos/report.json` → 12×500 seeds,
  0 invariant violations; unresolved cases stay frozen with an incident. Health
  shows the report. SEC-02 sandboxed-worker probe still needs the installed B1
  service on the operator host.
- **B3:** `gymctl restore-backup` (no-overwrite, verified, DISARMED receipt) and
  `gymctl update-check` (refuses unknown orders, unprotected positions, damaged
  ledger).
- **B3 cross-OS restore (2026-11-02):** a 100-event ledger built on Windows with the
  real `exec-store` schema was backed up on Windows, then restored with
  `gymctl restore-backup` inside WSL2 Ubuntu (Linux 6.18, Python 3.13) from a clean
  `git archive` install with no Windows files or keys. The receipt matched
  sequence 100 and head `79b6b3d1…59d2b`; an independent Linux chain check agreed, and a
  second restore to the same path was refused. WSL runs on the same hardware, so
  this proves portability, not hardware loss; repeat on a separate machine when
  one exists.

## Workstream C development status (2026-11-01)

| Epic | Latest draft | Implemented in code | Still missing for release |
| --- | --- | --- | --- |
| C1 | #14 | Bounded VenueFacts and external-observation journals; interactive-user authenticated read-only client; separate service-owned WinHTTP GET/provisioning code | Installed service reads and permission verification; normalized service observation integration; real pagination/status/exposure probes and validated operator budget/provenance |
| C2 | #15 | Exact-decimal offline tickets; durable fake approvals/reservations/first-byte rules/received-asset fee reconciliation and restart tests | Real trusted-path T1 approvals, funded identity and venue submission/cancel/reconcile transport; assisted conversion and actual-versus-modeled costs |
| C3 | #16 | Offline, non-executable Exit Guard and reopening veto policy; epoch and unknown-order checks | Certified protective venue stops, real Exit Guard and independently verified funded Autopilot with capped/session-reconciled operations |

**Security:** none of the C drafts authorize a new money path. All C outputs
are advisory, with `funded_authority=false`, until the real installed B1/B2
boundaries and live venue acceptance are completed.



## Release gaps

| Criterion | State | Evidence and next action |
| --- | --- | --- |
| Session bars, section 15.1 | Done | `resolution="session"` bars are bounded by merged BLOCK_ALL TradingWindow closures (rule vintage at the bar's time) and Tehran midnight; a closure is its own period. Replay labels gaps inside closures `VENUE_CLOSED`, not `NO_OBSERVATIONS`. |
| DATA-01 | Improved | Padded zoned dates, malformed numeric CLI inputs, non-finite bar observations, invalid unflagged quotes, ranges, unsupported resolutions; LAST on quote history fails explicitly. |
| DATA-02 | Done (public metadata) | The collector stores each complete public Wallex symbol object in the existing as-observed validity history. `metadata_at` returns the point-in-time raw object, interval, source, SQLite version and SHA-256. Missing historical flags stay UNKNOWN. Account-specific fees remain a B1 read-only-account fact. |
| DATA-03 | Improved | Future-only FX is unavailable, never backdated. Engine version `paper-session/6`. |
| DATA-04 | Done (detector) | `domain/units.py` tracks the IRT-per-USDT rate implied by each asset; a 10^k jump (|k| 1..4, 15% tolerance) on at least two assets at once records `UNIT_DISCONTINUITY` and an INFERRED CurrencyUnit BLOCK_ENTRY rule for TMN. Exits and USDT pairs stay allowed; stored rows are unchanged; market moves and single-asset glitches do not trigger. Relabeling derived views under a new unit epoch is not implemented. |
| DATA-05 | Done with source limitation | Quote bars have streaming/batch parity. `gymctl candles` compares internal LAST bars with venue 1min candles. Pre-fix evidence exposed identical same-second public trades being collapsed. After preserving ambiguous identical prints, the post-fix probe had 11/11 BTCUSDT minutes AGREE with no divergence. Source retransmissions remain indistinguishable without venue trade IDs. |
| DATA-06 | Done (close clocks) | `CloseSubscriptions` deterministically merges availability-safe 1min/15min/1h/1day/session close events by timestamp, resolution rank and subscription order. Forming bars remain flagged. Replay and live CLI expose `--subscribe`; the primary `--res` alone drives the current EMA. Event/schedule/regime clocks wait for a strategy that needs them. |
| SIM-01/04 | Done | Latency, lifecycle, quotas, closures and PriceBand locks are nonfills with a reason. Reopening gaps are marked once (`session.reopenings`). The band reference is the first observed mid of the Tehran day, not a venue-published price. |
| SIM-02 | Not certified | Read-only Windows service and durable fake execution exist; neither proves the actual research-worker isolation or a funded execution boundary. |
| SIM-03 | Done | Matched-window results retain nominal quote net and use USDT-equivalent for active ranking when point-in-time FX exists. Zero-trade runs remain visible as abstainers and are excluded from active-trading rank. |
| EVAL-01 | Done (shared-engine diagnostic) | Repeatability, midpoint truncation and stream/replay parity include first divergences. Warmup has a passing genuine-prehistory fixture and reports NOT_RUN when unavailable. Cost stress scales observed spread, fees and latency drift at 0/1/1.25/2/3 on the matched fill path; it does not change fills/depth/decisions. |
| REG-01/02/05 | Improved | Scope, precedence, vintage, rollback, CurrencyUnit and PriceBand are executable. |
| REG-07 | Improved | Pair scope and quota work. The FX factor is `STALE_CLOSED` while USDT/IRT is closed in replay, reports, Markets API and UI. External-channel quota reconciliation belongs to the money path. |
| Measured costs, section 15.1 | Done for observed spreads | `gymctl spreads` reports exact-decimal distributions by pair/Tehran hour. The post-fix probe had 3,374 observations, zero excluded and 10 pair/hour groups. Unobserved hours remain absent rather than invented; fee, depth and latency evidence remain separate. |

## Historical verification evidence (before the current slice)

- `uv run pytest -q`: **80 passed**. No new dependency.
- DEMO end-to-end: `gymctl paper BTCUSDT --demo --res 15min --subscribe 1h` produced run `bbcad5a794f2e363`; ranking retained `hold USDT` as an abstainer and diagnostics wrote an evidence report with no FAIL status.
- Earlier live spreads: `D:/GitHub/Trade/data/live/spreads-pre-b1.json`, 1,190 qualified observations, 19 excluded and 10 pair/hour groups; absent hours are explicitly absent.
- Pre-fix candles: `D:/GitHub/Trade/data/live/candle-crosscheck-pre-b1.json`, AGREE 25 / DIVERGENT 1 / NOT_COVERED 4. The 38.91 bps divergence led to the identical-print preservation fix.
- Post-fix interim candles: `D:/GitHub/Trade/data/live/candle-crosscheck-postfix-interim.json`, 11 AGREE / 0 DIVERGENT from `2026-10-31T08:54:00Z` to `09:32:00Z`.
- Post-fix interim spreads: `D:/GitHub/Trade/data/live/spreads-postfix-interim.json`, 3,374 observations / 0 excluded / 10 groups over the same 38-minute window.
## Next acceptance gates

Finish and verify the real sandboxed R0 worker, then perform an explicitly authorized installed-host read-only service/recovery drill with the chosen human operator logon. T1/funded venue transport is still missing code, not just missing live evidence. No funded probe may run without an explicit budget, suitable key permissions and the original capability/protection gates. A separate-machine restore and a genuine uninterrupted multi-day collection/session also remain outstanding.

Demo observations are not venue-cost evidence. No passing row grants trading authority.
