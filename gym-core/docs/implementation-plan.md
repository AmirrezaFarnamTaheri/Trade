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
| 18 | Toman premium and lead-lag hypotheses | Causal quote-time aligned exploratory diagnostics and historical paper strategy classes exist; held-out validation, transfer/closure costs and real costs remain required | Offline implementation; empirical qualification open |
| 25 | TWAP and spread-aware execution choice | Exact-decimal bounded paper child preview and supervised retrospective immediate-vs-TWAP comparison use the same quote snapshot and optional dated cost models. Compare effective prices only for two complete, equal-quantity fills. Real child placement/cancel/reconciliation, venue reservation and timing remain unverified | Paper preview and historical comparison implemented; protected integration open; see phase-c-execution-choice.md |
| 30 | Prospective shadow comparison | Locally frozen future configurations, disjoint windows, consume-before-read and matched simulated accounts; still needs real future collection, daily drift reports, independent custody and empirical evidence | Local preregistration implemented; future validation open |
| UI | Complete the source-audited interface refinements and rendered checks | Guided EN/FA premium, lag, TWAP and prospective freeze/inspect/evaluate forms added; remaining destinations, real-browser mobile/RTL/screen-reader checks, report freshness segmentation and other refinements still need current-build verification; see interface-review.md | Partial; not signed off |

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
