# Workstream B1 — service security status (2026-11-06)

**IN PROGRESS. DISARMED. NOT CERTIFIED. NOT protective or money-enabled.**
A compiled service, successful GET or acknowledged STOP does not establish certified venue exits.

## Implemented locally

Current installed result (13:24 Asia/Tehran): ordinary ACER review, consume-once
preparation, duplicate refusal, inspection and revocation passed. The actual R0
worker was denied all seven private targets and four STOP acknowledgements took
10–85 ms. The complete known-order receipt bundle is installed, the strict audit passed, and the
service is stopped/disabled. Zero-budget metadata was recorded/read back without
an account API or order call. Receipts:
`.pi/qualification/20261106T0954273200041`. An earlier attempt refused a stale
Windows logon; the administrator helper rebound the actual current ACER process
before the successful fresh run. Custody corruption/recovery and venue behavior on
the new bundle remain unverified.

Ordinary review holds the SCM service handle and validates the fixed image/account,
running PID and connected pipe server identity before/after exchange. It does
not request access to the protected process object. Administrator hard containment
continues to hold and verify the actual process object.

- Existing-install publication has an explicitly hash-pinned complete bundle, retained old-code backup, reverse-order rollback and marker-based startup refusal before listeners (1019). The updater never starts the service or changes custody/journals. Rebinding includes the review helper and removes the previous operator's explicit grants. Publication/operator-protocol self-checks and the installed test above passed. See [service publication](service-publication.md).
- The `prepare` review operation consumes a review once into durable preparation, rechecking service-supplied actor/logon/runtime/key generation and current limit/expiry/mode. The consumed marker and immutable exact ticket reference commit together; no executable order/reservation is created. Restart or lost acknowledgement cannot permit repeat preparation; revocation remains possible. Worker publication/preflight includes the operator pipe as a seventh denied target; actual R0 denial passed. Isolation-drill startup exposes it for negative probes and refuses all review operations.
- Separate OS-user/logon-authenticated operator review pipe and SCM-pinned `gym-review` helper record/revoke exact intent in the protected execution journal. Payloads bind units, current runtime/limit/key generation, expiry and evidence digests. The CLI and token/same-origin Operate relay have no order transport or trading capability. Installed review/preparation/revocation passed; executable admission, arming and money-path limit enforcement remain open. See [operator review](../../contracts/v1/operator-review-v1.md).

- Administrator-only `gym-ceiling get|set` records exact currency/unit-epoch/precision and capital in the protected `Vault/exec_ledger.db`. Stale updates, changed unit/operator bindings and operator-account increases are rejected. Actual T2 identities come from the connected Windows token. The existing journal is retained. Installed zero-budget recording/readback passed; the metadata is not enforced by a real money path and grants no trading authority. See [installation capital limit](installation-ceiling.md).

- Restricted LocalService SCM host, disabled-by-default installer, protected code/data/SCM ACLs and exact-byte SHA-256/FULL-synchronous SQLite journal. All B1 draft PRs were merged earlier; this is not an unmerged PR #10 status report.
- Independent authenticated STOP pipe/thread, network-client exclusion, fixed bounded codec and monotone stop gates. The client checks protected SCM and connected-pipe server identity before writing, and the server binds the selected operator's real OS user/logon token rather than trusting a supplied SID.
- Explicit `Bind-ExecutorOperator.ps1` for the selected interactive process. Binding files and helpers have protected ACLs. Normal operators may execute STOP/hard-stop helpers, not the provisioning/account-read helpers or credential/data files.
- Elevated hard-stop helper retains and revalidates the SCM process handle, imposes a ten-second deadline and reports explicit UNPROTECTED containment. It does not manufacture venue-side protection.
- Separate elevated-admin provisioning pipe, actual impersonated-token admission, user-scope service DPAPI encryption/decryption, immutable ACL-protected ciphertext generations and typed durable metadata before acknowledgment. No key bytes enter the ledger or diagnostic logs.
- Explicit **SCM-only recovery startup** for valid restored custody history whose current ciphertext is missing/nonportable. It preserves ledger history and root/ACL/reparse validation, permits only reprovisioning/STOP, rejects account reads and exits after durable replacement. The admin recovery wrapper restarts normal DISARMED operation; no silent recovery downgrade or history deletion.
- `gym-account-read balances`, `gym-account-read fees`, `gym-account-read known-client-order <id>`: the service decrypts the current key and makes fixed-origin HTTPS WinHTTP GET requests. Redirects, proxy/auth negotiation, request bodies and arbitrary URLs are disabled; bodies, headers, time and identifiers are bounded. STOP remains separate. The helper authenticates the SCM-pinned server and emits hex-encoded **RAW_UNPARSED** observation bytes with `funded_authority=false`.
- `gymctl account --source service --record` now validates the protected helper's bounded envelope with the shared exact-decimal/identity parsers and atomically records sanitized account snapshots, fees and order changes. The existing token-protected account API reads the latest snapshot. Interactive-user reads remain a separate source. Transport labels remain UNVERIFIED observations, never proven fills, settlement or spendable cash.
- The installed-host drill and protected existence manifest cover synthetic custody/recovery, a parked main loop, actual worker/profile-canary denial probes and suspended-process containment. The worker installer targets the explicitly selected ordinary operator; profile initialization runs from that operator's unelevated logon.

