# Phase B — market-model upgrade (in progress)

## Item 19: shared, causal high–low volatility

The opt-in model `parkinson-ewma` estimates per-bar variance from a *closed and available*
bar only:

`v_t = 0.94 v_(t-1) + 0.06 (ln(high_t / low_t) ** 2) / (4 ln 2)`.

The first available bar seeds the estimate; unqualified bars and missing high/low
must not be treated as zero-volatility periods. The implementation uses Python's
standard-library `Decimal` with a deliberately high precision context. No new
dependencies or executor/order permissions are introduced.

- Paper entry sizing: `gymctl paper ... --vol-target 0.002 --volatility-model parkinson-ewma`.
  With no `--vol-target`, the new model has no effect on execution or run identity.
- Optional exit model: `exit_atr_multiple` together with
  `exit_volatility_model: parkinson-ewma`; the high-low sigma times current
  closed-bar price substitutes for ATR distance. The existing ATR-based exit is
  the default.
- Optional regime model: `regime_gate: RANGE` and
  `regime_volatility_model: parkinson-ewma`. The fixed ADX cutoffs remain unchanged;
  the alternative only changes the reference distance against the EMA spread.
- Optional portfolio model: `policy.volatility_model: parkinson-ewma` uses
  the same high-low sigma for the covariance diagonal while keeping observed
  correlations. The default `close-std` covariance continues unchanged.
- Paper portfolio API cost models also accept the optional `volatility_model`
  setting when volatility-target sizing is enabled.

**Important:** A high-low Parkinson estimate is not interchangeable with ATR
for gap risk. Its formula omits open-to-open jumps, so comparing stop efficacy,
risk calibration, and out-of-sample results against the existing ATR baseline is
mandatory before any promotion. This is experimental paper-only model research,
not a verified improvement in trading performance.

## Phase B remaining gates

Items 20–24 are not implemented in this PR: covariance-shrinkage calibration,
square-root impact fitting, time-of-day execution costs, capacity estimation,
and experimental probabilistic regime selection. They require separate testable
changes and Phase A out-of-sample gates.

## Verification

Run `cd gym-core && uv run pytest tests/test_phase_b_volatility.py tests/test_phase_b_model_consumers.py`
and `uvx ruff==0.16.9 check src tests`, then full CI on Linux and Windows.
