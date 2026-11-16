# Native arming runtime source verification

This branch connects the elevated arm helper to the native service. It does not
install or arm that service, create an owner attestation, or place a venue order.

The listener checks the elevated caller's Windows user and logon against the
protected operator identity. Approval binds the current gate revision, policy,
evidence, credential generation and runtime. A synced, create-new approval receipt
precedes the gate transition; a concurrent stop or failed write leaves it closed.
An unacknowledged approval disarms. Restart never restores authority from that receipt.

The service polls fixed-origin public books and native authenticated account reads.
Risk uses complete own-order fills, current fees, and a matching complete open-order
page. Deposits cannot offset its loss measure. Balance pairs remain native and
dual committed; credential changes invalidate their context immediately. Polling
does not replace a completed receipt until both new copies commit. Own-order changes
invalidate the balance fence and disarm.

A separate safety worker checks source freshness, policy and owner artifact bytes,
limits and both independent journal audits. Audit failure or worker failure stops
the host. The dedicated stop listener remains independent of the vault and network.
Local backup bundles contain verified journal copies, sealed ciphertext, and a tip
receipt; there is no schedule, off-machine copy, or second-host restore.

Regression coverage includes approval-write failure, a halt during the write,
worker fault preserving HALT, hostile public symbols, receipt context rotation,
and the existing authority, receipt-copy, stale-data and expiry cases. Full branch
check logs are under `.pi/change-split/checks/native-arm-runtime/` locally.

The reviewed admission and venue-effect consumer are the next source step. These
native measurements do not qualify an installed service, prove key permissions,
or establish a trading edge. The registered 2027-02-08 prospective checkpoint is
still required; no real approval evidence is manufactured before it.
