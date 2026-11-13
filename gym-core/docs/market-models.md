# Causal market models, paper research only

Improvement plan items 19–23 define opt-in paper research models. Item 24 deliberately
remains an unpromoted experiment unless separately verified preregistered OOS
evidence beats the **existing fixed ADX regime gate**. A model implementation
does not establish an edge, funded authority, or executable venue capacity.

## 19 — One shared high–low EWMA volatility

`parkinson-ewma` computes the causal closed-bar variance

`v_t = 0.94 v_(t-1) + 0.06 (ln(high_t / low_t) ** 2) / (4 ln 2)`.

The first available closed bar seeds the estimate. Gap resets prevent
non-contiguous bars from masquerading as uninterrupted history. It is a diffusion
volatility model, not ATR gap-risk measurement.

- Paper entry sizing: `gymctl paper ... --vol-target 0.002 --volatility-model parkinson-ewma`
- Strategy exits: `exit_atr_multiple` plus
  `exit_volatility_model: parkinson-ewma` (sigma times closed-bar price, NOT ATR)
- Regime classification: `regime_gate: RANGE` plus
  `regime_volatility_model: parkinson-ewma`; fixed ADX thresholds stay unchanged
- Portfolio risk scale: `policy.volatility_model: parkinson-ewma` preserves
  observed correlations, replaces variance diagonal with the common bar sigma

Every setting is off by default, and historical run identities remain unchanged.

## 20 — Ledoit–Wolf covariance shrinkage

`policy.covariance_shrinkage: ledoit-wolf-constant-correlation` computes a
constant-correlation target and nonnegative, bounded Ledoit–Wolf plug-in
intensity from synchronized historical return rows. The report discloses
intensity, target, and the half-L1 target-weight turnover of successive
shrunk and raw-covariance counterfactual targets. The method retains original
sample variances: pure inverse-volatility weights should be unchanged, while
risk parity and covariance-dependent correlation caps may change. This is
*target* turnover, not executed turnover. Strict window and quadratic
computational budgets apply.

## 21 — Per-market square-root public-print impact

The opt-in model `sqrt-impact/1` estimates

`cost_bps(q) = a * spread_bps/2 + b * sigma_bps * sqrt(quantity / volume_base)`

with nonnegative coefficients and an 80% chronological fit/20% held-out
validation split. The estimator uses *public aggressive trade-print prices
relative to earlier public quotes* as an impact proxy. Public prints do NOT
establish independent funded fill costs. The fit returns an explicit
`UNIDENTIFIABLE` / `INSUFFICIENT_DATA` / `OUT_OF_RANGE` result rather than
inventing a coefficient. Fitted and held-out RMSE are disclosed.

The paper simulator and one-shot paper TWAP use the *same* optional
`impact_models` by symbol, adding only modeled excess above the half-spread
already present in the public bid/ask. Buy quantity is conservatively capped by
cash after modeled uplift. Price guards and normal venue-rule checks remain.
Neither path submits venue orders.

## 22 — Tehran-hour spread and read-only fee observations

`execution-model-calibrate` takes
`{"symbol":"BTCUSDT","from":"<aware ISO>","to":"<aware ISO>"}`.
It observes bounded quote snapshots, reporting each Tehran hour's P95
public spread only when at least 20 qualified quotes exist. When present,
it appends exact maker/taker rates from authenticated, locally stored
read-only GET account observations. Missing fees stay `null`, not zero.
A missing hour has no implied/default spread. Synthetic DEMO reports never
produce live-selectable profiles.

The result's `cost_models` is only a **candidate** opt-in input. For paper
replay, use `--cost-models-json '<JSON>'` with explicit `impact_models` and/or
`hourly_costs` or supply the corresponding portfolio cost object. For
`twap-preview`, use its optional `cost_models` field. A model trained
after the replay window begins fails before any result is recorded.
Replay fill diagnostics disclose observed and modeled spreads and applied
fee rates separately; no assumption is silently applied.

## 23 — Conservative modeled USDT capacity

Every `experiment-scorecard/2` row has a `capacity` block. A verified
native paper outcome with positive net USDT after costs, eligible dated
per-symbol impact profile, adequate held-out fit, and actual fills can show
the size at which incremental model impact consumes half the observed
paper return per traded notional:

`quantity = volume_base * (edge_bps/(2*b*sigma_bps)) ** 2`.

The model reports `capacity_usdt` using the observed average fill price
as a conversion **assumption**. If the impact model, eligible per-fill USDT
conversion, positive edge, quality, or sufficient volume is missing, capacity
is `null` with an explicit reason. In particular, TMN paper runs without
causal per-fill FX are unavailable: boundary FX must never be reused as
fill-time FX. These are model diagnostics, not independent future tradable
capacity forecasts or evidence of repeatable alpha.

## 24 — Three-state probabilistic regime, NOT PROMOTED

`experimental_probabilistic_regime.py` implements bounded causal,
three-tercile trend/volatility Gaussian probabilities (`DOWN_TREND`,
`RANGE`, `UP_TREND`). It is descriptive, not probability calibrated to
predictive outcomes. The model is **not in `create_strategy` or `catalog`**.
The promotion review is fail-closed; it refuses to select a regime gate based
on locally supplied scores, claimed IDs, unregistered tests, or circular
paper performance. Without independently attested prospective
evidence and multiple-comparison-adjusted results beating fixed ADX,
the required outcome is `NOT_PROMOTED` /
`REMOVE_EXPERIMENTAL_GATE`. No favorable true OOS evidence was available
in this implementation; the production fixed ADX gate is retained.

## Safety boundaries and verification

- All models are off by default, paper-only, and recorded in input identity.
- The command and local research API have no new funded executor capability,
  exchange credentials, or external network access for these models.
- Causal fit cutoff, data availability and sample limits fail closed.
- Empty, stale, synthetic, unavailable and ambiguous evidence remains explicitly
  unavailable; no trade or capacity claim is inferred.
- No model is authorized for funded trading or claimed to outperform the
  baseline without independent prospective evidence.

Run `cd gym-core && uvx ruff==0.17.4 check src tests`, then
`uv run --with coverage==7.6.10 coverage run --source=src/gym -m pytest -q`;
also use the repository's Linux, Windows, security and browser CI suites.
