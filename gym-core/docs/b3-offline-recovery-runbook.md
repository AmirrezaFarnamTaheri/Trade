# B3 offline recovery runbook (draft; not production acceptance)

This workflow is **not** a privileged scheduler, remote-backup system, production
updater, or approval to trade. Keep the Executor DISARMED. Never put credentials
or recovery passphrases in source control, CI variables, CLI arguments, environment
variables or chat.

## Manual encrypted archive

1. Require an independently checked, quiescent Executor database, with no funded
   authority, unresolved orders, or active ledger writer. The current Python
   utility cannot verify these authoritative service preconditions.
2. Mount an independently controlled removable/local volume and prepare a private
   directory with restricted permissions. Distinct filesystem device alone is
   **not proof** of an off-machine backup.
3. From a trusted interactive terminal in the gym-core directory, run:

   ~~~shell
   uv run gymctl backup-once PATH_TO_QUIESCENT_EXECUTOR_LEDGER PATH_TO_BACKUP_FOLDER --keep 7
   ~~~

   The prompt reads a unique recovery passphrase without echoing. Do not use the
   public synthetic CI passphrase. Keep the passphrase under a separate offline
   recovery procedure.
4. An exclusive encrypted bundle is created, decrypted into a temporary scratch
   destination and verified against its event sequence, SHA-256 ledger head,
   whole file digest and schema before old archives are pruned. Retention accepts
   2 through 365 bundles. An archive-creation or restore error keeps older files.
   Only ledger data is included, never secrets.dat.
5. Transfer the verified encrypted bundle to a genuinely independent off-machine
   location through an approved authenticated procedure; separately record the
   receiving machine, provenance, digest, event head, manifest authentication and
   retention evidence. The CLI does **not** perform that remote transfer.

## Recovery rehearsal on a second Windows machine

- No active Executor or existing destination ledger may be overwritten. Call
  gym.services.encrypted_backup.restore_backup on a clean target with a
  securely entered passphrase. Never copy original secrets.dat.
- Validate AEAD, exact event-chain head, stored bytes, sequence and a separately
  authenticated off-machine manifest. Existing receipt fields report
  trusted_origin=false: the passphrase does not establish provenance.
- Reprovision read-only venue credentials under the actual dedicated service
  principal only after B1 T2 service ACL and DPAPI acceptance. Startup remains
  DISARMED. Reconcile every ambiguous order from authenticated venue evidence.
- Capture actual independent-machine time, event count/head hash, ACL/negative
  probes, provenance proof and Health evidence for release review. The synthetic
  GitHub Ubuntu-to-Windows CI test does not satisfy this operational gate.

## Forward-only update / rollback

assess_migration_staging and assess_update are pure policy checks, not a trusted
privileged installer. Before applying a signed update, a service-owned release
controller must verify disarm, zero unknown orders, current ledger integrity,
independently rehearsed restore and a single forward schema step, with a
journaled operator authorization. Refuse all failed preconditions. Practice
rollback only on a copy; never downgrade a live append-only ledger in place.
Restart DISARMED and reconcile the venue before considering future authority.

**Not yet implemented:** automated privileged off-machine schedule/retention,
independent manifest attestation, real second-machine restore acceptance,
signed migration installation and rollback, and B1 service-owned credentials.
Do not close B3 or merge for funded trading on synthetic results alone.
