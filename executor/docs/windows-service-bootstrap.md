# Windows Executor — restricted, read-only SCM bootstrap

**Status: development-only / NOT protective / NOT funded.** This is a deliberately
incomplete B1 service-host milestone, not a deployable real-money system.

The Windows-only `gym-executor.exe` binary supports SCM lifecycle and verifies
its primary process user SID is **LocalService** (`S-1-5-19`) before it can
report RUNNING. It contains **no** venue credentials, IPC listener, order code,
stop guard wiring, trading ledger input or funding authority. SCM RUNNING only
means the no-op host process is alive; it does **not** mean that exits or
emergency stops are available. Do not run it while an account or position is
relying on TradingGYM for protection.

## Packaging (Windows build machine, after CI is repaired)

1. Obtain a trusted, reviewed source revision and build using a locked Cargo
   dependency graph (Cargo.lock is still missing and is a merge blocker).
2. Build `cargo build --release -p exec-svc --bin gym-executor` on Windows.
3. From an **elevated** PowerShell 5.1+ prompt, inspect then run:

   ```powershell
   .\scripts\windows\Install-ReadOnlyExecutor.ps1 -BinaryPath 'C:\staging\gym-executor.exe' -WhatIf
   .\scripts\windows\Install-ReadOnlyExecutor.ps1 -BinaryPath 'C:\staging\gym-executor.exe' -Confirm:$false
   .\scripts\windows\Test-ReadOnlyExecutor.ps1
   ```

   `-WhatIf` makes no changes. Full installation requires explicit
   administrator intent and creates only a **DISABLED** service, not a running
   one. The installer refuses existing installations for manual audit.

The installer places code beneath Program Files, data under ProgramData,
removes inherited ACLs on protected paths, grants only SYSTEM/Administrators
and the exact `NT SERVICE\TradingGYMExecutor` SID, and configures
`NT AUTHORITY\LocalService` with a **restricted** service SID. On an error,
the SCM service remains disabled; inspect/remove partial files manually.
Both scripts have Windows-only behaviors and require an isolated Windows VM.
The verifier examines the service name/account/start mode, protected ACLs,
broad groups and service SID, and fails closed. Its `sc qsidtype` parsing still
requires validation across localized Windows variants.

## Required before activation or B1 acceptance

- Windows build, syntax validation and end-to-end installer/rollback tests on
  non-production Windows VMs with clean and pre-existing installations.
- A first-class **service-SID membership** runtime check, token/ACL negative
  tests from the interactive user and sandboxed worker, and a `SEC-02` proof.
- Trusted, session-bound **operator logon SID discovery**. Never accept a SID
  claimed over IPC or a user-writable configuration file. The existing stop
  pipe library is intentionally **not** activated by this bootstrap.
- Install a dedicated emergency stop runtime that acknowledges within 1s even
  with the Python/browser/main loop dead; verify real OS pipe DACL, remote and
  hostile-client rejection and SCM hard-stop failure behavior.
- Separate T2 principal, provisioning, service-context DPAPI, key/ledger ACL
  self-tests, funded authority ceilings, independent recovery and Fake Venue.
- Fix GitHub Actions runner startup (issue #5) and require passing Rust tests
  on Windows and Linux; do not infer correctness from static source checks.

**No live order path, trade key or withdrawal capability is introduced.**
