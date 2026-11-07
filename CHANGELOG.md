# Changelog

## Unreleased

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
