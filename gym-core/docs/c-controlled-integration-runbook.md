# Workstream C: controlled-integration engineering runbook

**Status: implementation and synthetic acceptance only — NOT funded release.**
This runbook covers the current stacked draft branches for C1, C2, and C3.
All development in this slice is safe to run without a Wallex API key, but
**none of it submits, cancels, protects or certifies a real order**.

## Verify the code

From repository root:

```sh
cd gym-core
uv sync --locked --group dev
uv run pytest -q
cd ..
cargo test --locked --workspace --all-targets
```

Windows SCM/ACL, remote backup recovery, T2 principal and service-owned
credential isolation require a **clean controlled Windows host**.
CI success and synthetically restored ledgers are not a substitute for
operator-controlled deployment evidence.

## C1 — evidence, private-read uncertainty and budgeted manual probes

1. Public observatory works without credentials. The existing read-only
   account adapter can receive a deliberately injected **read-scoped**
   authenticated session on a properly controlled host. Do not run private
   account GETs under the browser or research worker identity.
2. Save **sanitized metadata only**, in the exact format described in
   `gym-core/docs/c1-readonly-venue-validation.md`, then run:

   ```sh
   gymctl --data data venue-fact-import safe-venue-metadata.json
   ```

   Facts are append-only, hash-chained and source labels remain untrusted.
   Inspect Health → venue capability evidence (English and Persian).
   Records with `OBSERVED` do NOT self-certify a venue order method.
3. To plan a strictly offline, maximum-total-loss manual probe, create a
   sanitized `probe.json`:

   ```json
   {
     "probe_id":"mechanics-001",
     "kind":"CLIENT_ID_ECHO",
     "symbol":"BTCUSDT",
     "worst_case_total_loss":"1.00",
     "venue_minimum_quote":"0.50"
   }
   ```

   Then stage an estimate:

   ```sh
   gymctl --data data probe-budget-stage --total-loss-limit 2.00 --quote-asset USDT probe.json
   ```

   This reserves full potential loss in a durable **offline-only** journal.
   Staged risk is never silently released, and a venue minimum never increases
   the operator ceiling. **It is not permission to place an order.** Do not
   use a sample total-loss budget as a live authorization.
4. For a captured private read, the pure `assess_probe_read` classifier
   treats non-200, malformed, too-large, undocumented and 404 responses as
   `UNKNOWN`, **not** proof of an absent order. A 200 balance observation
   is still not executable or certified. There is no private key in this path.

## C2 — order preview, review queue and shortfall

- In Operate (offline), paste a safe request JSON envelope. The only request
  the UI sends is to the **local** `/api/dry-run/ticket`. It returns an exact
  decimal price/fee/budget estimate with `mode=DRY_RUN`,
  `client_id=null`, and `order_submitted=false`.
- Equivalent CLI calculation: `gymctl ticket-preview safe-ticket.json`.
  The request schema is `PREVIEW_FIELDS` in `assisted_ticket.py`.
  Include exact observed bid/ask, quote freshness, bounded validity, both
  available balances, worst price, fee rate, order cap and venue minimum.
  Inputs are **hypothetical** until independently verified by a money service.
- `OfflineReviewJournal` persistently records canonical previews and
  append-only `ACKNOWLEDGE`/`REJECT` events. ACKNOWLEDGE is never T1
  authorization. The review journal cannot submit or create an order ID.
  Use `gymctl --data data ticket-queue-add saved-preview.json` to register a
  completed `ticket-preview` output, and `gymctl --data data
  ticket-queue-review PREVIEW_SHA256 ACKNOWLEDGE --at 2026-11-01T08:00:10Z`
  to record an in-window **offline-only** acknowledgment. The token-guarded
  `GET /api/offline-ticket-reviews` publishes this in Journal in both
  supported languages. There is no `APPROVE_LIVE` operation.
- `gymctl conversion-report fake-conversion.json` computes a synthetic
  implementation shortfall. Fields must be exactly `instruction` (typed
  spot conversion request), `fills` (Fake Venue fill IDs, quantities,
  prices, quote fees and times), `mark_price` and `observed_at`.
  The report decomposes quote shortfall into fill-price movement, quoted
  fees, and the value of unconverted quantity relative to arrival. A
  deadline remainder is explicitly marked unfilled; synthetic settlement
  never becomes verified live settlement. Quote fee is the supported fee
  assumption, **not** an assertion of the actual account fee asset.

## C3 — shadow Autopilot and exit/reopening safety

- `ShadowAutopilot` supports one simulated workload, one account, total and
  per-order caps, one unresolved entry, runtime epoch fencing and monotonic
  stop states. `restart()` is disarmed and retains unresolved reservations.
  All entries remain `SIMULATED_PENDING` with `client_id=null`.
- `propose_protective_exit` may recommend an independent reduction despite
  an entry-only cooldown or another instrument's pending entry, but it does
  not bypass verified base quantity, same-instrument uncertainty, venue
  closure or HALTED state. No real stop order is constructed.
- `ReopeningWindow` implements `SELL_AT_REOPEN` and
  `REEVALUATE_AFTER_N_QUOTES` as model-only advisory decisions. Only
  distinct increasing quote sequences with qualified freshness, verified
  units, no unknown orders and the active runtime epoch count. A closure
  shows protection **UNAVAILABLE**; a restart loses pre-crash quote credit.
- Rust `exec_core::c_admission` has independent entry/exit pure vetoes.
  Even when every caller-supplied fact is true, it refuses funded authority
  without the missing trusted service, T1/T2 principal and durable request.
- The browser's `/api/automation-safety` is intentionally conservative:
  **DISARMED, UNAVAILABLE, NOT_CERTIFIED, entries_enabled=false,
  autopilot_enabled=false**. It does not pretend to query a privileged
  Executor that has not been integrated.

## Acceptance still required for C1, C2 and C3 release

| Gate | Real proof required | Current status |
| --- | --- | --- |
| B1 / SEC-02 | Win32 separated principals, protected service keys, T2 consent and worker pipe/credential denial | **Not verified on operator host** |
| B2 / MONEY-01..11 | Durable money authority, account-scoped reservations, authenticated recovery, emergency stop and real settlement | **Only partial B models and synthetic tests** |
| C1 / VenueFacts | Real, dated private balance/fee/status reads and honest filter/pagination probes; no raw secrets | **Only offline/synthetic** |
| C1 / Probe | Operator-fixed affordable full-loss budget; explicit consent for **each** real order; observed client-ID, duplicate and stop semantics | **Not performed** |
| C2 / Assisted | T1 approval cryptographically/authenticated to exact durable order and price envelope; real conversion with settlement and measured shortfall | **Only offline models** |
| C3 / Exit Guard | Venue-side waiting/trigger/cancel/fee/quantity certification, host/network outage test and reopening policy exercised with real positions | **Only advisory models** |
| C3 / Autopilot | One signed/pinned executable workload, independently enforced service caps, real reconciled capped session and protected stops | **Not authorized or executed** |
| UI / OPS-03..05 | Live Operate/Journal state transitions, accessible bilingual controls, stop request acknowledgement and actual protection disclosure | **Offline bilingual UI, no live control acceptance** |

**Never classify C as production-complete on the strength of a green CI run,
a local hash chain, a paper preview, or a caller-supplied boolean.** The first
funded test is deliberately deferred until those independently verified
security and economic prerequisites and explicit operator authorization exist.
