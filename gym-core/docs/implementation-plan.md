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
| O1 | Diagnose collector shutdown and unify startup/data-root selection | One collector on loopback; all eligible pairs by default; explicit exclusions; current native assets served | Startup/all 373 selected pairs verified; 13:06 UTC snapshot has 292 READY and 81 STALE; REST TLS remains impaired |
| O2 | Supervise collection and paper scheduling | No duplicate processes; clear failures/retries; no hidden narrowing to BTC/ETH/USDT; recovery preserves history | Limited-user task supervision verified; sustained observation still open |
| O3 | Publish one current campaign/results view | Show defined/attempted/completed/ready/traded counts, exclusions, dated progress and process liveness separately | Queued |

## Organization

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| 12 | Continue browser view separation | Preserve EN/FA, theme, focus, mobile layout, hashed assets and existing UI contracts | Queued |

## Research mechanics

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| 29 | Overfitting and regime diagnostics | Declare CSCV/block/dependence assumptions; distinguish trade-path reshuffling from new market samples; no confidence from insufficient data | Queued |
| 16 | Shared optional exit policy | Fixed, ATR trailing, profit and time exits; actual holdings/fills, partials, dust, costs and closures; defaults preserve existing run identities | Queued |
| 19 | Optional reusable regime gate | Verify the actual detector owner first; causal inputs, explicit regime transitions, default-off identity compatibility | Queued |
| 20 | Stop-risk sizing in replay | Reuse portfolio_sizing with exact quantities, stop distance, shared cash, reservations, venue minimums and explicit unknowns | Queued |

## Strategy and portfolio research

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| 18 | Toman premium, Donchian/turtle, compression and lead-lag hypotheses | Separate preregistered rules, causal aligned inputs, FX/closure costs and held-out comparisons; none is an established edge | Queued |
| 21 | Inverse-volatility/risk-parity weights, correlation caps, rebalance clocks | Shared-cash accounting, lookback readiness, causal covariance and turnover/cost controls; test allocation conservation | Queued |
| 22 | Portfolio drawdown and daily loss limits | Latched state, correct Tehran/UTC clock policy, actual simulated exposure and restart/replay parity | Queued |
| 23 | Capped fractional Kelly sizing | Require sufficient out-of-sample evidence; disclose estimation uncertainty; a supplied fraction is not an inferred optimal fraction | Queued |
| 25 | TWAP and spread-aware execution choice | Recorded child orders, displayed capacity, partials, cancellation, timing and total reservation conservation; paper only | Queued |
| 30 | Prospective shadow comparison | Freeze configurations before future data; matched costs/baselines; daily drift, gaps and no-trade cases visible | Queued |
| 31 | Scorecards, parameter heatmaps and backtest/shadow overlays | Read native verified records; show USDT/FX status, trial counts, failure/readiness and statistical limitations | Queued |

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
