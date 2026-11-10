# Runbook: "operator logon SID changed" (finding S-9)

The executor's stop pipe (T0) accepts only the operator logon session recorded in
`C:\Program Files\TradingGYM\Executor\stop-logon.sid`, plus the operator account in `stop-user.sid`. A logon SID
belongs to one Windows sign-in, so after you sign out and back in (or reboot) the stored value no longer matches and
T0 refuses your stop requests. That is by design: a stale binding must not keep working.

## Symptoms

- `gym-stopctl` reports access denied, and the Safety view shows the stop control as unbound.
- The service stops at start with a service-specific code from the 1001-1004 range, or the event log says
  `untrusted configuration file` (a SID file whose owner or permissions were changed; see below).

## Rebind (elevated PowerShell, signed in as the operator)

1. Stop nothing; the service keeps running DISARMED while you rebind.
2. Run `scripts\windows\Bind-ExecutorOperator.ps1` from an elevated prompt in your own interactive session. It
   first invalidates the stored binding, so an interrupted run cannot reuse the old logon, then records the current
   logon SID and operator SID, removes the previous operator's helper grants, and seals both files: owner
   Administrators, full control for SYSTEM and Administrators, read for the service SID, inheritance removed.
3. Restart the service (`Restart-Service TradingGYMExecutor`) so it reloads the binding.
4. Check: `gym-stopctl status` answers, and `gymctl doctor` shows no failing check.

## "untrusted configuration file"

Since S-9 the service checks each SID file's owner and DACL before reading it. Only SYSTEM, Administrators or
TrustedInstaller may own it or hold any write right on it. If the check fails, treat the file as tampered with:
do not loosen its permissions. Inspect it (`icacls <file>`), then run the binding script again to write a fresh,
correctly sealed file.
