# Measured Performance Baselines, Rust Kernel Parity, SBOM & Script Hygiene Audit

**Date:** 2026-11-21 (UTC) · **Host:** Windows 10/11 (`10.0.26200`, 16 CPUs, Python `3.11.9`, Cargo `1.96.0`, Node `v26.1.0`)  
**Tasks covered:** `F007`, `O012`, `I001–I021`

---

## 1. Live `market.db` Query Baselines & Index Plans (`I001`, `I013`)

Measured read-only on `data/live/market.db` (**10,344.48 MiB**, schema v6, 469 instruments):

| Operation | Rows | Elapsed (ms) | SQLite Query Plan |
| --- | ---: | ---: | --- |
| Latest quote (`ORDER BY rowid DESC LIMIT 1`) | 1 | **0.67 ms** | O(1) rowid reverse seek (`2026-11-20T06:27:44.588210Z`) |
| 1-day `BTCUSDT` `book_top` range (`2026-11-19..20`) | 10,597 | **42.24 ms** | `SEARCH book_top USING INDEX book_top_time (ts_avail>? AND ts_avail<?)` |
| 1-day `BTCUSDT` `trades` range (`2026-11-19..20`) | 1,736 | **0.64 ms** | `SEARCH trades USING INDEX trades_event (instrument_id=? AND ts_event>? AND ts_event<?)` |

## 2. Storage Runway & Disk Footprint (`O012`)

| Store / Volume | Size | Operational note |
| --- | ---: | --- |
| `D:` volume free / total | **16.15 GiB / 170.0 GiB** | **WARN:** only **11.15 GiB** above the `5 GiB` hard collection stop floor |
| `data/live/raw/` (1,736 zstd segments) | **33.20 GiB** | Primary growth driver (~200 MB/hour when all markets run) |
| `data/live/market.db` | **10,344.48 MiB** | Schema v6, `quick_check: ok` |
| `data/live/experiments.sqlite3` | **179.44 MiB** | Research experiments store |
| `data/live/research.sqlite3` | **64.61 MiB** | Research jobs/runs store |
| `data/live/trial_ledger.sqlite3` | **32.07 MiB** | 97,476 append-only trial attempts |
| `data/live/recorder.sqlite3` | **2.58 MiB** | Venue recorder import store |
| `data/live/backup_status.sqlite3` | **0.07 MiB** | 195 executor restore receipts (`mode_after: DISARMED`) |

## 3. Compute, UI Payload & Rust Financial Kernel Parity (`I003`, `I005`, `I014`, `F007`)

- **Limit-order 30m paper replay (`I003`):** **62.62 ms**
- **10-market shared-cash portfolio 30m replay (`I005`):** **391.31 ms**, 10 fills, peak Python traced allocation **3.05 MiB**
- **UI static payload (`I014`):** **21 files, 414,752 bytes total** (largest: `workspace-config.js` 125.8 KB, `research.js` 59.1 KB, `styles.css` 34.6 KB, `index.html` 34.0 KB, `runs.js` 23.2 KB).
- **Schema upgrade rehearsal (`I012`):** Restored scratch copy of schema-v5 `data/demo/market.db` migrated cleanly to schema v6 in **0.159s** and passed `gymctl doctor`.
- **Python vs Rust financial kernel parity (`F007`):** Built `exec-kernel 0.2.0` (`maturin build --release -m executor/exec-kernel-py/Cargo.toml`) in **13.84s**; `GYM_RUST_KERNEL=1 uv run --no-sync pytest -q tests/test_kernel_sizing.py` passed **19/19 tests in 0.23s** (including 2,000 randomized rational budget-walk vectors, precision/rounding traps, overflow rejection, and dated fill/fee/posting parity).
- **CycloneDX SBOM generation (`I020`):** `.\tasks.ps1 sbom` succeeded cleanly for both Python (CycloneDX 1.5, 16 runtime components) and Rust lockfiles.

### Evidence-Based Disposition of Conditional Architecture Tasks (`I004`, `I006–I011`, `I015`)

- **`I004` (incremental limit scan), `I006–I007` (single-writer actor), `I008–I010` (Parquet/Arrow/DuckDB cold catalog), `I011` (multi-DB consolidation), `I015` (ES module rewrite):** **DEFERRED WITH MEASURED EVIDENCE.** Schema-6 SQLite queries return in `0.64–42.24 ms` on a 10.3 GB database, 10-market portfolio replay uses `3.05 MiB` peak memory, and the native dependency-free UI bundle is `414.8 KB`. The actual observed runtime failure was SQLite WAL multi-process writer lock contention (`sqlite3.OperationalError: database is locked`), which is directly fixed via `timeout=30.0` + `PRAGMA busy_timeout=30000` in `MarketDB.__init__`.

---

## 4. Complete Script Classification Inventory (`I018` — 38 Scripts, Zero Blind Deletions)

