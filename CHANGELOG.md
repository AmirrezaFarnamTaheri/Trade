# Changelog

## Unreleased

Hardening from the 2026-11-09 technical due-diligence review (finding IDs in brackets).

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
- Launcher requires a real TradingGYM `/api/ready` answer and warns when market data is blocked [O-3].
- CI actions pinned by commit SHA, Rust pinned to 1.96.0, Dependabot and CODEOWNERS added [S-4].
- Docs: root README with the current state, strategy count corrected to sixteen and guarded by a test, excluded
  strategy families recorded, OAuth marked opt-in, public reads documented [U-1, G-4, S-2, S-8].
