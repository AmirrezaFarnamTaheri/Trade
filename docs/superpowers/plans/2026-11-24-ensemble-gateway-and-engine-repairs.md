# Uncorrelated Ensemble, ML Meta-Gateway & Engine Repairs Implementation Plan

> **For agentic workers:** Execute inline sequentially in the primary agent (no subagents per workspace rule). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair all five verified engine/accounting/bottleneck defects caught in [2026-11-24-ensemble-gateway-design-review.md](../specs/2026-11-24-ensemble-gateway-design-review.md) and execute the First Paper Experiment (Wallex spot slow sleeves `S1/S2/S5`, fixed controls, adaptive vote, and veto-only calibrated `L2 LogisticRegression` challenger on a self-financing shared ledger).

**Architecture:** First repair and independently verify the measuring instrument (`convex_optimizer.py`, `async_covariance.py`, `microstructure.py`, `statistical_inference.py`, `passive_execution.py`, `instant_gate_check.py`). Second build the isolated domain modules (`timeframe_panel.py`, `strategy_sleeves.py`, `meta_gateway.py`) and end-to-end evaluator (`evaluate_ensemble_gateway.py`) with synthetic null/planted falsification controls, bar-source parity sensitivity, and strict self-financing cash/inventory accounting.

**Tech Stack:** Python 3.11 (`gym-core/.venv`), `Decimal` exact money math, `numpy 2.4.6`, `scipy 1.17.1`, `scikit-learn 1.9.1`, SQLite read-only (`data/live/market.db`), `pytest`, `ruff`, `scripts/complexity_ratchet.py`.

## Global Constraints

- `TradingGYMExecutor` remains `DISARMED / NOT CERTIFIED` with `$0` funded-loss budget.
- Zero placeholders, ellipses, or truncated code; clean domain-based filenames (no `phase_a`/`phase_b`/`task_x`).
- Every modified/created Python module must pass `ruff check` (`0` errors) and `scripts/complexity_ratchet.py` (`0 problems`, max cyclomatic complexity `<= 20`).
- Installed app remains importable without optional research ML packages (`scikit-learn` imported lazily inside ML gateway methods only).
- `2025-11-24 .. 2026-11-23` is permanently classified as `BEAR_STRESS_REPLAY_SEEN` (never called an untouched final holdout).

---

### Task 1: Repair Constrained Convex Solver & Cross-Check Against `scipy.optimize`

**Files:**
- Modify: `gym-core/src/gym/domain/convex_optimizer.py`
- Test: `gym-core/tests/test_financial_engine.py`

**Interfaces:**
- Produces: `solve_convex_portfolio(problem: OptimizationProblem, *, max_iter: int = 500, tol: float = 1e-7) -> OptimizationResult` using projected proximal gradient (FISTA with adaptive step size and exact Euclidean projection onto box + budget + underlying/issuer group caps) plus true projected-gradient KKT residual.

- [ ] **Step 1: Add failing test for binding-budget counterexample and `scipy.optimize` agreement**
  Test inputs: `w0=(0.5, 0.5)`, `mu=(0.02, 0.06)`, `cov=((0.01, 0.0), (0.0, 0.01))`, `risk_aversion=1.0`, `l1_fee_costs=(0.001, 0.001)`, `l2_impact_costs=(0.0, 0.0)`, `max_weight=1.0`, `cash_buffer=0.0`. Assert solved weights match `(0.0, 1.0)` within `1e-4` and objective matches `0.0540` within `1e-5` (and matches `scipy.optimize.minimize` on multi-asset binding-cap fixtures and symbol permutations).
- [ ] **Step 2: Run pytest to verify failure on current single-coordinate solver**
  Run: `uv run --no-sync pytest -q tests/test_financial_engine.py`
- [ ] **Step 3: Implement projected proximal-gradient solver with Dykstra/simplex projection & exact KKT residual in `convex_optimizer.py`**
- [ ] **Step 4: Run pytest, ruff, and complexity ratchet to verify pass**

---

### Task 2: Explicit Covariance Axis Alignment, Timestamp-Joined Returns & Replay Speedups

**Files:**
- Modify: `gym-core/src/gym/domain/async_covariance.py`
- Modify: `gym-core/src/gym/domain/microstructure.py`
- Modify: `gym-core/src/gym/domain/statistical_inference.py`
- Modify: `gym-core/src/gym/domain/passive_execution.py`
- Modify: `gym-core/scripts/evaluate_candidates.py`
- Modify: `gym-core/scripts/instant_gate_check.py`
- Test: `gym-core/tests/test_financial_engine.py`, `gym-core/tests/test_trading_framework.py`, `gym-core/tests/test_quant_modeling.py`

**Interfaces:**
- Produces:
  - `align_covariance_to_symbols(target_symbols: tuple[str, ...], source_symbols: tuple[str, ...], matrix: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]`
  - `coarse_bar_shrunk_covariance_aligned(dated_returns_by_symbol: dict[str, dict[datetime, float]], target_symbols: tuple[str, ...], *, shrinkage: float = 0.25) -> tuple[tuple[float, ...], ...]`
  - Arithmetic `divmod` VPIN bucket batching + strict `BUY`/`SELL` aggressor validation in `MicrostructureConsolidator.on_trade`.
  - `set`-backed test-index lookup in `purged_cpcv_splits` and `bisect` availability lookup in `simulate_passive_orders`.
  - Keyed `instrument_id` candle query + fixed stateful causality lambda in `instant_gate_check.py` and `evaluate_candidates.py`.

