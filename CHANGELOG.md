# Changelog

## Unreleased

Hardening from the 2026-11-09 technical due-diligence review (finding IDs in brackets).

- Seeded property tests for every exec-ipc frame codec: mutated frames never panic a decoder, and every
  accepted frame re-encodes byte-for-byte [E-9].
- Shared fill-timestamp profile (`contracts/v1/fixtures/fill-timestamps.json`) enforced identically by the
  executor and gym-core; v2 operator-review golden frames checked from Rust and Python [E-8, A-4].
- Executor account-observation freshness is checked per resource, so a fees read is no longer refused because
  a balances read was in flight; stale reads of the same resource are still refused [E-6, partial].
- Weekly mutation testing now also covers the cash book, portfolio policy and margin math [E-10].
- `gymctl backup-research`, `research-restore-drill`, `restore-research` and a nightly schedule script: encrypted
  snapshots of every research store and the raw archive, with an authenticated restore that never overwrites;
  `doctor` reports the age of the last snapshot [R-5, OD-4 groundwork].
- Holdout custody for the long-history study: every look at a test window is recorded in an append-only
  ledger; a second look is withheld unless `--rescore-holdout`, and then the deflated Sharpe counts the
  configurations tried across every look [R-1].
- Research workers log their deadline use (`research_worker` in events.jsonl) and warn above 75% of it [P-2].
- UI: the refresh banner names the failing sources and the last complete refresh, and polling backs off to
  30 s while the service keeps failing; covered by the real-browser smoke test [U-8, P-3].
- UI: a ratchet test stops inline Persian copy from growing outside the shared vocabulary [U-7, partial].
- Conformance vectors for the ticket quote envelope (`contracts/v1/fixtures/ticket-envelopes.json`): Rust and
  Python accept and refuse the same 16 tickets at the same rounding boundary [A-1 step 1, partial].
- Model gateway: optional `policy.allowedHosts` pins custom endpoints to approved hosts [S-7].
- Executor-ledger head anchors in the backup folder: each verified backup records (sequence, head hash); a
  truncated or rebuilt ledger is refused before older bundles are rotated, and the restore drill checks the same [R-3].
- Simulator: seeded property tests over 4,000 random market orders (cash conservation, no overspend, precision,
  never better than the touch, no fill before latency, non-fills move nothing); `market_order` split into sizing,
  modeled-cost, price-guard and settlement helpers, complexity 40 to under 20 and enforced in CI [E-1].
- Bias harness (`gym.services.bias_harness`, `tests/test_bias_harness.py`): every registered strategy is
  replayed with truncation at two cuts, with every observation after each cut repriced (decisions up to the cut
  must stay byte-identical), and with a longer prehistory (positions must agree once settled). Three seeded
  faults prove it bites: a strategy that precomputes from the whole stored history, a data layer that publishes
  quotes a minute early, and a signal that depends on the replay start [R-2, M-2 step 1].
- API: a non-ASCII `X-Gym-Token` is refused with 403 instead of a 500 [E-3].
- Wallex candles are parsed as `Decimal` straight from the JSON text; non-finite values are rejected [E-2].
- Instrument-spec close and successor insert run in one savepoint [E-5].
- Raw segments get a manifest row when they open; `verify-segments` and the daily sweep report unclosed and
  unregistered files [R-4].
- Model gateway is started with an allowlisted environment [S-10].
- DPAPI blobs carry purpose-bound entropy (legacy blobs migrate on first read); linked key paths are refused [S-1, S-12].
- Executor: `forbid(unsafe_code)` in exec-core, exec-store and exec-ipc; saturating `reserved()`; release builds
  keep overflow checks; SID files resolve through the Program Files known folder [S-3, E-7, S-9].
- `gymctl doctor`: one read-only check of market.db, raw segments, journals, free space, backup receipts and key
  expiry, with a JSON receipt (`--json`) and exit 1 on any failure [O-4].
- Model usage ledger enforces daily and monthly call caps (200 and 2,000 by default) and optional cost caps,
  checked before a request reaches the gateway; set them with the `usage_limits` control [L-4].
- Research assistant extracts the first complete JSON array, retries once with a repair prompt, and reports
  `INVALID_MODEL_REPLY` instead of silently testing nothing [L-2].
- UI: first visit follows the system colour scheme; Windows forced-colours mode keeps borders and focus visible [U-6].
- UI: rule disable and preset load use a labelled bilingual dialog (Cancel focused, focus returned); covered by
  the real-browser smoke test [U-9].
- Launcher requires a real TradingGYM `/api/ready` answer and warns when market data is blocked [O-3].
- CI actions pinned by commit SHA, Rust pinned to 1.96.0, Dependabot and CODEOWNERS added [S-4].
- Docs: root README with the current state, strategy count corrected to sixteen and guarded by a test, excluded
  strategy families recorded, OAuth marked opt-in, public reads documented [U-1, G-4, S-2, S-8].
