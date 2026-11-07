# Decision records

Short records of choices that are easy to undo by accident. Newest first.

## D5 — Causal FX curves have explicit identity (7 November 2026)

New historical TMN runs bind each recorded equity mark's point-in-time FX factor
and status through the causal-fx-curve/1 input fingerprint. These new outputs need
new run IDs; old artifacts are retained. USDT is already native and keeps the
existing default identity without storing a redundant conversion for every mark.
Shared-cash portfolios reuse the same curve owner and retain their conversion
contract. The golden USDT identity guard remains unchanged.

## D4 — Fill-size cap keeps old run identities (2026-11)

**Decision.** `CostModel.max_participation` is optional. `describe()` emits it only when set.
**Why.** The run ID is the digest of the inputs, and the cost description is an input. Emitting `null`
by default would change every existing run ID and orphan saved comparisons and hypotheses.
**Guard.** `tests/test_run_identity_golden.py` pins one default and one capped run ID.

## D3 — Display rounding, exact values on hover (2026-11)

**Decision.** Tables and stat tiles round money to two decimals. The exact source decimal stays in the
`title` tooltip, in the "Exact values" list, and in every export.
**Why.** 28-digit results made tables unreadable on desktop and mobile. Precision is a storage and audit
property; the screen is for comparison.

## D2 — Session key in the URL fragment, not in the page (2026-11)

**Decision.** `gymctl run`/`serve` print `http://127.0.0.1:<port>/#t=<key>`. The page reads the key from
the fragment once, keeps it in the tab's `sessionStorage`, and removes it from the address bar.
`POST /api/session/rotate` replaces it.
**Why.** Any local process could read the key when it was embedded in `GET /`. Browsers never send the
fragment to a server, so the key only reaches tabs the operator opened from the printed link.

## D1 — Constant authority flags removed from transient responses (2026-11)

**Decision.** Responses no longer carry `funded_authority: false` / `order_submitted: false`.
**Why.** The values could never be anything else, the UI re-checked them, and tests asserted them,
which made every new endpoint carry boilerplate without protecting anything. Authority is enforced by
the executor boundary, not by response fields. Durable records that already contain them are unchanged.