- [ ] **Step 1: Add failing tests for symbol-permutation covariance invariance, misaligned missing dates, 100M-unit PEPE VPIN print speed, unknown aggressor side, and stateful causality positive-control detection**
- [ ] **Step 2: Implement all five repairs with exact parity**
- [ ] **Step 3: Verify pytest, ruff, complexity ratchet, and commit engine repairs cleanly**

---

### Task 3: Multi-Timeframe Panel, Bar-Source Parity & Eligibility Contract

**Files:**
- Create: `gym-core/src/gym/domain/timeframe_panel.py`
- Test: `gym-core/tests/test_ensemble_and_meta_gateway.py`

**Interfaces:**
- Produces:
  - `BarPoint(ts_start, ts_avail, open, high, low, close, volume, bar_source, clock_complete, nonzero_volume_fraction, entry_eligible, mark_status)`
  - `load_keyed_candles(con, symbol, resolution, *, limit=25000) -> list[BarPoint]`
  - `resample_hourly_to_bucket(hourly_bars, hours: int, *, offset_hours: int = 0) -> list[BarPoint]`
  - `audit_bar_parity_and_coverage(con, symbols, *, start_at, end_at) -> dict`

- [ ] **Step 1: Write unit tests verifying lossless UTC resampling, `INCOMPLETE_BAR` handling, zero-volume `entry_eligible=False`, and `offset_hours` shift sensitivity**
- [ ] **Step 2: Implement `timeframe_panel.py` using keyed `instrument_id` SQLite queries**
- [ ] **Step 3: Run tests and ruff**

---

### Task 4: Slow Uncorrelated Sleeves (`S1, S2, S5`) & Self-Financing Shared Ledger

**Files:**
- Create: `gym-core/src/gym/domain/strategy_sleeves.py`
- Create: `gym-core/src/gym/domain/paper_ledger.py`
- Test: `gym-core/tests/test_ensemble_and_meta_gateway.py`

**Interfaces:**
- Produces:
  - `SleeveSignal(symbol, as_of, s1_trend, s2_residual_mom, s5_defensive_gold, crypto_breadth, active_crypto_count, eligible_for_entry)`
  - `compute_slow_sleeves(panel_by_symbol, symbols, *, gold_symbol="XAUTUSDT") -> dict[datetime, dict[str, SleeveSignal]]`
  - `SelfFinancingLedger`: exact `Decimal` cash, base units, drifting holdings, received-asset fee debits (`BUY` debits base, `SELL` debits quote), zero cost on unchanged inventory, and full reconciliation invariants (`NAV == cash + sum(units * mark)`).

- [ ] **Step 1: Write unit tests for `S1/S2/S5` warmup/tie/breadth rules, cash->buy->hold->sell ledger conservation, zero cost on unchanged holdings, and end-to-end future perturbation causality (with future-peeking positive control)**
- [ ] **Step 2: Implement `strategy_sleeves.py` and `paper_ledger.py`**
- [ ] **Step 3: Run tests and ruff**

---

### Task 5: Veto-Only Calibrated Logistic Meta-Gateway, Adaptive Vote & Synthetic Falsification

**Files:**
- Create: `gym-core/src/gym/domain/meta_gateway.py`
- Create: `gym-core/scripts/evaluate_ensemble_gateway.py`
- Test: `gym-core/tests/test_ensemble_and_meta_gateway.py`

**Interfaces:**
- Produces:
  - `AdaptiveVoteGateway` (decayed-Sharpe capped weights with abstention remainder)
  - `LogisticVetoGateway` (lazy `sklearn` `Pipeline([SimpleImputer, RobustScaler, LogisticRegression(C=0.2)])` + chronological inner-fold sigmoid calibration, expected-value payoff gate, Brier Skill Score / ECE / reliability diagnostics, and shadow scoring of rejected proposals)
  - `run_synthetic_falsification_checks()` (null noise panel + planted feasible edge panel)
  - `evaluate_ensemble_gateway.py` outputting `evidence/2026-11-24-first-ensemble-experiment-report.md` with all four sign-off artifacts: (1) dated coverage & bar-parity report, (2) solver & ledger reconciliation receipt, (3) arm-by-arm paired comparison (`CASH_USDT`, `STATIC_GOLD_AND_CRYPTO`, `FIXED_S1`, `FIXED_ENSEMBLE_S1_S2_S5`, `ADAPTIVE_VOTE`, `LOGISTIC_VETO`) with date-block bootstrap CI & attribution, and (4) machine-readable JSON decision receipt.

- [ ] **Step 1: Write unit tests for synthetic null rejection, synthetic planted-edge recovery, Brier skill score, shadow veto accounting, and importability without sklearn at module load**
- [ ] **Step 2: Implement `meta_gateway.py` and `evaluate_ensemble_gateway.py`**
- [ ] **Step 3: Run full test suite, `ruff check`, `complexity_ratchet.py`, execute `evaluate_ensemble_gateway.py` on live `market.db`, inspect real results, and commit cleanly**
