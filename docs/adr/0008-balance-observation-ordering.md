# ADR 0008: Balance ordering by native service receipts

Status: Accepted, owner decision 2026-11-16. Supersedes the venue-sequence
requirement for balance admission in ADR 0006/0007. Implementation and protected
publication remain separate work; execution stays disarmed.

## Evidence and limit

The official [main-wallet response](https://developers.wallex.ir/docs/basic-services-main-wallet),
checked 2026-11-16, documents asset identity, value, locked amount and display
flags. It documents no balance sequence or exchange observation timestamp.
Requiring one would prevent this API from ever satisfying admission.

The native service can authenticate a GET response and order its own requests.
It cannot establish when the venue generated the snapshot or whether an upstream
cache returned an older one. Receipt order is explicitly a local ordering contract.
Two identical cached responses can still be old; the safeguards below reduce that
exposure without claiming to prove exchange freshness.

## Decision

1. **Conservative amount.** For each account/asset, spendable is the lower
   available amount in the last two eligible receipts, minus the executor's open
   holds. Available is exact value minus locked; underflow, unsupported precision
   or overflow refuses admission. Holds include waiting stops and unknown orders,
   whether or not the venue reports their funds as locked. Subtracting holds may
   conservatively count a venue lock twice; it must never increase spendable.
2. **Own-activity fence.** Any own order attempt that may reach the venue, cancel
   or newly observed fill invalidates earlier receipts. Both reads for a new
   admission must start after that activity and share the current activity fence.
   A fill discovered late invalidates the pair immediately. Unresolved order
   effects retain their holds and block admission until reconciled.
3. **Disagreement.** The service makes single-flight reads. Consecutive receipts
   at the same activity fence must agree on exact account/asset amounts and locks.
   A disagreement blocks and disarms; it is not averaged away. An intervening own
   activity discards the pair and requires two new reads. Recovery requires clean
   reconciliation, a fresh agreeing pair and a new privileged approval.
4. **Age.** Both receipts must be at most 120 seconds old, and no older than a
   stricter owner policy. Missing, future-dated or regressing local clocks refuse
   admission. Restart, credential change, STOP and privileged faults invalidate
   approval; a new runtime cannot reuse a previous runtime's pair.
5. **Honest names.** The field in available.rs is receipt_seq. It is issued by the
   one native producer; it is never described as an exchange/venue sequence.

Only the native service constructs trusted balance receipts. Browser values,
research imports and Python DTOs do not confer balance authority. Each receipt
binds the credential generation, runtime epoch, activity fence, request identity,
local read clocks, exact asset units/amounts and response digest. Matching copies
must commit durably in both credential and execution journals before use. A
partial commit, copy mismatch, malformed payload or failed read leaves no permit.
Receipt validation and reservation commit run under the journal owner; an
intervening activity/STOP/epoch change is rechecked before transport.

## Order and trade cross-checks

The current [order-detail reference](https://developers.wallex.ir/docs/spot-single-order-detail)
documents created_at, updated_at, transactTime and each fill's timestamp. The
[order-list reference](https://developers.wallex.ir/docs/spot-order-list) exposes
the same event fields. These can cross-check known order activity and detect
regressions in a reconciled order's history. They do not timestamp a balance read
or provide a shared revision connecting orders and balances.

The earlier live check recorded own-trade id, isMaker and clientOrderID from
GET /v1/account/trades; the older response reference also describes timestamp.
The current public docs reviewed here do not establish a globally monotone
account-trade ID or a balance revision. Do not infer balance order from IDs or
claim this endpoint was freshly exercised as part of this documentation check.

## Remaining boundaries

Venue funds checks help reject uncovered orders, but do not prove that stale
reads are harmless for sizing, exposure or duplicate effects. Keep the hold book,
unknown-order refusal, the 10-USDT per-order cap, two-open-order cap, 50-USDT loss
cap and all independent kill/preflight rules. The prospective paper checkpoint
is unchanged. No off-machine backup or second-host restore is required by this
decision; the owner canceled those jobs. Existing local backup checks remain.

Before publication, test the composed native producer, dual journal commits,
admission and privileged arm/STOP path against stale/unequal reads, own activity
between reads, late fills, replay, restart, partial commits and every kill input.
This ADR authorizes the receipt-based redesign, not funded orders or installation.
