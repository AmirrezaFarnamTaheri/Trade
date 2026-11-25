# Executor authority review and final fault checks

Root reviewed the complete native service path after integrating the two agent
branches. The agents reached their usage limits; this final pass is source review
and local fault verification, not an independent installed-host acceptance audit.

Two findings were corrected:

- An approval's synced write could outlive its freshness window. The controller
  now rechecks actual completion time after the write and before the gate CAS.
  The native host also rechecks owner evidence at that time. Slow writes, clock
  regression, STOP during commit, and failed writes leave the gate closed.
- The installation capital limit previously bounded outstanding holds only.
  Native buy admission now counts net own cash debits, existing quote holds and
  the new fee-inclusive hold. Sales can return cash; external deposits cannot
  enlarge this budget. Exact boundary, exceeded-budget and zero-budget behavior
  fail closed. Lowered/changed limits disarm existing approval.

The composed tests cover start/restart disarmed, policy changes, owner artifact
and claim binding, credential/runtime changes, stale or unequal balance pairs,
own activity between reads, late fills, partial durable copies, lost responses,
non-retry, terminal settlement and each kill input. The dedicated STOP path does
not wait for account networking. Full branch checks use Windows Python/native,
Ruff, complexity, Clippy, formatting and whitespace checks.

No protected binary was published, service installed, key permission certified,
owner attestation manufactured, or real order sent. A verified local release
bundle is prepared separately for review. Publication, installed-host fault
qualification and the registered 2027-02-08 prospective decision remain pending.
