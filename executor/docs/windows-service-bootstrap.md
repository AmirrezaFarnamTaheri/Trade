# Windows Executor setup and qualification

The current host activates independent STOP and elevated provisioning/account-read
listeners. It remains **DISARMED, NOT CERTIFIED and without venue-write transport**.
SCM RUNNING means the host passed startup checks, not that a position is protected.

## Build and protected installation

Build every helper from the same reviewed revision:

    cargo build --release --locked -p exec-svc --bins

Choose the human operator account and an existing process from that operator's
actual logon. OperatorProcessId is checked against the OS token; do not copy a
claimed SID into configuration. From a separate elevated administrator console:

    .\scripts\windows\Install-ReadOnlyExecutor.ps1 -BinaryPath D:\GitHub\Trade\target\release\gym-executor.exe -OperatorAccount "$env:USERDOMAIN\ACER" -OperatorProcessId <operator-process-id> -WhatIf
    .\scripts\windows\Install-ReadOnlyExecutor.ps1 -BinaryPath D:\GitHub\Trade\target\release\gym-executor.exe -OperatorAccount "$env:USERDOMAIN\ACER" -OperatorProcessId <operator-process-id>
    .\scripts\windows\Test-ReadOnlyExecutor.ps1

Replace the angle-bracket example with the selected operator's numeric process ID.
The installer creates a **DISABLED** service under restricted LocalService,
protects Program Files code and ProgramData custody/ledger files, and grants the
selected operator only required stop/launcher execute rights. Existing
installations and reparse paths are refused rather than overwritten. Failed
installation remains disabled for inspection. Installation supplies no real key.

Binding a later operator logon is a separate administrator action through
Bind-ExecutorOperator.ps1, using the actual operator process token. The operator
cannot rewrite binding files, change SCM configuration, provision credentials or
invoke account reads.

## Credential custody and observations

The protected gym-provision helper requires an elevated administrator, pins the
installed SCM process and accepts only a protected, current-user-owned regular
secret file through --secret-file. The service encrypts bytes with its own DPAPI
identity and commits immutable custody metadata before acknowledging. Never pass
a key on a command line, put it in browser fields or retain it in diagnostics.

The administrator-only gym-account-read helper supports balances, fees and one
known-client-order ID. The service decrypts the current key and makes a bounded
HTTPS GET to the fixed Wallex origin. The helper emits RAW_UNPARSED, permission
UNVERIFIED and funded_authority=false. The Python service-source adapter validates
and sanitizes that envelope before optional observation-journal recording.
Neither GET success nor a venue status proves no-withdrawal permissions or settlement.

Restored custody history with missing or nonportable DPAPI ciphertext needs
explicit Invoke-ExecutorCredentialRecovery.ps1 with a protected -SecretFile.
Recovery accepts reprovisioning and STOP only, preserves history, rejects account
reads, then restarts normal DISARMED operation with startup still DISABLED.

## Runtime and recovery evidence

Use the installed-host drill only after reviewing its separate administrator
and operator stages. Synthetic custody must not be mixed with real credentials.
It is not a substitute for an independently budgeted venue test.

Required evidence includes actual AppContainer access denials, service-context
DPAPI provision/restart/corruption refusal/recovery, authenticated STOP within one
second during application/main-loop failure, retained-handle containment within
ten seconds, and a DISARMED restart. A standard account merely named worker
does not prove the AppContainer boundary.

The hosted-VM test covers its documented disposable SCM/ACL checks only. A local
WSL restore proves cross-OS portability on the same hardware; loss-of-machine
recovery still needs a separately controlled machine and credential reprovisioning.

See [current security status](service-security-status.md) and
[acceptance status](../../gym-core/docs/acceptance-status.md). Real venue
submission/cancel/reconciliation, trusted T1 approvals and certified protective
exits remain separate integration work. Do not use this service to protect a funded position.
