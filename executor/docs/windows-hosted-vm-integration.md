# Disposable Windows VM integration gate (B1, read-only only)

This workflow exercises the **actual** Windows SCM and effective NTFS/SCM ACLs
on a fresh **GitHub-hosted Windows runner**, never on a workstation or an
attached trading machine. The script immediately refuses non-GitHub Actions,
non-Windows, and self-hosted runners. The workflow job runs on trusted repository
**push** events only, not pull requests from forks, with contents: read.

Execution steps:

1. Build gym-executor.exe with cargo build --release --locked and refuse a
   pre-existing TradingGYM service or installation directory on the runner.
2. Verify that the installer -WhatIf makes no changes. Register the read-only
   service DISABLED, compare binary SHA-256, run the elevated service/ACL audit.
3. **Temporarily on this disposable VM only**, switch this no-op, no-secret,
   no-venue service to manual startup, start it via SCM to exercise its
   LocalService/restricted-service-SID token guard, then stop it and restore
   DISABLED. If the service cannot report RUNNING, the test fails.
4. Create two distinct randomly named local **standard-user** accounts (operator
   and worker *stand-in*), with one-use passwords held only in process memory.
   Under each real OS token, attempt file read/overwrite, private-data creation
   and privileged SCM handle access using Test-UnprivilegedExecutorAccess.ps1.
   Each request must be denied with Win32 ACCESS_DENIED (5); unexpected errors
   and granted access fail the job. Test results and return codes are checked.
5. In finally, stop/disable/delete only the service installed by the test,
   remove the two test users and the test's private directories. If a previous
   installation is present, the test stops **without deleting it**. Cleanup
   errors also fail the job.

The job has a 15-minute timeout, requires an elevated GitHub-hosted runner,
and uses no venue credentials, trading endpoints, funded actions or persistent
secrets. Successful CI is evidence for **these specific installer, service-
identity and two-principal OS access checks**, not proof of real operator session
binding, actual worker sandbox containment, authenticated stop-pipe access,
sub-second STOP availability under a hung Python/UI process, backups, T2 or
real-money readiness. Those B1 gates remain open. Do not run this test on a
funded or non-disposable host.
