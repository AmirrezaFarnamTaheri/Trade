# Observation Sampling, Economic Power & Executable-Net Evidence Contract

**Status:** Canonical research & financial labeling specification (tasks `S001`, `S002`, `G010`, `X001`)  
**Applies to:** All historical replays, prospective paper journals, shared-cash portfolios, and statistical scorecards.

## 1. Economically qualified "net" evidence ladder (`G010`)

Every return, Sharpe ratio, P&L figure, or fill summary displayed in CLI output, JSON reports, evidence markdown, or the browser workspace belongs to exactly one evidence tier. Lower tiers must **never** be presented as higher tiers.

| Tier | Required label | What is actually modeled/observed | Prohibited claim |
| --- | --- | --- | --- |
| **0** | `DEMO / SYNTHETIC` | Generated fixture quotes/trades for UI/smoke testing | Never market or research evidence |
| **1** | `OBSERVED PUBLIC DATA` | Authentic recorded Wallex quotes/trades/depth/candles with raw-segment provenance | Not an executable fill or account balance |
| **2** | `MODELED PAPER (REFERENCE)` | Mid/close/bar-based signal simulation with fixed/assumed fees | Not historically executable net return |
| **3** | `HISTORICALLY CONSTRAINED PAPER` | As-of venue rules (tick/lot/min/halt/order-type), dated fee schedule, actionable touch/depth walk, latency & conservative maker queue | Not live fill guarantee or venue settlement |
| **4** | `REGISTERED FORWARD PAPER` | Frozen strategy/model identity executed causally on unseen future days (`journal.jsonl`, `mix-journal.jsonl`, `breadth-journal.jsonl`) | Not independent custody until custodian-verified; not live capital proof |
| **5** | `INDEPENDENTLY RELEASED` | Preregistered identity evaluated once by a separated custodian ([independent-custody-protocol.md](independent-custody-protocol.md)) with signed/anchored release bundle | Still paper economics unless paired with Tier 6 venue evidence |
| **6** | `AUTHENTICATED VENUE` | Signed/verified account reads, order acknowledgments, actual fills, fees, and balances from Wallex under qualified installed HOST | Never inferred from paper or public feeds |

## 2. Strict executable-net gate (`X001`)

A replay or order fill may carry the `HISTORICALLY CONSTRAINED PAPER` (executable-net) label **only** when every input required for that order is actually known as-of the decision/execution clock. Missing metadata must **never** be imputed as zero fee, infinite depth, or unrestricted market-order eligibility:

| Required as-of input | If missing, stale, or contradictory | Required status |
| --- | --- | --- |
| Market rule vintage (`stepSize`, `minQty`, `minNotional`, `isMarketTypeEnable`, halt/suspension) | Absent, expired, or future-dated vintage | `UNKNOWN / REFUSED` for executable-net (labeled `MODELED PAPER` only if opt-in fallback is explicitly declared) |
| Applicable fee schedule (account fee or dated structured maker/taker tier) | Fee unavailable or currency outside instrument pair | `UNKNOWN / REFUSED` (never zero-fee unless explicit as-of `is_zero_fee == true` receipt) |
| Actionable quote (non-crossed, non-stale qualified bid/ask) | Missing, `STALE`, `CROSSED`, or `ZERO_SPREAD` anomaly | `NO_QUOTE / ABSTAIN` (no invented close-price fill) |
| Depth / capacity for order clip | Order size exceeds displayed qualifying depth levels | Partial fill up to observed depth + explicit residual, or `INSUFFICIENT_DEPTH` (never silent full fill) |
| Maker queue capacity | Indistinguishable identical-field REST/WS prints without venue trade IDs | Flag `AMBIGUOUS_PRINT_CAPACITY` and apply conservative adverse sensitivity |
| Terminal mark valuation for open inventory | Stale/missing bid mark or missing FX conversion route | Mark status `PROVISIONAL` or `UNKNOWN`; never net mixed currencies (TMN/USDT) without dated executable FX route |

## 3. Canonical observation & return sampling contract (`S001`)

Before any statistical test (Sharpe, Lo/HAC Sharpe, PSR, DSR, stationary-block bootstrap, SPA-style comparison, ES/CVaR) is computed on an equity or return series, the series must satisfy:

1. **Fixed timestamp grain:** Declare the exact sampling calendar (e.g. `1d` UTC close, `15:00 Asia/Tehran` daily grid, or fixed intraday bar spacing `BarSpec`). Mixed or ad-hoc event-time ticks cannot be annualized as fixed-period bars.
2. **Strict monotonicity & duplicate refusal:** Timestamps must satisfy $t_0 < t_1 < \dots < t_n$. Non-positive intervals ($\Delta t \le 0$) must be counted (`mark_spacing.nonpositive_intervals`) and cause statistical promotion scores to refuse (`INVALID_SAMPLING_CLOCK`).
3. **Mark-age & gap disclosure:** Every sampled mark carries its quote/candle source timestamp. A mark older than the declared `max_mark_age` (default 5 minutes for live touch journals; 1 bar for bar-based replay) marks that observation `STALE`. Multi-day gaps must never be silently filled with invented zero returns to inflate $N$.
4. **Cross-asset & calendar-date clustering (`S006`):** Multi-asset panels on overlapping dates are **not** independent observations. Statistical uncertainty (bootstrap blocks, paired baseline uplift, effective $N$) must cluster by calendar date / market-date blocks, never by `num_assets * num_days`.
5. **Refusal conditions (`S022`):** Return `NOT_ESTABLISHED` (never a numeric pass) whenever: sample count is below minimum required for the declared block length, return variance is zero/degenerate, terminal or >10% of marks are stale/provisional, benchmark calendar/currency mismatches, or costs are undeclared.

## 4. Minimum detectable economic effect & prospective power (`S002`)

Prior power analysis ([evidence/archive/early-trials/2026-11-18-detectable-edge.md](../../evidence/archive/early-trials/2026-11-18-detectable-edge.md)) showed that earlier daily tests could not reliably detect edges below **~10 bps/day (~44%/yr)**, whereas realistic net edges are **1–5 bps/day**. Accordingly, every new registered trial must declare before running:

1. **Smallest economically useful net excess return** ($\Delta_{\min}$, after full round-trip fees, spread, and turnover cost) against its investable same-currency benchmark.
2. **Expected daily volatility and autocorrelation/block dependence** ($\hat{\sigma}$, block length $L$).
3. **Prospective power / required horizon** computed via `gym-core/scripts/detectable_edge.py` at $\alpha = 0.05$ (multiplicity-adjusted for family size $K$) and power $1 - \beta \ge 0.80$.
4. **Honest interpretation (`S009`):** A run whose realized sample size cannot detect $\Delta_{\min}$ reports `UNDERPOWERED / NOT_ESTABLISHED` rather than claiming "proof of no edge" or "proof of edge".
