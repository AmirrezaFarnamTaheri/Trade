# Baseline Integrity, Live Runtime Audit & Sprint-1 Execution Receipt

**Date:** 2026-11-21 (UTC) · **Host OS:** Windows (operator workstation)  
**Pinned repository base:** `master` at `2eedb5e7590b42c8df0244e15d582a2281dcfb6e` (merge commit with zero tree diff vs `8fba0b15115b617067fc93b9c9769c9351472900`, PRs #102–#107 integrated)  
**Toolchain:** `uv 0.11.23`, `Python 3.11.9`, `cargo 1.96.0`, `node v26.1.0`, `gh 2.92.0`  
**Tasks covered:** `G001`, `G002`, `G003`, `G004`, `G005`, `G006`, `G007`, `G008`, `G009`, `G010`, `G011`, `G012`, `E001–E004`, `E006–E007`, `E011–E016`, `M001`, `F001–F006`, `F008–F009`, `F012`, `S001–S002`, `X001`, `O001–O008`, `O010`

---

## 1. Pinned Baseline & Local Integration Run (`G001`, `G002`, `G009`)

- **Hosted CI (`G001`):** GitHub Actions Validate run `44834196697` on `8fba0b1` completed successfully (extended weekly mutation skipped; hosted CI does not qualify the installed Windows executor or independent research custody).
- **Local baseline run (`G002`) on unmodified `2eedb5e` / `8fba0b1`:**
  - Command: `.\tasks.ps1 rust python browser`
  - `cargo fmt --all --check`: **PASS**
  - `cargo clippy --locked --workspace --all-targets -- -D warnings`: **PASS** (16.59s)
  - `cargo test --locked --workspace --all-targets`: **PASS** (all workspace crates, fake-venue chaos, active holds, arming, admission, restricted service identity, stalled venue, Windows stop security, token probe)
  - `uv run --locked --group research ruff check src tests`: **PASS**
  - `python scripts/complexity_ratchet.py`: **PASS** (`16 functions above 20; 0 problems`)
  - `uv run --no-sync pytest -q`: **PASS** — `1977 passed, 23 skipped, 1 warning, 35 subtests passed in 198.74s`
  - `node tests/browser_smoke.cjs`: **PASS** — real Windows `msedge.exe` UI smoke

---

## 2. Installed-vs-Source Executor Capabilities (`G004`, `G005`)

- **Windows Service:** `TradingGYMExecutor` is **`Stopped`** (**`DISARMED` / `NOT CERTIFIED`**).
- **Installed bundle path:** `C:\Program Files\TradingGYM\Executor\` — binaries timestamped **2026-11-06 15:09** (predating the Nov 16–20 in-source LIMIT order path).
- **Installed qualification metadata:** `C:\Program Files\TradingGYM\Executor\operator-qualification.json` (`2026-11-06T11:39:33Z`) explicitly records:
  - `custody_requalified: false`
  - `funded_authority: false`
  - `capital_quanta: "0"`
- **Installed binary inventory & ACL observation (2026-11-21):**

| Binary | Size (bytes) | Timestamp | Unprivileged read / SHA-256 | Qualification status |
| --- | --- | --- | --- | --- |
| `gym-executor.exe` | 2,786,816 | 2026-11-06 15:09 | Access denied (service/admin ACL enforced) | **NOT QUALIFIED / PREDATES LIMIT SOURCE** |
| `gym-account-read.exe` | 1,928,192 | 2026-11-06 15:09 | Access denied (service/admin ACL enforced) | **NOT QUALIFIED / PREDATES LIMIT SOURCE** |
| `gym-ceiling.exe` | 1,837,056 | 2026-11-06 15:09 | Access denied (service/admin ACL enforced) | **NOT QUALIFIED / PREDATES LIMIT SOURCE** |
| `gym-provision.exe` | 1,844,224 | 2026-11-06 15:09 | Access denied (service/admin ACL enforced) | **NOT QUALIFIED / PREDATES LIMIT SOURCE** |
| `gym-hardstop.exe` | 1,840,128 | 2026-11-06 15:09 | `F334114A2D96764838312B8B8BD37A38BB6E2B133B187DFE16E3AFE4A8AD67FD` | Installed Nov 6; differs from Nov 4 drill manifest |
| `gym-research-worker.exe` | 286,208 | 2026-11-06 15:09 | `37590FBA07668DE44DF1481427DBEFAC765E4911709DB2C3AD00FFDE2034C881` | Installed Nov 6; differs from Nov 4 drill manifest |
| `gym-review.exe` | 1,840,128 | 2026-11-06 15:09 | `D93324D40519267B69E39EDD81BED2C72F4B6665CB1F7CA2AF114FE2899EAF12` | Installed Nov 6 |
| `gym-stopctl.exe` | 1,833,984 | 2026-11-06 15:09 | `3349ED4B9FF67E0D9E8A1DB3CD1CFCC29D15165F98DD5F5075C722DB4DB7B138` | Installed Nov 6; differs from Nov 4 drill manifest |

- **Source-only funded features (`NOT INSTALLED / NOT QUALIFIED / DISARMED`):** elevated one-shot LIMIT transport, review v2 approval/settlement, active holds, service receipt ordering (ADR 0008). Zero funded-loss budget preserved.

---

## 3. Live 30-Day Feed Continuity Audit (`M001`)

Measured read-only from `data/live/market.db` (10.85 GB, schema v6, 469 instruments) and `uv run --no-sync gymctl --data ..\data doctor` on **2026-11-20T23:45Z**:

- **`gymctl doctor` highlights:**
  - `market_db`: `PASS` (`SQLite quick_check: ok`)
  - `collector_feed`: **`WARN`** — `newest quote 1034 min old; collector stopped or venue unreachable` (`collector_publication.through = 2026-11-20T06:27:44.588210Z`)
  - `collection_gaps`: `SKIP` (`fewer than two heartbeat quotes in the last 24 hours`)
  - `raw_segments`: `PASS` (`21 re-hashed (days from 20261119); mismatched none; missing none`)
  - `segment_manifest`: **`WARN`** — unclosed `['20261119/11-0.jsonl.zst', '20261119/14-0.jsonl.zst', '20261120/06-0.jsonl.zst']` (15 total unclosed segments across Nov 10–Nov 20 out of 1,736 total segments)
  - `free_space`: **`WARN`** — `18.0 GiB free; collection stops below 5 GiB` (13.0 GiB runway remaining)
  - `collector_crash`: **`WARN`** — `2026-11-20T06:29:26Z: sqlite3.OperationalError: database is locked` in `_housekeeping` -> `tick` and again during shutdown `seg.close()` -> `add_segment`
- **Observed archive span (`2026-10-30T21:00Z` to `2026-11-20T06:00Z`, 22 calendar days elapsed):**
  - Days with >= 1 segment hour: **20 / 22** (0 hours on `2026-11-02` and `2026-11-09`)
  - Days with 24/24 segment hours: **1 / 22** (`2026-11-11`)
  - **Raw segment gaps > 24 hours (3 occurrences):**
    - `35.0h`: `2026-10-31T10:00Z` -> `2026-11-01T21:00Z`
    - `41.0h`: `2026-11-01T23:00Z` -> `2026-11-03T16:00Z`
    - `49.0h`: `2026-11-08T09:00Z` -> `2026-11-10T10:00Z`
  - **Current active outage:** ~17.2 hours since `2026-11-20T06:29Z` crash (will cross 24h if collector is not restarted).
- **Quality event totals (`1,187,914` rows):** `WIDE_SPREAD` (855,291), `STALE` (217,840), `SOURCE_ERROR` (70,182 — latest on `2026-11-20T06:31Z` and `2026-11-20T11:30Z` with `ClientConnectorError: api.wallex.ir:443`), `THIN_BOOK` (42,652), `GAP` (1,289), `CROSSED` (322), `ZERO_SPREAD` (233), `SEGMENT_UNCLOSED` (59), `SEGMENT_RECOVERED` (33), `CATALOG_RETAINED` (12), `CLOCK_REGRESSION` (1).
- **Remediation landed in source:** `MarketDB.__init__` now sets `timeout=30.0` and `PRAGMA busy_timeout=30000` to prevent transient multi-process WAL writer contention from crashing the collector.

---

## 4. Prospective Journal & Archive Continuity Audit (`E011`, `E012`, `E013`, `E014`)

| Study / archive | Path / source | Observed state (2026-11-21) | Gaps / operational findings |
| --- | --- | --- | --- |
| **`btc-daily-trend` (`E011`)** | `data/live/allocation/journal.jsonl` | 6 entries (`2026-11-13`..`2026-11-18`), all `CASH` (`1000 USDT`, `0 BTC`); last appended `2026-11-19T00:16Z` | **Missing `2026-11-19` & `2026-11-20`**. Task `TradingGYM Allocation Journal` ran `2026-11-20 09:25` local and exited `0x0` while `api.wallex.ir` failed with `ClientConnectorError` because `\| Out-Null` masked `$LASTEXITCODE`. |
| **`passive-multi-asset-mix` (`E012`)** | `data/live/allocation/mix-journal.jsonl` | 2 entries (`2026-11-17`, `2026-11-18`); last appended `2026-11-19T00:16Z` | **Missing `2026-11-19` & `2026-11-20`**. `AAPLXUSDT` daily candles stopped after `2026-09-25` (weight forced to `0.0`). On `2026-11-18`, all 6 tokens had `stale_quotes`. |
| **`breadth-trend-forward` (`E013`)** | `data/live/allocation/breadth-journal.jsonl` | 1 entry (`2026-11-17`, appended `2026-11-19T11:30Z` = 15:00 Tehran, `breadth=0.0`, `gate_open=false`, 32 symbols) | **Missing `2026-11-18`, `2026-11-19`, and `2026-11-20` (Day 1 of official `2026-11-20..2027-05-19` scored window)**. Task `TradingGYM Breadth Journal` ran `2026-11-20 15:00` local and exited `0x0` while `api.wallex.ir` failed (`SOURCE_ERROR`). Only 10 symbols had 1d candles for Nov 18/19 (vs 304 on Nov 17) and 0 on Nov 20. |
| **`funding-confirmed-trend-forward` (`E014`)** | `data/binance-public/` | `1d`: 474 symbols, 21,857 zips (`2017-08`..`2026-10`, 371 in `2026-10`); `funding`: 474 symbols, 17,366 zips (`2020-01`..`2026-10`, 363 in `2026-10`) | On schedule; `2026-11`..`2027-02` monthly zips are future data. Scoring remains blocked until after `2027-02-08`. |

- **Code fixes landed (`E015`, `E016`):**
  1. Added cross-process OS file locking + durable `fsync` append (`gym-core/src/gym/services/_journal_lock.py`) to `allocation.py`, `mix_journal.py`, and `breadth_journal.py` — concurrent runs can never duplicate a day entry.
  2. Updated `scripts/windows/Install-AllocationJournal.ps1` and `scripts/windows/Install-BreadthJournal.ps1` to propagate nonzero `$LASTEXITCODE` instead of masking errors behind `| Out-Null`. (Operator must re-run the installers to update existing Task Scheduler actions.)

---

## 5. Backup State & Isolated Full Local Restore Rehearsal (`G007`, `O001`, `O002`, `O003`)

- **Live operator state (`O001`, `O002`):**
  - `data/live/backup_status.sqlite3`: 195 `RESTORE` receipts (executor ledger sequence 2, `mode_after: DISARMED`, latest `2026-11-20T10:41:14Z`); **0 `BACKUP` receipts**.
  - `data/live/research_backup_status.json`: **absent** (`gymctl doctor` reports `SKIP: optional research backups are not configured`).
  - Windows Task Scheduler: **no automated backup task installed**, matching the owner's explicit **2026-11-16 cancellation** of automated off-machine backups and second-machine restoration. Exposure is now documented prominently in `gym-core/docs/disaster-recovery.md` without auto-enabling any remote service.
- **Isolated full local restore rehearsal (`O003`, executed 2026-11-21):**
  - Source: isolated scratch copy of `data/demo` (5 SQLite DBs + 74 closed raw segments + 1 open segment `20261110/17-0.jsonl.zst` excluded).
  - Snapshot ID: `20261121T000947Z-z762133-844978` · Manifest SHA-256: `35f40279ed0d6df060410d9bbf5e5e2cad77e3627f1f25c26745633aa9ea3797`
  - Elapsed times: backup **10.329s**, pinned full restore **10.849s**, schema 5 -> 6 migration on restored copy **0.159s** (`data/demo/market.db` itself remains untouched at schema v5).
  - Verified labels: `manifest_status: PINNED`, `segment_coverage: COMPLETE (missing: [])`, `segment_integrity: FULL_RESTORE (74/74)`, `sampled_drill_integrity: SAMPLED_DRILL (2/74)`, `cross_host_verified: false`.
  - Restored root `doctor`: `market_db: PASS`, `raw_segments: PASS`, `segment_manifest: PASS`, `venue_facts: PASS`, `offline_reviews: PASS`, `external_journal: PASS`, `executor_ledger: SKIP` (isolated/DISARMED).

---

## 6. GitHub Issue #13 Triage Reconciliation (`G008`)

Issue #13 (`B1 release acceptance`, opened/updated 2026-10-31) predates ADR 0007, ADR 0008, and the in-source LIMIT path. **Do not close Issue #13** based on source commits or CI; reconcile sub-items as follows:

| Issue #13 sub-item | Status on master `8fba0b1` | Remaining host/venue requirement |
| --- | --- | --- |
| T2 credential isolation & service DPAPI ACL | Implemented in source + CI Windows SCM/ACL + Nov 6 binary ACLs on disk | Re-qualify against signed current-source bundle (`H002–H006`); Nov 6 bundle has `custody_requalified: false` |
| Dedicated T0 STOP-only pipe (<1s under hung main loop) | Implemented in source + synthetic stalled-venue/security tests | Benchmark & verify on installed current-source Windows service (`H007–H009`) |
| Scoped read-only Wallex key live balance/fee/order read | Implemented in source + ADR 0008 receipt ordering | Authenticated live Wallex account read qualification (`H016`) |
| Manual external order lifecycle observed via GET | Offline/synthetic tests only | Permitted real non-withdrawal read-only observation of manual external order (`H028`) |
| Installed-host negative checks with real deployment principal | Older Nov 4 drill manifest does not match Nov 6 binaries or current source | Complete installed-host qualification bundle after 2027-02-08 gate & owner sign-off (`H001`, `H029`) |

---

## 7. Open Owner Decisions (Preserved — Not Auto-Decided)

1. **Restart collector & check Wallex connectivity:** Collector has been stopped since `2026-11-20T06:29Z` (approaching 24h gap) and `D:` free space is `18.0 GiB` (13.0 GiB above the 5 GiB stop floor). Re-running `Install-AllocationJournal.ps1` and `Install-BreadthJournal.ps1` will apply the fixed exit-code propagation to Windows Task Scheduler.
2. **New-run inventory default (`F011`):** Keep `legacy` default vs switch new runs to `inventory/1` or `inventory/2` after golden comparison.
3. **Independent final custodian (`E001`):** Approve the concrete separated evaluator/CI-release workflow before scoring future trials.
4. **Off-machine backup policy (`O014`):** Remains canceled per 2026-11-16 owner decision; requires explicit opt-in if policy changes before 2027-02-08.
5. **Issue #13 comment (`G008`):** Ready to post the Section 6 triage summary to GitHub Issue #13 upon owner approval.
