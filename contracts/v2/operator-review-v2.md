# Offline native operator-review wire v2

**Status:** protocol-only / not deployed. This file specifies a future review
boundary for item 46. It **does not** create a service listener, money
reservation, venue request, credential path, or funded trading authority.

## Separation from v1

The original v1 operator-review pipe, helper, Python adapter, journal and
all historical receipts remain unchanged. A v1 request starts with
`TGREVW01` and a v1 reply starts with `TGREPLY1`. A v2 request begins
with `TGREVW02`; a v2 reply begins with `TGREPLY2`. The existing canonical
400-byte request, 432-byte reply and 352-byte ticket field layouts are
unchanged **apart from the frame magic**. All padding, positive
sequence/correlation, exact-unit and reply-to-request checks still apply.

A v1 parser rejects v2; a v2 parser rejects v1. A v2 receipt must be
correlated with its exact v2 request and must not be treated as a submit
capability. No endpoint currently serves the v2 magic. A future listener
would need a separately authorized OS principal, revocation and restart
tests before installation; automatic fallback from v2 to v1 is forbidden.

## Submit-side IDs versus historical read IDs

For a new v2 `approve` ticket or `prepare` action, `client_id` must
contain 1–64 ASCII letters, digits or underscores. Hyphens, periods,
spaces, non-ASCII, slashes and 65-byte IDs are rejected. `inspect`
and `revoke` still accept the v1 read-side grammar so observed legacy
venue IDs can be inspected and revoked; the existing v1 API is not
tightened retroactively.

Tests in `executor/exec-ipc/tests/operator_review_v2.rs` independently
check exact framing, noncanonical bytes, old/v2 cross-version rejection,
request correlation, ticket mismatch, and identifier boundaries.

## Remaining integration and acceptance

The previous Python `PaperSubmissionGate` records dry-run duplicate
and 20-proposals/10-seconds checks; that is **not** native service pacing,
real order idempotency or venue rate-limit proof. The v2 module is a codec
only. Native helper/client/pipe publication, separate token and Windows
ACL qualification, admitted order reservation, real retry/unknown-order
recovery, operator approval, authentic account/fee evidence, and an
explicit nonzero loss budget are all outstanding. The funded budget stays zero.

## Golden fixture

`fixtures/operator-review-v2.hex` holds one approve request and its reply for the
v2-valid ticket `New_01`. Rust generates and checks it
(`executor/exec-ipc/tests/operator_review_v2.rs`); Python checks that it shares the v1
layout apart from the magic and that its v1 codec refuses it
(`gym-core/tests/test_operator_reviews.py`). Changing the layout breaks both.
