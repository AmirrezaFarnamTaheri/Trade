# Research workspace implementation

Agreed scope: the eight modules selected on 2026-11-04. Extend existing native
owners, retain observed/demo separation and never infer trading permission.
No paid provider request or funded order is part of this pass. A subsequent
request authorizes a local commit of the completed changes.
The subsequent request to archive reviewed ZIPs is authorized separately; move
receipts retain hashes and preserve existing archives without overwriting them.

Implementation status: all eight bounded research workflows below now have native
service owners, shared CLI/local API dispatch and GUI access. Coverage/recovery
and replay have dedicated readable controls; detailed offline models use the
advanced workbench. Contracts and limits are in [research workspace](research-workspace.md).
This completes these research implementations, not the separate executor,
external-provider, supervised prospective or physical-host acceptance work.

Predictive ML/RL training is outside current delivery scope, as recorded in the
[implementation plan](implementation-plan.md). All eight research modules remain
in scope, including supplied-forecast scoring and optional evidence-linked AI
notes. Neither requires training a predictive trading model.

| Module | Deliverable | Acceptance |
| --- | --- | --- |
| Data coverage and job recovery | Bounded bucket timeline of recorded quotes, bad/stale/missing intervals, late trade receipts and closed-bar readiness; explicit retry/skip and selected-job bounded catch-up | Gaps stay missing, receipts after cutoff excluded, skip requires expected due window and reason, failures retained |
| Replay and decision debugger | Verified saved artifact, paginated chronological decisions with recorded snapshot/features/rules, pre-decision holdings and separately labeled subsequent order outcomes; previous/next GUI controls | No future fill appears in decision-time state, tampering/store mismatch rejected, unknown historical details stay unknown |
| Experiment registry | Immutable experiment definition and durable attempt records registered before calculation; code/config/data/run references, failed/incomplete attempts and frozen final-evaluation links | Failed trials retained; no silent successful-only selection; local registry is not independent custody |
| Market screening and relative strength | One market snapshot, explicit universe, comparable quote currency and cutoffs; momentum/distance/spread/liquidity/volatility diagnostics with exclusions and reference-relative return | Bounded work, stale/warmup symbols excluded from ranking, no aggregate confidence or intrinsic-value label |
| Portfolio planning | Exact offline target rebalance preview over supplied holdings, reservations, bid/ask, quantity steps and fees; sale-before-buy plan, turnover/concentration and shared-cash checks | Locked quantities/cash cannot be spent, no fabricated acquisition basis or settlement, unknown minimums explicit |
| Robustness laboratory | Native strategy replay under bounded fee/latency/feed-removal scenarios over chronological windows, with matched baselines and every attempt retained | Train/evaluation meaning unchanged; stress outcomes are assumptions, insufficient/gapped results visible, no automatic promotion |
| Evidence-linked AI research | Saved allowlisted evidence packet, bounded role/citation/numeric-claim schema and note journal; explicit send through existing optional model gateway | Numeric citations checked; model judgments/disagreements labeled unverified; no order tools, silent paid calls or secret-bearing input |
| Execution-quality analysis | Exact reconciliation of supplied observed fill identities/fees/quantity/latency against saved modeled orders, explicit unmatched/nonfill/unknown records and per-side cost differences | No missing fill inferred; wrong units/currency/order identity rejected; imported observations remain unauthenticated |

Each workflow must reach CLI dispatch, bounded token-protected local API, EN/FA
GUI controls and meaningful regression tests. Complex offline inputs may use the
existing advanced workbench; timeline, replay navigation and recovery require
readable GUI views. Existing protected execution and second-machine qualification
remain separate work in [implementation-plan.md](implementation-plan.md).
