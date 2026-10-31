# Workstream B1 — unified development status (2026-10-31)

**Current status: IN PROGRESS. Draft PR #10 against master. NOT protective.
NOT money-enabled.** The T2/private credential and authenticated venue
surfaces are not active. SCM service liveness does not prove protective exits.

## Implemented and test evidence

- Pure Rust stop-state core and a read-only, full-synchronous SQLite event
  ledger with exact-byte SHA-256 chaining, fail-closed tamper/replay tests.
- Fixed-size, versioned stop IPC codec, monotone atomic stop gate and Windows
  named-pipe **library** with explicit DACL/no remote clients. The named-pipe
  listener is **not hosted by the SCM service**.
- Restricted Windows LocalService SCM host and installer, registered disabled
  by default, with guarded code/data/SCM permissions.
- Disposable Windows-hosted CI [run 41215249615](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/41215249615)
  validated disabled install, binary/ACL checks, restricted token SCM start,
  and distinct local operator/worker stand-in accounts denied file/data/SCM
  privileged access; normal Rust Windows/Linux and Python tests green.
  These temporary accounts are NOT actual sandboxed research workers.
- Cargo.lock pinned; Rust CI uses cargo test --locked.
- Conservative read-only account observation projection in gym-core:
  balances/locked amounts remain separate from spendable authority;
  subaccount cash is not merged into main; unknown/manual order statuses
  never become proven fills/settlement; external exposure is not managed.
  The local API is token guarded and the bilingual Journal displays
  NOT_CONFIGURED by default. **Only explicit, injected sanitized test
  observations have been exercised. No Wallex private account read runs.**

## B1 exit criteria not yet met

- [ ] Provision/read **service-owned** credentials through a separate
      T2-authorized Windows pipe, prove service-context secret encryption,
      DACLs and negative attempts from operator/worker tokens (ARCH-01/04,
      OPS-01). No real key is stored or requested in this branch.
- [ ] Discover the actual operator logon SID from trusted OS state and
      host the stop pipe on an **independent thread**; add tray/gymctl client
      with STOP-REQUESTED vs ACKNOWLEDGED and hard-stop containment warning.
      Prove response under dead Python/UI/main loop, network SID exclusion,
      and <1s ACK on the operator's Windows target (ARCH-02, SEC-01, OPS-02).
- [ ] Build authenticated **read-only** Wallex balance/fee/order/margin/package
      clients and separate-account external-exposure projections; preserve
      pagination/freshness/errors, no unverified available cash (EXT-01).
      Key and account-bound behavior require venue authorization/probing.
- [ ] Replicate actual externally initiated manual order lifecycle events
      into the Journal: missing order not proof of fill/absence, status raw
      until verified, no double posting, fees/settlement shown truthfully.
- [ ] Verify a real restricted sandbox research worker cannot access any
      Executor pipes, credential store or funded ledger (SEC-02).
- [ ] Verify empty/stale/error/manual-order views in both languages and
      complete applicable acceptance mapping on a non-funded target machine.

**No live order creation/cancellation, no withdrawal, no funded arming.
All remaining work stays in the single draft PR #10** until acceptance.
Do not merge to master on the strength of a passing hosted CI workflow alone.
