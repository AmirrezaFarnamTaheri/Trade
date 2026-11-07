# Changelog

## Unreleased

### Portfolio workflows and execution realism
- Portfolio revision 3 adds point-in-time USDT-equivalent curve marks and explicit
  LIVE/STALE/STALE_CLOSED/UNAVAILABLE FX states to the native records, CLI and browser.
  Future-only FX cannot value starting cash. Single-market boundary valuation shares
  the same owner. Pure drawdown arithmetic belongs to the domain layer.
- Shared-cash portfolio replay now reaches the private research API and EN/FA browser
  workbench through the existing bounded worker. Saved portfolios are listed and verified;
  derived performance is recomputed from verified records.
- Resting limit orders fill only observed capacity after queue depletion, retain exact
  working remainders and charge maker fees per fill. Invalid queue sizes cannot invent
  capacity. New limit records carry the queue-capacity/2 cost fingerprint.
- RSI, MACD, TRIX and Keltner rules accept bounded periods and thresholds, reset custom
  history across gaps and publish their actual readiness. Default configurations keep
  their existing identities; changed configurations use strategy version 2.

### Correctness and operations
- The single CLI entry point now delegates to established research, account,
  maintenance and daemon command groups. Parser/dispatch and command semantics remain.
- Portfolio controls verify running-backend support before enabling a calculation;
  an older process reports that activation requires an observatory restart.
- Backup receipt consolidation validates and preserves original history, deduplicates
  imports and selects current status by recorded time rather than import order.
  Both local source journals were snapshotted before the two missing receipts merged.
- Maintained EMA examples use registry parameters; legacy flags retain identical native
  saved-record behavior and remain available for existing callers and frozen engines.
- Portfolio revision 2 closes all market clocks before revealing later quotes; shared-cash
  marks and allocation no longer consume future prices. Its IDs bind resolved assets,
  decision/reference snapshots, depth, consumed limit prints, rules and specification history.
- Alias markets resolving to one base asset are rejected instead of double-counting holdings.
- Compound strategies reject unsupported limit orders and carried working remainders explicitly.
- Portable JSON/HTML summaries retain allowlisted execution and sizing assumptions.
- Concurrent native test directories use atomic suffixes rather than relying on clock resolution.
- Windows startup uses one explicit data root and all-market defaults, waits for collector startup,
  and supervises collection and paper scheduling as separate limited-user tasks.
- The implementation plan unifies the 31 cleanup/finance proposals with audit findings and
  outstanding execution/acceptance contracts. Existing study evidence stays in place.

### Security
- The session key is no longer embedded in the served page; open the private link printed by `gymctl run`.
  The Safety page can rotate the key. API responses carry a Content-Security-Policy and `nosniff`.
- CI scans for committed secrets and audits Python, Rust and Node dependencies.

### Research and finance
- First-in-first-out trade ledger; per-trade returns now count every buy, not only the last one.
- Risk and return per run: Sharpe, probabilistic Sharpe, Sortino, Calmar, drawdown, win rate, profit factor,
  expectancy, exposure, turnover, Kelly fraction (20+ trades), annualized figures for 30+ day windows.
- Comparisons report a deflated-Sharpe selection check.
- `--participation` caps each fill at a share of the displayed best-level size.
- Portable summaries are `paper-summary/2` (adds performance, drops constant authority flags).

### Data and storage
- Collection stops below 5 GiB free; `gymctl raw-move` moves finished day folders to another drive.
- Segment files are opened exclusively and hashed as a stream.
- The collector pauses publication when the clock goes backward instead of crashing.

### UI
- Paper research tabs, rebuilt charts, rounded display values, risk/return panel, closed-trade table,
  run filter and paging, comparison metrics and the server's error text on the compare form.

### Removed
- `exit_guard`, `reopening`, `shadow_autopilot`, `signed_release`: test-only modules with no caller.

### Tooling
- Ruff 0.16.9 with a project config; real-browser smoke tests on Linux (Chrome) and Windows (Edge);
  `uv run python scripts/check.py` runs lint, tests and the smoke test.
