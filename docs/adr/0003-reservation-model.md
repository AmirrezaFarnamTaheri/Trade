# ADR 0003: Reservation model for funded orders

Status: Proposed (needs the money-path review before any funded work; finding A-6)

## Context

`exec-core` `ReservationBook::reserve` refuses a new hold when any hold for the same account and asset was
admitted against a different balance snapshot (`initial_available`), and a group is purged only when every
hold in it is released. Release requires `available + spent == initial_available + credits` exactly.
This is a deliberate fail-closed defence against double spending, and it is sound while nothing is funded.

It does not fit funded trading: while any hold in a group is pending, an order whose balance snapshot differs
cannot be admitted, so overlapping orders (TWAP slices, several markets sharing USDT) are refused; and a
one-quantum venue credit (dust, rebates) makes release fail and keeps the hold forever.

## Proposal

- Track per account and asset a running **committed spend** and the set of **active holds**, not a shared
  snapshot anchor. Admission checks `committed + active + request <= newest verified available`, with the newest
  observation per ADR 0002.
- Release a hold when its order is terminal and its fills are reconciled; move the settled amount into
  committed spend; a credit the venue adds is accepted within an explicit **tolerance class** per asset
  (for example one quantum, or the venue's documented dust rule) and recorded, never silently absorbed.
- Anything outside tolerance goes to an explicit RECONCILE state that blocks new entries for that asset.
- Wire `reserve_prepared_intent` and the review-v2 codec behind the disarmed gate, or mark them test-only.

## Validation required before acceptance

- A property test over random reserve / fill / credit / cancel interleavings that never overspends and never
  leaves a hold that can neither be released nor reconciled.
- A one-quantum external credit ends in either a tolerated release or RECONCILE, never a wedged hold.
- Replay of an existing journal under the new rules is either identical or explicitly migrated.
