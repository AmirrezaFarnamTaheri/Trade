# Evidence Directory Index

`INDEX.json` holds a SHA-256 for every acceptance receipt, benchmark and study output that the docs cite under
`.pi/`. The receipts themselves stay out of the repository because they can hold host details. Anyone given the
receipts can check them with `uv run --no-sync python scripts/evidence_index.py --verify` (from `gym-core/`);
`tests/test_regressions_safety_boundaries.py` fails when a doc cites a path that has no digest here.

## Active Research & Forward-Validation Artifacts (2026-11-24 / 2026-11-25)

### Interactive Offline Cockpit
- [2026-11-25-research-dashboard.html](2026-11-25-research-dashboard.html) — 100% offline, zero-CDN interactive HTML5 dashboard covering all 8 quantitative panels and live forward tracking.

### Frozen Prospective Registrations & Operational Status (`DISARMED`)
- [2026-11-25-champion-ensemble-registration.json](2026-11-25-champion-ensemble-registration.json) — Frozen v1 Champion (`70% BASE_13_S1_S5 (XAUT) + 30% 2h GRU-Ignition`, SHA-256 locked).
- [2026-11-25-champion-forward-score.json](2026-11-25-champion-forward-score.json) — Live untouched forward paper NAV, live spread telemetry, and sequential `e_process`.
- [2026-11-24-s1-s5-prospective-registration.json](2026-11-24-s1-s5-prospective-registration.json) — Standalone `BASE_13_S1_S5` daily prospective registration.
- [2026-11-25-operational-health.json](2026-11-25-operational-health.json) — Read-only collector, 20-symbol Nobitex recorder, journal, and model health snapshot.

### Core Quantitative Studies (Strictly Causal, Zero Lookahead)
- [2026-11-24-first-ensemble-experiment-report.md](2026-11-24-first-ensemble-experiment-report.md) — First 1,638-day ensemble & ML-veto ablation establishing `S1 + S5 + ADMM`.
- [2026-11-24-leader-deep-dive-report.md](2026-11-24-leader-deep-dive-report.md) — `S2` hysteresis retirement, OLS BTC/Gold factor attribution (`+27.65%/yr` alpha), 2×2 entry/exit decomposition, and causal BUY/SELL execution asymmetry.
- [2026-11-24-venue-execution-cost-report.md](2026-11-24-venue-execution-cost-report.md) — Matched live Wallex L1 vs. Nobitex (`-30%`) spread & depth audit (`+6.2` to `+12.0 bps/leg` saving).
- [2026-11-25-smart-execution-report.md](2026-11-25-smart-execution-report.md) — Walked 5-level L2 depth `$250` order audit (`SIDE_ASYMMETRIC_ROUTER`: `+8.1` to `+21.9 bps/leg` saving across `4/4` live pairs).
- [2026-11-24-family-and-timeframes-report.md](2026-11-24-family-and-timeframes-report.md) — Zero-lookahead `2h`/`3h`/`6h` crash-breaker audit (retired), family-differentiated `33`-asset test, and rare momentum ignition discovery.
- [2026-11-24-ignition-validation-report.md](2026-11-24-ignition-validation-report.md) & [2026-11-24-ignition-expansion-report.md](2026-11-24-ignition-expansion-report.md) — Live-spread + `+1h` clock-shift validation, shared-ledger `70/30` blend (`+37%–+51%` Sharpe lift, `-29%` MaxDD), and `15m`/`30m` sub-hourly floor audit.
- [2026-11-24-short-and-leverage-report.md](2026-11-24-short-and-leverage-report.md) — Event-scoped `1.5×`/`2.0×` leverage vs. `2h` short ignition under exact Wallex `0.015%/4h` borrow and intra-bar liquidations.
- [2026-11-24-gru-prototypes-report.md](2026-11-24-gru-prototypes-report.md) — Pure-NumPy purged walk-forward `GRU-Vol`, `GRU-Ignition` (`AUC 0.558`, dynamic `0.5×/1.0×/1.5×` sizer), and `GRU-Exec`.
- [2026-11-25-orthogonal-alpha-report.md](2026-11-25-orthogonal-alpha-report.md) — Orthogonal audit: `2h` flush rebound & dead-cat short (retired), covariance-only `GRU-Vol` (retired), `PAXG` vs `XAUT` (`XAUT` wins), standalone macro commodities (watchlist).
- [2026-11-25-higher-order-and-sparse-report.md](2026-11-25-higher-order-and-sparse-report.md) — 2nd-order trend acceleration (`BASE_13` `1.011 → 1.116`, `GRU8` `+33% → +45.5%`), tiered sparse `18 → 38` markets (`+1h` fragility caught on meme satellites), walk-forward vs. static sleeve weighting, and `1d` structural bear-laggard shorts (`+22.4%` bear year zero-borrow vs. `-33.9%` full-period Wallex margin).
- [2026-11-25-core-engine-ablation-report.md](2026-11-25-core-engine-ablation-report.md) — Track I `1d` ablations: `ACCEL_BLEND_20` (`SR 1.116`) beat Savitzky–Golay (`0.957–0.962`), Path-Efficiency IC (`0.940`), and `HRP` (`0.591–0.660`); multi-issuer defensive metals reserve added modest positive lift (`1.011 → 1.023`).
- [2026-11-25-ignition-upgrade-ablation-report.md](2026-11-25-ignition-upgrade-ablation-report.md) — Track II `2h` ablations: Conformal + 5% DD leverage governor (`SR 0.811 → 0.857` NBX16, `0.611 → 0.670` WLX25, MaxDD `-24%` to `-29%`), 11-feat Path-PnL GRU (`SR 0.822 / 0.636`, MaxDD `10.6%`), and `50/50` twin-phase book (`IGN38_TIERED` `SR 0.775 / 0.535`) all beat baselines; two-tranche partial profit-lock and absorption throttle retired.
- [2026-11-25-diffusion-and-netting-report.md](2026-11-25-diffusion-and-netting-report.md) — Track III ablations: Joint Single-ADMM cross-sleeve netting beat post-hoc `70/30` on both venues (`SR 0.650 → 0.685` NBX16, `0.554 → 0.582` WLX25, `-21%` Wallex fills); live 15-pair Nobitex↔Wallex dislocation audit confirmed `+15–95 bps` real entry-guard/exit-rebate opportunities; `2h` lead-lag diffusion retired.

### Historical / Superseded Receipts
- `2026-11-16-*` through `2026-11-22-*`: Earlier executor authority drills, daily-trend replays, and audit dispositions retained for chronological provenance.
- `2026-11-24-expansion-and-margin-report.md`: Retained with explicit retraction notice on `EXP_B2`/`EXP_B3` (pre-causality-fix intraday crash breaker; superseded by `2026-11-24-family-and-timeframes-report.md`).
