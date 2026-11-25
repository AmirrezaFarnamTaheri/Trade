# Quantitative Experiments & Live Forward Journals (`gym.services.experiments`)

All strictly causal offline research studies, shared simulation utilities, live read-only forward shadow journals, and the offline HTML5 research dashboard live in this package. Pure financial math resides in `gym.domain`; this package coordinates SQLite candle loading, walk-forward training, and report generation.

## Shared Building Blocks

| Module | Role |
| --- | --- |
| `admm_helpers.py` | Dated return index, shrunk horizon covariance, daily breadth extraction, and canonical `S1+S5` ADMM weight solver |
| `unified_book_helpers.py` | Shared `WALKFORWARD_FOLDS`, causal `resolve_bar_prices`, twin-phase `latest_signal_date`, and window/annual NAV aggregation |
| `gru_engine.py` | Pure-NumPy purged walk-forward multi-seed `EnsembleGRU` classifier & regressor |
| `bar_parity.py` | Live vs. historical bar parity & freshness audit helpers |

## Live Forward Shadow Journals & Observability (Read-Only, `DISARMED`)

| Module | CLI Runner (`gym-core/scripts/`) | Output |
| --- | --- | --- |
| `leader_forward_journal.py` | `record_leader_journal.py` | Daily `BASE_13_S1_S5` shadow journal (`03:55` local) |
| `champion_forward_journal.py` | `record_champion_journal.py` | Frozen v1 Champion shadow journal (every `2h`) |
| `champion_v2_journal.py` | `record_champion_v2_journal.py` | Frozen parallel v2 Champion shadow journal (hourly) |
| `operational_health.py` | `check_operational_health.py` | Collector, Nobitex recorder, journal, and SHA-256 watchdog |
| `research_dashboard.py` | `build_research_dashboard.py` | 11-panel offline HTML5 cockpit (`evidence/research-dashboard.html`) |

## Quantitative Study Tracks (Mapped to `evidence/studies/`)

1. **Track 1 — Core Ensemble (`evidence/studies/core-ensemble/`):**
   `ensemble_study.py`, `leader_deep_dive.py`, `sleeve_attribution_study.py`, `expansion_and_margin_study.py`, `family_and_timeframe_study.py`, `orthogonal_alpha_study.py`, `higher_order_and_sparse_study.py`, `core_engine_ablation_study.py`
2. **Track 2 — Momentum Ignition & ML (`evidence/studies/ignition-and-ml/`):**
   `ignition_validation_study.py`, `ignition_expansion_study.py`, `short_and_leverage_study.py`, `gru_prototypes_study.py`, `ignition_upgrade_ablation_study.py`, `champion_v2_verification.py`
3. **Track 3 — Execution & Venues (`evidence/studies/execution-and-venues/`):**
   `venue_execution_audit.py`, `smart_execution_sim.py`, `diffusion_and_netting_study.py`, `venue_leverage_study.py`
4. **Track 4 — v3 Adaptive Engine, Optimal Closing & Bear-Regime (`evidence/studies/v3-adaptive-engine/`):**
   `dynamic_resolver_study.py` → `multi_horizon_adaptive_study.py` → `optimal_exit_study.py` → `bellman_resurrection_study.py` → `bear_regime_and_timeframe_study.py` → `convex_bear_cross_asset_study.py`
