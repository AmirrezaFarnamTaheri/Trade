# Native order reconciliation and settlement

The native observer now advances known reviewed orders from native receipts and
releases a terminal hold only after two later, matching, dual-committed balance
reads. It requires complete exact fills, each actual venue gross `sum`, recognized
fee assets, the reviewed limit price and cash envelope, current credential/runtime,
and zero outgoing-asset locks. Missing evidence keeps the hold and blocks arming.

Close and release are one hash-chained journal event and one SQLite commit. Both
the new sell-fee hold and this settlement event retain old byte interpretation
for earlier journal formats. Proven unsent crash leftovers can be abandoned;
an uncertain send cannot be abandoned or retried. External credits do not wedge a
fully evidenced release and cannot reduce the own-fill loss calculation.

Open-order pages are matched by identity, status and exact cumulative quantities.
An omitted empty fill list or equivalent decimal spelling does not invent a
fill change. Detailed economic evidence comes from the native known-order read.
Actual fill gross cash is preserved in new receipts; older sanitized receipts
remain replayable. A nonzero fill lacking its actual gross cash cannot settle.

Synthetic composition regressions cover full and partial buy settlement, outgoing
base fees on sells, restart, locked/stale/context-mismatched balances, missing gross
cash, invalid atomic settlements, proof of an unsent request, and preservation of
uncertain liabilities. Venue rounding and sparse zero-fill pages have regressions.
Full branch logs are under `.pi/change-split/checks/native-order-settlement/` locally.

No venue order, protected publication, owner attestation or real arming occurred.
The registered 2027-02-08 checkpoint and installed-host qualification remain pending.
