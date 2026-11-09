# Disaster recovery

One laptop holds the collector, the research data and the protected executor. This page lists what is lost
with it, what brings it back, and how to prove the backups work before they are needed.

## What must exist before a loss

| Item | How | Check |
|------|-----|-------|
| Research data backup | `gymctl backup-research <folder>` nightly via `scripts/windows/Install-ResearchBackupSchedule.ps1` | `gymctl doctor` shows `research_backup` under 36 h |
| Executor ledger backup | `gymctl backup-once` nightly via `scripts/windows/Install-BackupSchedule.ps1` | Backups page receipt; `ledger-anchors.jsonl` grows in the backup folder |
| Backup passphrase | `gymctl key set-backup` seals it on this machine | A copy kept **off** this machine (password manager or paper) |
| Update signing key | `gymctl release-keygen` on another machine | Private key and passphrase kept offline |
| Wallex API keys | Not backed up by design | Re-create on Wallex after a loss; they expire within 90 days anyway |

The backup folder must be on another drive or a cloud-synced folder. A copy on the same disk does not survive
the disk.

## Drills (do these before trusting the backup)

1. `gymctl research-restore-drill <folder>` decrypts the newest snapshot and the newest raw segments into a
   temporary folder and verifies every database and hash. The nightly schedule already runs it after each
   backup; run it by hand after changing the destination.
2. `gymctl restore-drill <folder>` does the same for the executor ledger and checks it against every anchor.
3. Once a quarter, rebuild a data root on a clean folder and check it:

       gymctl restore-research <folder> --to D:\restore-test\live
       gymctl --data D:\restore-test doctor

   Record the time it took; that is the recovery time for the research store.

## After losing the laptop or its disk

1. On the new machine: install uv, Node 22+ and Rust as in the root README; clone the repository; `uv sync`.
2. Restore research data into an empty data root:
   `gymctl restore-research <folder> --to <repo>\data\live`, then `gymctl doctor`. Expect `PASS` for the
   databases and segments; `research_backup` will warn until the next backup runs.
3. Seal the backup passphrase again (`gymctl key set-backup`) and reinstall both backup schedules.
4. Executor, only if it was installed: install the signed bundle (executor README), pin the update key,
   restore the ledger with `gymctl restore-backup <bundle> <new ledger path>`, and confirm the service stays
   **DISARMED / NOT CERTIFIED**. Credentials are host-bound (DPAPI) and must be re-provisioned; they are never
   restored from a backup.
5. Create new Wallex API keys and store them with `gymctl key set read|trade`.
6. Start the workspace (`scripts/windows/Start-Workspace.ps1`) and confirm `gymctl doctor` is clean.

## What is not recoverable

- Market observations from the gap between the last backup and the loss. Wallex keeps only candle history, so
  order-book and trade ticks from that gap are gone; the collector records the gap as missing.
- Anything protected only by the old machine's DPAPI: provider credentials in the model gateway and the
  stored Wallex keys. Re-enter them.

## Acceptance status

The host-instance rebuild can be rehearsed on a disposable VM; the physical-hardware row stays open until a
second machine exists. See `acceptance-status.md`.
