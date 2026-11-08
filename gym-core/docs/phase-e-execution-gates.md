# Phase E — execution and the path to live (November improvement plan, 38–46)

**This is a paper-only implementation ledger, not trading authorization.**
Phase E cannot make real orders possible by implication. The funded loss budget
remains zero, and dependency E43 (protected executor submit/cancel/recovery and
external operator approval) is outside this workstream.

| Item | Contract | Current implementation state |
| --- | --- | --- |
| 38 | Trade-volume participation TWAP, limit-vs-market decisions from prior spread and urgency, selected dated impact-model costs, paired equal-slice report | Paper mechanics added: `adaptive-twap-preview` prior-volume/spread/urgency and equal-slice reference; no significant Almgren–Chriss fit or verified cost improvement |
| 39 | 1/5/30-minute post-fill adverse move per strategy and order type, causally fitted cost feedback | Paper mechanics added: `postfill-check` records retrospective 1/5/30-minute signed markouts on verified native paper fills; optional bounded later-replay adverse-cost profile |
| 40 | Daily shadow drift beyond 2σ alerts, immutable demotion evidence | On-demand `shadow-drift-screen` uses a prior disjoint run and recorded prospective paper days; no continuous monitor or executor demotion |
| 41 | Fixed DSR, history, SPA, prospective and shadow gates, logged before any operator approval | Local paper diagnostic: `paper-promotion-screen` reports fixed numerical thresholds, always blocks any funded promotion without independent evidence |
| 42 | Reference-vs-Wallex feed divergence trips entry lock, with frozen-feed test | `feed-divergence-screen` uses strictly prior matched quotes and a trained spread bound; `feed-divergence-lock` records a scoped, paper-only `BLOCK_ENTRY` rule; reference authenticity unverified |
| 43 | External executor order path and recovery | **Blocked external dependency**, not in this paper-only PR |
| 44 | Read-only order `fills[]` with fee currency and maker/taker coefficients | Measured fee coefficients retained when complete in existing GET `fills[]` evidence; fee asset kept exact and maker/taker classification marked ambiguous when rates equal; account settlement remains unknown |
| 45 | Public fair-price observation channel, timestamped storage, labeled non-executable fallback | `fairprice-observe`/`fairprice-read` parse the documented public snapshot shape into an immutable available-at journal; subscription and authentication not installed |
| 46 | Versioned operator-review client-id constraints and paced submit path | `PaperSubmissionGate` dry-run journal enforces submit-only IDs, uniqueness and 20/10-second paper pacing. A distinct **offline** Rust v2 review codec has tests; native service/helper wiring and real pacing are **not installed**; no live submit path enabled |

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


## Items 39–42, 44–46 — controls and remaining acceptance

- **39:** Paper markouts read only qualified future quote midpoints *after* their
  synthetic fill, preserving missing horizons. A 30-sample, bounded adverse
  5-minute profile may optionally affect later paper costs and is fitted from
  a qualified fill-time midpoint rather than the spread-bearing fill price;
  it is never fit within the replay that consumes it. Real authenticated fill markouts and
  actual execution-cost correction remain outstanding.
- **40:** The on-demand, matched/disjoint historical-versus-shadow report uses
  complete consecutive UTC days and a fixed training sample. A shadow daily
  return below mean minus two standard deviations records a paper-only
  demotion recommendation. No always-on scheduler, independent provenance or
  live registry demotion is claimed.
- **41:** Fixed local thresholds include DSR probability at least 0.95, at least
  300 closed positions and 90 days' history, SPA-style p at most 0.05,
  successful prospective study and at least 20 compliant shadow days.
  Self-reported figures are **never** independent evidence and never pass the
  protected executor's approval gates. No funded permission is possible here.
- **42:** Matched, prior public midpoint deviations train a baseline and trip
  a paper `BLOCK_ENTRY` rule on divergence or stale input. Local input is
  not authenticated as a second independent feed; manual invocation is not
  continuous monitoring and never blocks exits or cancellations.
- **44:** The existing private-order **read parser**, not a new endpoint,
  retains the supplied fee amount, fee asset and complete maker/taker rate
  fields; no exchange reconciliation, fill authenticity or cash settlement
  is assumed. Missing/inconsistent coefficients fail or stay unavailable.
- **45:** Documented `public:all@fairPrice` snapshots use ISO `ts` plus
  `prices{SYMBOL:string}`. Imported snapshots are persisted by receipt
  availability, and fresh midpoints are labeled **not executable**.
  No websocket channel subscription is enabled, and missing/stale marks are
  never substituted into trading execution.
- **46:** The stand-alone dry-run `PaperSubmissionGate` enforces ASCII
  `[A-Za-z0-9_]{1,64}`, durable per-account duplicate rejection and a
  rolling 20-proposals-per-10-seconds cap. The offline Rust review v2
  codec uses distinct request/reply magic and rejects invalid submit-side
  IDs while allowing historical read-only identities. The installed
  native review service remains v1: no funded submit or paced order path
  is attached.

All of these contracts require separate authenticated venue observations,
prospective stress windows, integrated scheduler/executor controls and
operator sign-off before a live Phase E completion claim. CI green only
establishes the paper-side regression contract, not those external gates.
