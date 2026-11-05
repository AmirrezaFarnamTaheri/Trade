# Installation capital limit

The service now records an administrator-controlled installation capital limit.
It remains **DISARMED / NOT CERTIFIED**. Recording a limit does not create an
operator approval, arm a session, certify a method or permit a venue order.
Real money-path enforcement and authenticated venue reconciliation remain missing.

## Protected console

After installing and qualifying the reviewed build, run the fixed helper from
an elevated administrator console:

```powershell
& "$env:ProgramFiles\TradingGYM\Executor\gym-ceiling.exe" get
```

The response reports `UNSET` with sequence zero, or the exact current amount,
currency, unit epoch, decimal precision and committed sequence. It always reports
`ceiling_protection: UNQUALIFIED` and `funded_authority: false`. The browser's
Safety page explains this console workflow; it cannot read or raise the limit.
A read of an unset limit does not create the execution ledger.

The setter's exact syntax is:

```text
gym-ceiling set CURRENCY UNIT_EPOCH DECIMALS AMOUNT EXPECTED_SEQUENCE
```

All fields are required. The amount is nonnegative plain decimal text, with at
most the explicitly declared precision and no rounding or exponent notation.
`UNIT_EPOCH` is an explicit positive integer, not a currency conversion factor.
The existing market model uses epoch 1 for its current toman unit; that does not
authenticate future venue units or choose the administrator's limit.
Use the sequence returned by `get`; a stale sequence is refused. A missing
acknowledgement means the change may have committed. Read status before any
manual retry; the helper never retries a mutation automatically.

The configured operator account cannot increase the limit, even with an elevated
token. It can record zero or reduce a current limit through this administrator
channel. An increase requires an authenticated administrator with a different
user SID. Currency, unit epoch, precision and configured operator identity cannot
be changed through this setter once recorded. Such changes require a separately
reviewed migration, not reinterpretation of existing capital.

## Service and storage boundary

The 96-byte canonical request carries only the command, exact limit, expected
sequence and correlation. It carries no principal, permission, URL or credential.
The existing privileged pipe retains its administrator-only ACL and actual
elevated-token check. For limit requests, the service obtains the caller's user
and logon SIDs while impersonating the connected client, then reverts before any
filesystem or journal operation. The operator SID comes from protected setup.
Recovery and STOP-isolation drill modes reject limit commands. STOP handling
remains on its independent thread.

Changes append to `Vault/exec_ledger.db`, using the existing single-writer,
FULL-synchronous, hash-chained order journal. Each change retains the exact
limit, OS-derived administrator/logon identity, protected operator binding,
actual service clock, request identity and prior limit sequence. Duplicate
requests, stale versions, changed units/operator bindings and regressing clocks
are rejected before append. Replay validates the same contracts and retains
previous changes. An uncertain ledger commit is fatal to the service.

The existing `Vault/credentials.sqlite` and DPAPI generations are retained. The
execution ledger is opened on startup if present; invalid contents fail startup.
An absent ledger has no configured capital limit and grants no authority. The
first valid explicit change creates it under the existing protected vault ACL.
No authorized capital or credential was configured during implementation.

## Verification boundary

Eight new Rust tests cover exact amounts, malformed/correlated frames, CLI
arguments, restart/history, stale and duplicate updates, changed currency/unit
epoch/precision/operator, clock regression and the operator's zero/increase
boundary. They use temporary journals and synthetic identities; they do not
establish installed-host authentication or a real account balance.

The installer and installed-host file checks include the administrator-only
helper. These new binaries have not replaced the previously qualified protected
installation. A different administrator SID alone does not certify a strong
Windows security boundary when the daily operator also has administrator access.
No protection qualification is inferred from the metadata or local tests.
