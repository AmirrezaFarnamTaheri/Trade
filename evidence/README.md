# Evidence Directory

All quantitative research reports, live forward-validation artifacts, and historical audit receipts live under `evidence/`, organized by role rather than flat date prefixes.

> **Authority invariant:** `TradingGYMExecutor` remains **`DISARMED / NOT CERTIFIED`** (`$0` funded-loss budget). Paper and replay results cannot authorize capital; see [docs/2027-02-08-checkpoint-protocol.md](../docs/2027-02-08-checkpoint-protocol.md) and [gym-core/docs/trial-log.md](../gym-core/docs/trial-log.md).

## Directory Map

| Path | Contents |
| --- | --- |
| [research-dashboard.html](research-dashboard.html) | 100% offline, zero-CDN 11-panel interactive HTML5 research cockpit (rebuilt via `gym-core/scripts/build_research_dashboard.py`) |
| [studies/SUMMARY.md](studies/SUMMARY.md) | **Start here** — executive synthesis of all strictly causal quantitative studies, v1/v2/v3 champion evolution, verified winners, and retired dead ends |
| [studies/core-ensemble/](studies/core-ensemble/) | **Track 1:** `1d` slow core (`S1 + S5 + ADMM`), 2nd-order acceleration, metals reserve, factor/2×2 attribution, and orthogonal alpha audits |
| [studies/ignition-and-ml/](studies/ignition-and-ml/) | **Track 2:** `2h` rare momentum ignition, pure-NumPy walk-forward GRUs (`GRU6`/`GRU8`/`GRU11`), conformal/DD governor, leverage/shorts, and Unified v2 Champion verification |
| [studies/execution-and-venues/](studies/execution-and-venues/) | **Track 3:** Experiment 0 execution ceiling, live Wallex vs. Nobitex L1/L2 spread audits, `SIDE_ASYMMETRIC_ROUTER`, Joint Single-ADMM cross-sleeve netting, and Nobitex vs. Wallex margin economics |
| [studies/v3-adaptive-engine/](studies/v3-adaptive-engine/) | **Track 4:** v3 Dynamic Instrument Resolver, `MultiHorizonBook` Adaptive Engine (`F1`–`F6`), Optimal Position-Closing (`E1`–`E4`), Nonlinear Bellman Stopping V2 (`E3_V2`), and Bear-Regime & `0.5h`/`1h` Timeframe studies |
| [forward/](forward/) | Frozen prospective registrations, live untouched forward paper scoreboards (`v1` & `v2`), and read-only operational health snapshot |
| [archive/](archive/) | Chronological historical receipts preserved verbatim for audit provenance (`executor/`, `early-trials/`, `audits/`) |
| [INDEX.json](INDEX.json) | SHA-256 manifest for out-of-repo `.pi/` receipts (`uv run --no-sync python scripts/evidence_index.py --verify`; enforced by `tests/test_regressions_safety_boundaries.py`) |

## Live Forward-Validation & Data Freshness Tasks (`forward/`)

All forward shadow journals and hourly refresh tasks run read-only on Windows Task Scheduler (`scripts/windows/Install-ChampionJournals.ps1`) against untouched forward market observations:

- [s1-s5-leader-registration.json](forward/s1-s5-leader-registration.json) — Standalone `BASE_13_S1_S5` daily prospective registration (`03:55` daily).
- [champion-v1-registration.json](forward/champion-v1-registration.json) & [champion-v1-forward-score.json](forward/champion-v1-forward-score.json) — Frozen **v1 Champion** (`70% BASE_13_S1_S5 (XAUT) + 30% 2h GRU-Ignition`, every `2h`).
- [champion-v2-registration.json](forward/champion-v2-registration.json) & [champion-v2-forward-score.json](forward/champion-v2-forward-score.json) — Frozen parallel **v2 Champion** (`1d ACCEL_BLEND_20 + 11A Metals Reserve + Joint ADMM + Twin-Phase 2h GRU11 Path-PnL + Conformal/DD`, hourly).
- `TradingGYM Hourly Candle Refresh` (`gym-core/scripts/refresh_hourly_candles.py`) — Hourly `1h` OHLCV backfill across all 21 champion/ignition/metals symbols ahead of forward journal runs.
- [operational-health.json](forward/operational-health.json) — Read-only collector, 20-symbol Nobitex recorder, forward journal, and frozen-model SHA-256 watchdog receipt.

## Historical Archive (`archive/`)

- `archive/executor/` — 2026-11-16 native Rust executor authority reviews, checkpoint scale verification (`1M` rows), order admission/effects/settlement, and review branch records.
- `archive/early-trials/` — 2026-11-16..2026-11-19 early hypothesis receipts cited by [gym-core/docs/trial-log.md](../gym-core/docs/trial-log.md) and [evidence-and-sampling-contract.md](../gym-core/docs/evidence-and-sampling-contract.md).
- `archive/audits/` — 2026-11-21..2026-11-24 sprint receipts, performance/hygiene audits, historical replay financial audit, peer contract comparison, and instant gate packets.
