# Architecture decision records

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-authority-split.md) | Three runtimes, one kind of authority each | Accepted |
| [0002](0002-fail-closed-money-path.md) | The money path fails closed | Accepted (OD-5) |
| [0003](0003-reservation-model.md) | Reservation model for funded orders | Implemented, not wired |
| [0004](0004-bounded-startup-replay.md) | Bounded executor startup | Partly implemented |
| [0005](0005-shared-execution-kernel.md) | One execution kernel for research and the executor | Stages 1-3 done |
| [0006](0006-arming-and-fail-closed-custody.md) | Arm record, kill rules, fail-closed custody | Implemented, not wired |

A Proposed ADR changes money-path code and needs the pre-funding review before it is built.
