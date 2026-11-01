# Workstream C1 — read-only venue evidence (development slice)

This branch starts **C1** as specified in Master Specification §15.4.
It adds a local, **non-authoritative** `VenueFacts` evidence journal and
a truthful capability/status view in Health. It does **not** read private
Wallex endpoints using a key, initiate a probe order, or enable a funded mode.

## Offline workflow

1. An operator working outside TradingGYM obtains a sanitized, read-only
   observation from an authorized source. **Never copy a credential, raw
   authenticated response, session cookie, client secret or personal account
   detail into the evidence file.**
2. Save *only* the metadata envelope below in a UTF-8 JSON file on the
   workstation. `evidence_sha256` is the digest of the separately retained,
   properly redacted evidence. It is **not** an origin signature.
3. Run `gymctl --data data venue-fact-import <safe-metadata.json>`.
   The file must be regular, unsymlinked, and at most 16 KiB.
4. Open Health. The capability names and observation IDs are visible in
   English and Persian. There is no trade or certification action.

Example metadata (a **synthetic test**; never use the sample digest as proof):

```json
{
  "evidence_id": "demo-20261101-01",
  "observed_at": "2026-11-01T08:00:00Z",
  "source": "SYNTHETIC_FIXTURE",
  "kind": "BALANCES",
  "endpoint": "ACCOUNT_BALANCES",
  "state": "OBSERVED",
  "account_scope": "main",
  "response_version": "v1",
  "evidence_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

All fields are allowlisted. Values are limited to safe types and enumerations.
`source` is **caller supplied and unauthenticated**: `SERVICE_GET_REPORT`
does not prove that a service made a trusted call. Existing evidence IDs
cannot be reused to rewrite a past fact. The separate SQLite journal uses
full-synchronous writes, immutable row triggers, and a verified SHA-256 event
chain; this detects local edits but does not authenticate external provenance.

The private `GET /api/venue-facts` endpoint requires `X-Gym-Token` and
is no-store. It returns only sanitized metadata and an informational registry
with `funded_authority=false` for **every** capability. No submitted record
can turn an order, stop or Autopilot capability into a certified method.

## Missing acceptance (NOT production-ready)

- B1: actual T2 service-owned, no-withdrawal read credential, Windows
  identity/DPAPI/ACL and operator/worker negative acceptance.
- B2: durable money reservation/reconciliation and live venue transport
  safety; Fake Venue scenarios and installed-Windows SEC-02 evidence.
- C1: authorized, fresh Wallex private **GET** requests inside the
  credential-isolated Executor; order status/fee/pagination/shape tests
  against a real account; independent timestamped provenance and external
  exposure; a budgeted probe with explicit operator consent only after B.
- C2/C3: an actual service-issued approval, verified protective order,
  capped real conversion or Autopilot session and evidence of live
  reconciliation. Do not infer any of these from a Health display.

No API keys, funded POST, withdrawal calls or arming code are added here.
Keep all active PRs in draft until corresponding OS and venue acceptance passes.