## Verified versus external

The previously qualified protected binary set now passes installed synthetic
provision/restart/corruption refusal/recovery with retained custody history.
Actual ACER AppContainer child denied all six existing private targets and
returned exactly three R0 tools. Operator STOP acknowledgements took 12–17 ms;
retained-handle suspended-process containment took 1,037 ms. Normal restart
completed, then the service was stopped and disabled. Receipts are in
`.pi/paper-qualification/custody-continuation.json`, `operator-20261105.json`
and `containment.json`.

The current source additionally implements fixed GET open/history pages and
durable offline cancellation evidence, with all-target tests, strict Clippy and
release build. These new binaries are installed; current ordinary review,
seven-target worker denial and STOP tests passed. Current custody recovery and
venue behavior were not requalified.
They do not add real order transport or certified protection. The failure history
below records earlier attempts and is superseded only for the qualified set.

Local unit tests, offline Windows builds, helper refusal probes and PowerShell parsing have passed for the implemented slices. Their exact integrated counts live in [acceptance status](../../gym-core/docs/acceptance-status.md). Source/token checks are not a successful installed-service round trip.

The ACER operator's no-capability AppContainer profile was initialized locally.
The isolated runtime/public snapshot package passed a local startup self-check.
An earlier administrator prompt was canceled; the later approved attempt installed
the protected read-only service and passed its disabled/stopped ACL/path audit.
Synthetic custody provisioning returned **NOT_ACKNOWLEDGED**. Custody/recovery,
actual worker denial, independent STOP and hung-service containment remain
**NOT PASSED**. These preparation steps do not satisfy the installed-host gates.

On 2026-11-04, administrator-only read inspection confirmed the service stopped
and disabled (exit code 5), an intact zero-event credential ledger and no encrypted
credential generation. The ledger and lock file were preserved. No secret content
was read, service started, ACL changed or credential replaced. The helper now
preserves the fixed client/OS failure reason and distinguishes timeout from
disconnection, but this updated diagnostic is not installed. The original failure
stage is still unknown; zero current events do not establish successful custody.

Historical hosted Windows [run 41215249615](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/41215249615) checked an earlier disabled service install, ACLs/restricted token and ordinary disposable-account denials. Those accounts were **not** actual sandboxed research workers; that run cannot certify the newly added pipe/vault/read/recovery code.

## B1/B2 exit gates still open

- [x] Qualify the previous protected binary set under the selected ACER account/logon: synthetic service DPAPI provision/restart/corruption/recovery passed with retained history and no real key.
- [x] Install the current page/order-receipt/codec bundle and repeat ordinary-operator, seven-target isolation and STOP checks. Actual protected account GET responses and custody corruption/recovery remain unqualified.
- [ ] Verify the key's actual venue permission contract. Provisioning and GET deliberately retain **UNVERIFIED**; successful reads never satisfy SEC-03 by themselves.
- [ ] Exercise actual service-owned balances/locked exposure and known manual-order lifecycle; normalize observations without inventing absent fills or settlement. Connectivity, pagination, margin/package availability and freshness remain unverified.
- [x] Run the actual constrained child against STOP/T2 pipes, current custody files, operator-profile canary and SCM; all were denied. The future funded ledger still needs its own real-file probe once implemented.
- [x] Measure independent STOP under the parked main loop and retained-handle containment under a suspended service on ACER; measured deadlines and DISARMED startup passed for the qualified set.
- [ ] Verify an isolated restore, exact ledger chain and DISARMED startup. Service-owned DPAPI credentials must be reprovisioned when required, never exported as plaintext.

Trusted-path T1/funded order transport, live reconciliation and certified protective exits remain missing integration code. No live order creation/cancellation, withdrawal, funded arming or capability promotion is enabled or claimed.
