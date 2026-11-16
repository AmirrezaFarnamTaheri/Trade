# Architecture decision records

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-authority-split.md) | Three runtimes, one kind of authority each | Accepted |
| [0002](0002-fail-closed-money-path.md) | The money path fails closed | Accepted (OD-5) |
| [0003](0003-reservation-model.md) | Reservation model for funded orders | Wired in source; host qualification pending |
| [0004](0004-bounded-startup-replay.md) | Bounded executor startup | Source and scale checks complete; host qualification pending |
| [0005](0005-shared-execution-kernel.md) | One execution kernel for research and the executor | Stages 1-3 done |
| [0006](0006-arming-and-fail-closed-custody.md) | Arm record, kill rules, fail-closed custody | Wired and locally fault tested; installed service disarmed |
| [0007](0007-wiring-the-funded-path-behind-an-arm-button.md) | Native funded path behind elevated owner approval | Source complete; publication and qualification pending |
| [0008](0008-balance-observation-ordering.md) | Native balance receipt ordering | Accepted and implemented in source; no venue-sequence claim |

A Proposed ADR changes money-path code and needs automated contract/security checks before delivery.
