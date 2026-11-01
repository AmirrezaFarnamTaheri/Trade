# Windows Executor — restricted, read-only SCM bootstrap

**Status: development-only / NOT protective / NOT funded.** This is a deliberately
incomplete B1 service-host milestone, not a deployable real-money system.

The Windows-only `gym-executor.exe` binary supports SCM lifecycle and verifies
its primary process user SID is **LocalService** (`S-1-5-19`) *and* the
OS-derived `NT SERVICE\TradingGYMExecutor` service SID is present as both an
enabled token group and a restricted token SID before it can report RUNNING.
The SID is resolved with Windows `LookupAccountNameW`; the group/restricting
lists are read from the process token with `GetTokenInformation`, not from a
user-writable configuration or a claimed IPC identity. Failure results in
SCM STOPPED/access-denied, not a fallback identity. It contains **no** venue credentials, IPC listener, order code,
stop guard wiring, trading ledger input or funding authority. SCM RUNNING only
means the no-op host process is alive; it does **not** mean that exits or
emergency stops are available. Do not run it while an account or position is
relying on TradingGYM for protection.

## Packaging (Windows build machine, after CI is repaired)

1. Obtain a trusted, reviewed source revision and build using a locked Cargo
   dependency graph (the repository now tracks a generated `Cargo.lock`; CI runs with `--locked`).
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
removes inherited ACLs, sets protected-path ownership to Administrators,
grants only SYSTEM/Administrators and the exact `NT SERVICE\TradingGYMExecutor` SID, and configures
`NT AUTHORITY\LocalService` with a **restricted** service SID. On an error,
the SCM service remains disabled; inspect/remove partial files manually.
Both scripts have Windows-only behaviors and require an isolated Windows VM.
The installer now also sets a **protected SCM service DACL**: SYSTEM and
Administrators have full control; authenticated users can query service
configuration/status only, never change configuration, start, stop, pause,
delete, or change service permissions. The elevated verifier checks the
service descriptor and file ACLs independently; its `sc qsidtype` parsing still
requires validation across localized Windows variants.

## Required negative probes, two separate standard Windows identities

On an isolated Windows test VM, after an explicit disabled-only install and an
**elevated** `Test-ReadOnlyExecutor.ps1` pass, run these commands from an
**unelevated** PowerShell session for the ordinary operator account:

```powershell
.\scripts\windows\Test-UnprivilegedExecutorAccess.ps1
```

Then run the same command under the separately restricted **research/worker**
principal. The script refuses an elevated administrator token, checks that the
service is still DISABLED and STOPPED, and uses real OS access attempts to
prove that these principals cannot read/write the executable, create files in
the private authority data directory, or open SCM handles with START, STOP,
CHANGE_CONFIG, PAUSE, DELETE, WRITE_DAC or WRITE_OWNER authority. Service
query-status remains intentionally readable. The only filesystem mutation
attempt creates a uniquely named harmless canary; if a misconfiguration allows
it, the script attempts cleanup and **fails** the security check.

Record the user SID, token groups, service DACL and output from **both** runs.
Neither a static Python check nor an administrator-run audit can substitute
for these two real Windows negative probes. Do not install on a funded machine.
The independent named-pipe, T2 and credential-denial checks from ARCH-01,
ARCH-02, ARCH-04, SEC-01/02 remain outstanding; these SCM/NTFS probes do not
certify those gates.

## Required before activation or B1 acceptance

- Windows build, syntax validation and end-to-end installer/rollback tests on
  non-production Windows VMs with clean and pre-existing installations.
- **Real Windows proof** of the new runtime service-SID membership check,
  including wrong service SID, missing restricted SID and token-query failures;
  Windows Rust tests and an installed-service negative test are pending.
  Also perform token/ACL negative probes from the interactive user and sandboxed
  worker, plus a separate `SEC-02` proof.
- Trusted, session-bound **operator logon SID discovery**. Never accept a SID
  claimed over IPC or a user-writable configuration file. The existing stop
  pipe library is intentionally **not** activated by this bootstrap.
- Install a dedicated emergency stop runtime that acknowledges within 1s even
  with the Python/browser/main loop dead; verify real OS pipe DACL, remote and
  hostile-client rejection and SCM hard-stop failure behavior.
- Separate T2 principal, provisioning, service-context DPAPI, key/ledger ACL
  self-tests, funded authority ceilings, independent recovery and Fake Venue.
- GitHub Actions runner-startup issue #5 has been resolved and the Rust/Python
  CI checks run on hosted Windows and Linux. This verifies the testable code,
  **not** installed Windows SCM/ACL/operator/worker security integration.

**No live order path, trade key or withdrawal capability is introduced.**

The source contains a fail-closed token-membership gate and Rust policy tests.
Hosted Windows CI builds and runs compiled tests; this development container
still lacks a Rust/Windows toolchain. Static Python source guards and Windows
compilation **do not** prove installed-service identity isolation. A clean-VM
service launch, OS-token membership evidence and hostile-user/worker ACL audits
remain mandatory before B1 acceptance. The service remains DISABLED by default.
