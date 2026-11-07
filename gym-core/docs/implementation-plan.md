# Implementation and acceptance plan

Current delivery state is in [system status](system-status.md).
[Capabilities](capabilities.md), [research contracts](research-workspace.md) and
[adapter contracts](wallex-api.md) describe supported behavior. This plan contains
remaining implementation and acceptance work.

Use the native owners and exact money arithmetic. Preserve operational journals,
raw observations, saved results and failed attempts. Research and DEMO evidence
cannot grant protected execution authority. The funded loss budget is zero.
No push, paid provider request or credential change is implied.

## Operations

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| O1 | Diagnose collector shutdown and unify startup/data-root selection | One collector on loopback; all eligible pairs by default; explicit exclusions; current native assets served | Current assets and 373-pair retained selection verified; REST and WebSocket connections currently fail; freshness remains blocked |
| O2 | Supervise collection and paper scheduling | No duplicate processes; clear failures/retries; no hidden narrowing to BTC/ETH/USDT; recovery preserves history | Direct Python task stop/child termination verified on an isolated collector; both current tasks running; sustained observation still open |

## Strategy and portfolio research

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| 18 | Toman premium and lead-lag hypotheses | Prior Donchian/compression rules are available; remaining hypotheses need causal aligned inputs, FX/closure costs and held-out comparisons; none is an established edge | Open |
| 25 | TWAP and spread-aware execution choice | Recorded child orders, displayed capacity, partials, cancellation, timing and total reservation conservation; paper only | Queued |
| 30 | Prospective shadow comparison | Freeze configurations before future data; matched costs/baselines; daily drift, gaps and no-trade cases visible | Queued |
| UI | Complete the source-audited interface refinements and rendered checks | Guided workflows, readable reports/receipts, searchable states and current-build EN/FA/theme/phone/accessibility verification; see interface-review.md | Open |

Predictive ML/RL training is outside delivery scope. New external data requires
a provider, clock/revision/rights contract and explicit credentials/paid-call
authorization. Optional model interpretation remains separate from verified
arithmetic.

## Protected account and execution

| Work | Completion requirement | State |
| --- | --- | --- |
| Service-owned account readiness | Instrument/rule/unit identity, actual key permission semantics, complete exposure/reservations, pagination and fee provenance | Open |
| Authenticated observation/settlement | Verify actual venue responses; absence of orders is not completeness, spendability or settlement | Unverified |
| T1 admission and arming | Consume exact operator review, account/rule/cost evidence and installation/session/loss caps atomically | Open |
| Real submit/cancel/reconciliation | Fixed origin, durable first-byte outcomes, no blind retry, partial fills and unknown-order holds across restart | Open |
| Protective exits and capped automation | Qualified venue protection, disjoint quantities, restart/reopening and hard installation/loss ceilings | Open |
| Maker/trade-credit/relay/multi-leg execution | Distinct custody/idempotency/settlement/protection/outage contracts after core execution | Open |
| Installed custody/isolation/STOP | Repeat current-build drills after relevant deployment/policy changes; earlier synthetic receipts remain dated evidence | Existing host evidence; requalification scoped to changes |
| Actual-versus-modeled costs | Independently reconcile measured quantities, fees, depth and latency; separately authorized probe and loss budget before funded testing | Open; funded budget zero |
| Independent final evaluation | Consume-once local registry plus independent custody and a real future evaluation window | Open |
| Physical-host recovery | Restore on a second physical host, explicitly reprovision credentials and retain DISARMED | Blocked: user has no second machine |


A future observation window needs actual elapsed time and valid collection.
A physical-host recovery drill needs a second machine. These acceptance
conditions remain explicit while implementable contracts continue.

Record completed behavior and exact validation in the current system status.
