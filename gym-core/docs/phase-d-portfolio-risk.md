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

- **32 — TMN/USDT factor:** Value each TMN instrument's returns in USDT
  using causally available FX quotes before estimating covariance. Block
  missing FX; never pretend TMN risk is USDT risk.
- **33 — Expected shortfall:** Evaluate worst historical 5% net USDT
  returns, recorded stress-day scenarios, and a bounded exposure-downscaling
  factor. Report the limit and tested scenario set.
- **34 — Cost-aware rebalance band:** Require the estimated benefit of
  trading to exceed explicitly modeled costs. Report tracking error,
  executed turnover, and resulting cash, using identical input data.
- **35 — Fractional sizing:** Consume a locally verified prior report ID;
  record source inputs and cap without letting a later report alter an
  earlier execution decision.
- **36 — HRP option:** Implement a dependency-free deterministic
  hierarchical clustering for more than roughly 30 markets. Compare
  against an independently worked two-cluster example.
- **37 — Margin liquidation book walk:** Price hypothetical forced
  settlement through observed depth with bounded, fail-closed gaps; report
  the spread between mid and executable liquidation value.

Every remaining item requires its own regression tests and full Python,
Ruff, browser, Windows, Rust and security gates. No phase-complete
claim is justified until all seven items and empirical acceptance pass.
