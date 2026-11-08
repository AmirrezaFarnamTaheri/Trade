# Phase D portfolio risk: implementation ledger

Paper-only and causally evaluated. Nothing here submits venue orders or
authorizes funded trading. New options are opt-in. Unverified performance
must never be reported as a verified improvement.

## 31 — Whole-portfolio volatility target (mechanics implemented; acceptance open)

`portfolio_volatility_target` is an optional policy Decimal string in
(0, 1], expressed as the standard deviation of **one aligned closed-bar
return**, not annualized volatility. The unit is explicit because market
closures and differing bar resolutions make an unqualified annualization
misleading. The existing closed-price covariance (optionally shrinkage-
adjusted and Parkinson-rescaled) measures **joint** target-weight risk.

After max-weight and correlation caps are applied, the ratio
`target / sqrt(w' Sigma w)` scales every weight, with a hard upper cap of
1. This implementation can only **reduce** exposure: it never borrows,
adds leverage, or fills a missing history. The report records the
unscaled risk, scale, target, and modeled post-scale risk in the
`TARGETS` policy events. The opt-in changes portfolio version to 7;
existing no-option run identities remain unchanged.

Remaining acceptance: measure realized portfolio volatility against the
configured target across matched out-of-sample paper replays, with
documented bands, changing market availability, costs and cross-market
quote-currency normalization. A covariance estimate alone is not realized
risk control or evidence of a stable volatility target.

## Ordered remaining work

- **32 — TMN/USDT factor (mechanics implemented; empirical gate open):**
  Optional `usdt_fx_risk: true` is restricted to TMN-quoted portfolios.
  Each closed market price (and optional Parkinson high/low) is converted to
  USDT using the previous strictly available, qualified, open USDT/TMN
  midpoint. A missing, closed, invalid or stale FX rate clears all risk
  histories, invalidates targets, and requires a fresh warmup; no future
  prices may be used. Covariance therefore includes the TMN depreciation
  factor while capital and cash accounting remain in the original TMN
  units. Target events label risk currency USDT; the FX observation digest
  and opt-in schema version (8, or 9 jointly with item 31) are recorded.
  Still required: independent out-of-sample FX stress evidence and actual
  USDT-denominated risk calibration.
- **33 — Expected shortfall (partial mechanics; acceptance open):**
  Optional `expected_shortfall_limit` requires at least 20 prior closed
  bars and explicit portfolio rebalancing. For frozen current target weights,
  the worst ceiling(5% × history length) prior portfolio bar returns yield a
  descriptive historical ES95. The policy can only downscale exposure and
  records the modeled loss, scale, confidence, limit, and worst observed
  returns. This is not a verified realized loss limit: recorded historical
  stress-day replay, out-of-sample tail calibration, and gap-aware realised
  ES comparison remain unfinished. The optional policy uses portfolio
  run version 10 and preserves default identities.
- **34 — Cost-aware rebalancing (mechanics implemented; acceptance open):**
  Optional `cost_aware_rebalance: true` requires `rebalance: true`.
  At a later policy decision, the strategy's most recent causal qualified
  book establishes a no-trade band: the greater of the old static threshold
  and two modeled fees plus the observed full spread and any selected dated
  uplift. No qualified recent quote means no rebalance request. The
  `REBALANCE_BAND` event records the source quote time, tracking drift,
  estimated turnover/cost, applied band and whether an order was requested.
  This does not override a strategy's protective exit or its original
  risk gate. Opt-in version 11. Still required: demonstrate lower *realized*
  turnover and after-cost return versus the fixed-band rule on identical
  held-out paper observations, with tracking error and fill uncertainty.

- **35 — Fractional sizing receipts (mechanics implemented; acceptance open):**
  The `fractional-sizing` research action retains a new immutable
  `fractional-sizing/2` report. A later portfolio-replay request may supply
  `cost.fractional_sizing_report_id` (instead of `max_fraction`) for
  a fixed-symbol universe. The loader validates the report digest, native
  underlying paper run and result digest, matching strategy identity,
  resolution, fee assumption and symbol membership. The evaluated historical
  window must end before the new replay starts. Ineligible, zero, or stale
  evidence is refused; the cap and source IDs appear in the canonical cost
  inputs. Opt-in portfolio version 12. This is *locally* verified, not
  independently attested; no funded sizing is authorized.

- **36 — HRP allocator (mechanics implemented; acceptance open):**
  Optional `method: hierarchical-risk-parity` applies deterministic
  Decimal single-linkage correlation-distance clustering and recursive
  inverse-variance bisection on earlier aligned covariance. Up to 100
  markets are bounded; degenerate matrices fail closed. Its output records
  the leaf order and only makes paper target weights. A textbook two-cluster
  matrix regression verifies adjacency and risk-weight direction.
  Still required: compare realized costs, turnover, and OOS volatility
  against equal, inverse-vol and risk-parity baselines over >30 markets.

- **37 — Depth liquidation valuation (mechanics implemented; acceptance open):**
  A historical `margin-replay` may opt into `depth_valuation: true`
  (v2). A fresh observed full book must have aligned best quote/quantity,
  strict price ordering and enough displayed quantity to liquidate the
  entire long base position or repay all borrowed short base, including
  base-denominated fees. The open equity uses depth-walk proceeds or
  buyback cost with hypothetical exit fee; insufficient, invalid, missing
  or stale depth has no modeled liquidation value, never a fabricated
  fill. The report exposes walked value, fee, midpoint proxy, and gap to
  midpoint. The original top-of-book method remains the default and its
  report schema/identity stays unchanged. This is **not a real margin
  health trigger, forced-liquidation promise or venue executable fill**;
  actual account borrow eligibility and live settlement remain unverified.

Every remaining item requires its own regression tests and full Python,
Ruff, browser, Windows, Rust and security gates. No phase-complete
claim is justified until all seven items and empirical acceptance pass.
