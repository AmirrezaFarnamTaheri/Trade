# Acceptance gates

Updated 7 November 2026 (Asia/Tehran). The application is DISARMED. Research,
account observations, operator acknowledgements and local tests grant no funded
execution authority. This page tracks current gates; dated older receipts remain
in Git history and local qualification artifacts.

| Gate | Current state | What is required |
| --- | --- | --- |
| Public research implementation | Delivered, with current regressions passing | Continue the explicit remaining functionality in the unified plan; implementation is not economic acceptance |
| Portfolio correctness | Revision 5 accounting, target/risk policies, fill-time cash reservations and checkpoint reconstruction implemented and tested | Preserve frozen records; running-process restoration and prospective evidence remain open |
| Continuous market collection | Local collector recording 373 markets since 2026-10-30; a keyless GitHub Actions recorder covers three markets when this machine is off. api.wallex.ir is intermittently unreachable from this machine | Confirm the six-hour catalogue refresh writes rows after an outage; import recorder artifacts before their 90-day expiry |
| Sustained prospective paper | Open | Multi-day future evidence with preregistered configuration, real clocks, no-data failures, fills and costs; downtime stays visible |
| Strategy profitability | Not established. Eight registered trials ([trial log](trial-log.md)): seven failed; T6 (BTCUSDT 50-day trend) passed narrowly and is on a forward paper journal from 2026-11-14 | The forward journal at the 2027-02-08 checkpoint; T6 replayed through the exact engine |
| Account permissions and exposure | Observation transport/journaling delivered; venue acceptance unverified | Actual key-permission semantics, instrument/rule/unit identity, complete locked/external exposure and fee evidence |
| Account/order settlement | Six owner-placed BTCTMN limit orders (2026-11-14) observed outside the app: 0.10% maker and taker fee charged in the received asset, 50,000 TMN minimum, cancel works. Partial fills and stop orders unobserved | A partial fill and a venue stop order; pagination completeness; the same facts read back through the executor's own evidence path |
| T1 admission/arming | Unfinished | Atomically bind trusted account/rule/cost evidence, exact review/reservation and installation/session/loss caps |
| Submit/cancel/reconciliation | Unfinished | Fixed-origin real transport, durable first-byte outcomes, bounded retry rules, unknown holds and restart recovery |
| Protective exits/automation | Unfinished | Qualified native protection, disjoint quantities, reopening/restart and hard loss/installation caps through the real money path |
| Measured execution costs | Unqualified | Independently reconcile observed fills/fees/depth/latency; a separately bounded authorization and budget before funded probes |
| Independent final evaluation | Local consume-once controls delivered; independent custody open | Separate access/custody and an untouched prospective evaluation window |
| Host-instance recovery | Rehearsed in CI (O-5) | `windows-vm-smoke` rebuilds the executor on a clean disposable Windows VM, installs and starts it, verifies it reports DISARMED and records the elapsed time in the job summary; `b3-synthetic-produce` and `b3-synthetic-restore` restore an encrypted ledger backup across operating systems. Custody reprovisioning with real keys stays a host step |
| Current browser appearance/accessibility | Real-browser smoke passed 2026-11-09 (Edge: ten views, paired replay, EN/FA RTL, desktop/mobile overflow, keyboard focus, confirmation dialog); axe-core scan not run locally | An axe-core scan in CI and a contrast check of hover, selected, chart and disabled states |

## Retained installed-host evidence

The exact protected native bundle previously passed ordinary ACER review,
consume-once preparation/revocation, seven isolated-worker denials and four STOP
acknowledgements in 67/11/10/11 ms. The final strict audit left the service
Stopped/Disabled. Latest recorded bundle receipt:
.pi/qualification/20261106T1139159526512.

Earlier synthetic custody/restart/corruption/recovery and suspended-process
containment evidence has its own dated receipts. Those drills do not establish
real venue permissions, settlement or funded safety.
Repeat affected drills after native deployment, principal or security-policy changes.
This delivery changes Python research/startup and native test fixtures, not the
installed native service binaries or custody state.

## Validation and authority

Current regression and audit results have one owner: [system status](system-status.md).
Dependency-audit results are advisory-database snapshots, not certification.
Tests use explicit synthetic fixtures where appropriate; their outcomes are never
reported as actual venue orders or fabricated market evidence.

No positive funded loss budget exists. No automatic promotion, real order,
borrowing, transfer, paid provider dispatch or credential replacement is authorized
by a paper result or by this acceptance checklist.

See [current status](system-status.md), [the unified plan](implementation-plan.md),
[paper definitions](paper-qualification.md), and
[the integration runbook](controlled-integration-runbook.md).