| Script (`gym-core/scripts/`) | Size (B) | Refs | Classification | Disposition |
| --- | ---: | ---: | --- | --- |
| `complexity_ratchet.py` | 2,612 | 4 | Operational CI gate | Keep (active CI & `tasks.ps1`) |
| `detectable_edge.py` | 9,242 | 4 | Active research power gate | Keep (required for new registrations) |
| `binance_archive.py` | 5,176 | 2 | Active forward data fetcher | Keep (`funding-confirmed-trend-forward`) |
| `held_out_followups.py` | 5,652 | 3 | Active forward scorer | Keep (scores after `2027-02-08`) |
| `venue_recorder.py` | 12,167 | 3 | Operational scheduled sync | Keep (`TradingGYM Recorder Import` & CI) |
| `venue_probe.py` | 1,761 | 1 | Operational CI probe | Keep (`venue-probe.yml`) |
| `venue_public_shape.py` | 1,655 | 2 | Operational CI probe | Keep (`venue-probe.yml` & test) |
| `mutation_gate.py` | 11,450 | 2 | Operational CI security gate | Keep (`validate.yml` & test) |
| `restore_portability_probe.py` | 2,815 | 2 | Operational CI recovery probe | Keep (`validate.yml` & test) |
| `evidence_index.py` | 2,977 | 1 | Operational integrity checker | Keep (safety boundary test) |
| `ui_copy_extract.py` | 3,792 | 1 | Operational UI test utility | Keep (`test_ui.py`) |
| `check.py` | 991 | 1 | Operational dev helper | Keep (`tests/README.md`) |
| `long_history_study.py` | 34,631 | 3 | Historical reproducer (tested) | Keep (holdout no-peek regression target) |
| `usdttmn_v1.py` | 12,226 | 3 | Immutable trial reproducer | Keep (`usdttmn-intraday-reversion`) |
| `edge_screen.py` | 16,573 | 2 | Immutable trial reproducer | Keep (trials T2–T6) |
| `feature_table.py` | 4,381 | 2 | Immutable trial reproducer | Keep (`logistic-entry-gate`) |
| `meta_label_fit.py` | 8,717 | 2 | Immutable trial reproducer | Keep (`logistic-entry-gate`) |
| `trend_portfolio.py` | 7,920 | 2 | Immutable trial reproducer | Keep (`ten-coin-trend`) |
| `margin_breakout.py` | 6,352 | 2 | Immutable trial reproducer | Keep (`margin-breakout-long-short`) |
| `margin_hold.py` | 6,880 | 2 | Immutable trial reproducer | Keep (margin research) |
| `market_campaign.py` | 31,473 | 2 | Historical campaign reproducer | Keep (`paper-qualification.md`) |
| `book_imbalance.py` | 6,335 | 1 | Immutable trial reproducer | Keep (`book-imbalance`) |
| `daily_trend_replay.py` | 5,251 | 1 | Immutable trial reproducer | Keep (`btc-daily-trend`) |
| `funding_filter.py` | 6,999 | 1 | Immutable trial reproducer | Keep (`funding-crowding-filter`) |
| `horizon_study.py` | 20,854 | 1 | Historical research reproducer | Keep (tested) |
| `implied_rate.py` | 6,195 | 1 | Immutable trial reproducer | Keep (`implied-toman-rate`) |
| `passive_mix.py` | 4,909 | 1 | Immutable trial reproducer | Keep (`passive-multi-asset-mix`) |
| `rule_selector.py` | 7,378 | 1 | Immutable trial reproducer | Keep (`rule-selector-with-cash`) |
| `signal_decay.py` | 3,296 | 1 | Historical diagnostic reproducer | Keep (tested) |
| `strongest_coin.py` | 5,731 | 1 | Immutable trial reproducer | Keep (`strongest-coin-or-cash`) |
| `token_premium.py` | 2,399 | 1 | Historical diagnostic reproducer | Keep (`2026-11-18-tokenised-premiums.md`) |
| `trend_short.py` | 5,299 | 1 | Immutable trial reproducer | Keep (`trend-with-short-side`) |
| `usdttmn_range.py` | 5,010 | 1 | Historical diagnostic reproducer | Keep (tested) |
| `conversion_route_study.py` | 4,939 | 0* | Evidence reproducer (`evidence/2026-11-18-conversion-routes.md`) | Keep (do not delete) |
| `portfolio_lab.py` | 13,295 | 0* | Evidence reproducer (`evidence/2026-11-19-portfolio-lab-exploration.md`) | Keep (do not delete) |
| `signal_lab.py` | 10,403 | 0* | Evidence reproducer (`evidence/2026-11-19-signal-blend-exploration.md`) | Keep (do not delete) |
| `benchmark_reports.py` | 1,542 | 0 | Standalone benchmark utility | Retain unless owner approves archive |
| `paper_report.py` | 19,124 | 0 | Standalone paper reporting CLI | Retain unless owner approves archive |
