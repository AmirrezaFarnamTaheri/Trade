# ADR 0002: The money path fails closed

Status: Accepted (owner decision OD-5, 2026-11-09)

## Context

The privileged executor thread (T2) holds custody and the journals. An uncertain journal commit, a venue
observation that may be stale, or two journals that disagree all leave the executor unsure what it owns.

## Decision

- A fault in the privileged thread stops the whole service, which ends in the stopped state with a phase code.
  A restart comes up DISARMED. Keeping the STOP pipe alive past a privileged fault is not attempted.
- Reservation uses only the newest account observation of the same resource, and refuses one older than a fixed
  bound. Freshness is checked per resource (balances and fees do not block each other) since 2026-11-09.
- Every observation read and write goes through one authority whatever the file split; if the two vault
  journals disagree, the executor blocks and disarms.

## Consequences

- Availability is traded for certainty: a recoverable fault still stops the service. Splitting recoverable from
  fatal errors is a later change (see ADR 0004) and must not weaken the uncertain-commit stop.
- Tests to add with the funded work: a forced privileged fault stops the service and restart is disarmed; a stale
  observation blocks; a journal disagreement blocks and disarms.
