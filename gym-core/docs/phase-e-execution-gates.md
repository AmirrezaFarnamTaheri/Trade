# Phase E — execution and the path to live (November improvement plan, 38–46)

**This is a paper-only implementation ledger, not trading authorization.**
Phase E cannot make real orders possible by implication. The funded loss budget
remains zero, and dependency E43 (protected executor submit/cancel/recovery and
external operator approval) is outside this workstream.

| Item | Contract | Current implementation state |
| --- | --- | --- |
| 38 | Trade-volume participation TWAP, limit-vs-market decisions from prior spread and urgency, selected dated impact-model costs, paired equal-slice report | In progress: `adaptive-twap-preview` paper-only research action; no Almgren–Chriss fit or verified improvement |
| 39 | 1/5/30-minute post-fill adverse move per strategy and order type, causally fitted cost feedback | Not implemented |
| 40 | Daily shadow drift beyond 2σ alerts, immutable demotion evidence | Not implemented |
| 41 | Fixed DSR, history, SPA, prospective and shadow gates, logged before any operator approval | Not implemented |
| 42 | Reference-vs-Wallex feed divergence trips entry lock, with frozen-feed test | Not implemented |
| 43 | External executor order path and recovery | **Blocked external dependency**, not in this paper-only PR |
| 44 | Read-only order `fills[]` with fee currency and maker/taker coefficients | Not implemented |
| 45 | Public fair-price observation channel, timestamped storage, labeled non-executable fallback | Not implemented; public payload shape must be verified |
| 46 | Versioned operator-review client-id constraints and paced submit path | Not implemented; no live submit path enabled |

## Item 38 — mechanics and limits

`adaptive-twap-preview` accepts the original TWAP request fields plus
`volume_lookback_seconds` (60..3600), `max_spread_bps` and
`urgency` (`NORMAL` or `FINISH`). Each scheduled decision uses only
public trades with `ts_avail < slot` and the preceding qualified book.
The target is capped at a requested fraction of recently observed traded base
volume and at remaining target quantity. When prior spread exceeds the
threshold, a passive LIMIT is proposed; no fill is claimed without queue
evidence. The final `FINISH` slot may request a MARKET paper fill, priced with
existing exact-Decimal latency, fee, depth and optional dated impact model.
The same frozen historical window produces a plain equal-slice TWAP reference.
Reported modeled costs are compared **only when both schedules completely
fill the same original quantity**. Missing volume, stale quotes, and otherwise
unpriced children are not silently promoted to fills.

Remaining acceptance: record real public trade/quote coverage and fit
significance of item 21's impact model, compare full-fill paper execution
costs on an independent historical or future period, and demonstrate robust
performance across volatility, urgency and market closures. Do not introduce
Almgren–Chriss scheduling until the impact fit passes a documented significant
out-of-sample test.

## Verification / status

No Phase E mechanism is accepted solely from synthetic tests. End-to-end
browser/CLI and Windows/Linux CI plus independent real-data qualification are
required before declaring the phase complete. Each new contract must remain
opt-in so older run IDs and research receipts retain their meaning.
