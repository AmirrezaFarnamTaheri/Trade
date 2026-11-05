# Updating the protected service without replacing custody

`scripts/windows/Update-ReadOnlyExecutor.ps1` publishes an explicitly selected,
complete binary bundle to an existing **stopped, disabled** installation. This
does not start the service, read credentials, call an account API, arm trading,
reset journals or qualify the new runtime. An elevated administrator is required.

The bundle contains exactly these names: `gym-executor.exe`, `gym-stopctl.exe`,
`gym-hardstop.exe`, `gym-provision.exe`, `gym-account-read.exe`, `gym-ceiling.exe`,
`gym-review.exe` and `gym-research-worker.exe`. The bounded manifest has one line
per member: its SHA-256 hex digest, two spaces and its exact lowercase filename.
Unknown names, duplicates, missing members and paths in filenames are refused.
This manifest pins explicitly reviewed bytes; it is not publisher signature
verification or an unattended-update authorization.

Run the updater with absolute `-BinaryDirectory` and `-HashManifest` paths from
the administrator console. It checks the fixed SCM image/account and stopped,
disabled state, existing code/data ACLs and parent mutation permissions. Migration
preflight permits only the previously absent ceiling/review helpers; its output
is explicitly not installed-host acceptance. Existing helper permissions remain
mandatory, and a normal final audit requires the complete new bundle.

Source executable handles deny writing/deleting while their hashes are checked
and bytes copied. Bounded Windows executable headers are required. All files are
staged, flushed and hashed again before publication. An administrator-only backup
directory retains prior code and a sanitized receipt. A flushed `update.pending`
marker precedes replacement, and the executor image is replaced last. Each file
replacement retains old bytes. Helpers receive the same narrow service/operator
permissions as the installer; T2 helpers remain administrator-only.

The new service refuses startup with stable error **1019** whenever that marker
exists, before creating listeners. The normal installation audit refuses it too.
An ordinary process cannot remove the marker from the protected code directory.
The updater removes its own marker only after the publication audit, then runs
the strict audit. On failure it attempts reverse-order rollback, retains failed
new bytes and records the result. Failed rollback leaves the marker in place and
requires manual administrator recovery. It never tries to start a partially
updated service or automatically downgrade journal contents. A power failure or
concurrent administrator intervention still requires inspection; local file
replacement checks are not crash or hardware qualification.

`Bind-ExecutorOperator.ps1` now includes `gym-review.exe`, invalidates the old
logon before changing helper permissions, and removes the previous operator's
explicit helper grants when selecting another account. It retains custody and
still requires the executor stopped and disabled.

## Qualification

`Update-ReadOnlyExecutor.ps1 -SelfTest` checks strict manifests, pinned source
access, real temporary-file replacement and retained-byte rollback without
touching the installed service. Native regressions check that a file or directory
at the marker path prevents startup, and source contracts check the veto precedes
listeners. These are local checks, not proof of a successful installed update.

`Test-ExecutorOperator.ps1 -SelfTest` checks exact unsigned 64-bit values, native
request layout and correlation refusal without invoking a helper. Its ordinary
operator mode requires the fixed administrator-protected
`operator-qualification.json`, a recent matching service PID, selected OS user
and an exact zero capital budget. Given a new `-ReportPath`, it records a clearly
synthetic SELL intent, prepares it, checks duplicate refusal, inspects it and
revokes it. The ticket is not a holding or instrument observation. It then runs
the actual AppContainer seven-target denial probe and four STOP commands. It
makes no private exchange request. A supervising administrator must stop and
disable the service afterward; this script cannot change SCM configuration.

The installed test passed on 2026-11-05 at 15:05 UTC under the ordinary ACER
logon. Receipt directory `.pi/qualification/20261105T1505191135205` retains both
administrator and operator reports. The exact synthetic intent was recorded,
prepared once, refused on duplicate preparation, inspected and revoked. The
actual R0 child was denied all seven existing protected targets. STOP status,
pause, exit-only and halt acknowledged in 84, 12, 11 and 11 ms respectively.
The supervising administrator stopped and disabled the service, and the strict
installation audit passed. No account API or exchange order was called, and the
installation capital budget was exactly zero.

The installed test exposed a helper permission bug: an ordinary operator cannot
open the protected service process object. Read-only review now holds the SCM
service handle, validates its fixed image/account and running PID, and checks the
connected pipe's kernel-reported server PID before and after exchange. It never
requests process/debug/termination rights. Administrator hard containment still
pins the actual process object. The earlier failed attempts remain recorded;
they do not qualify any runtime. This result does not requalify custody recovery,
venue exits, crash recovery or a different machine.
