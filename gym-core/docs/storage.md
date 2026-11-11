# Storage ownership

Operational records already use SQLite. Retain this layout: SQL for queries and
transactions, compressed raw segments for original exchange messages, and
individual immutable JSON files for portable research reports.

The repository-level `data/` directory is the single canonical root for
source checkouts, including Windows collector and research tasks. Commands
launched from the repository root or `gym-core/` use it by default; an
explicit `--data ../data` from `gym-core/` still works. Standalone installed
wheels must be given an explicit `--data` path.

### Legacy receipt migration (operator machine only)

Older commands launched from `gym-core/` without `--data` may have written
`gym-core/data/live/backup_status.sqlite3`. This is a **separate** SQLite
receipt journal, not the canonical `data/live/backup_status.sqlite3`.
Stop the collector, research workers, backup commands, and other writers before
migration. Inspect both files and make a recoverable copy of the legacy store.
If the canonical file does not exist, use SQLite's **backup API** to copy the
legacy database to a new canonical file, verify the receipts and immutable
triggers, and only then archive the legacy file. Do not simply copy an open
SQLite database: WAL sidecars can contain committed data. If both journals
exist, **do not overwrite either file or concatenate SQLite files**; reconcile
the immutable receipts with an operator-reviewed migration. Preserve all
other files under the old data root until their owners are identified.
This repository change does not move databases on a running machine.

Tool-cache cleanup must preserve live and DEMO stores, protected Executor
ledgers, credentials, backups, immutable run artifacts and signed recovery
evidence. Tracked design references remain project sources.

Backup/restore receipts are append-only, bounded and sanitized. Current status
selects the latest recorded time, independent of append order. A receipt does not
prove current archive availability, independent origin or runtime recovery.

| Owner | Format | Contents |
| --- | --- | --- |
| Market collector | `market.db`, SQLite WAL | Instruments, specifications, quotes, trades, candle vintages, quality, rule history and raw-segment manifests |
| Research services | `research.sqlite3`, `research_protocol.sqlite3`, `experiments.sqlite3` | Hypotheses, jobs, alerts, evaluations, outcomes, observations and experiment events |
| Operator journals | `external_journal.db`, `offline_reviews.db`, `venue_facts.db`, `backup_status.sqlite3` | Account/order observations, ticket reviews, venue facts and backup receipts |
| Protected Executor | SQLite through `exec-store` | Native execution ledger; owned by the protected service |
| Model gateway | `state.sqlite`, SQLite | Credential state and key-pool rotation; credential values use current-user DPAPI on Windows |
| Raw collector archive | `raw/YYYYMMDD/*.jsonl.zst` | Original public WebSocket/REST messages with sequence, receipt time and message hash |
| Research artifacts and configuration | Individual JSON files | Immutable run receipts and portable declarative settings; not appendable JSONL journals |

Market schema 4 adds a singleton committed collector-publication watermark.
Each complete multi-market tick, its quality/unit-rule effects and the watermark
commit in one SQLite transaction. A failed tick rolls back its normalized writes
and restores its cached tops/unit state. Prospective readers use one read snapshot
for the watermark, quotes, specifications and rules, and do not infer that a
wall-clock deadline proves the collector has published through that time.
Read-only opens require the current market schema (5). Upgrade older stores
through the normal writable open, after preserving a consistent backup; read-only
access never runs migrations. Future schema versions are refused in both modes.
DataPortal uses the current depth, publication and candle-vintage schema directly,
without runtime fallback to partially supported older layouts. An empty publication
table still means no committed watermark; quiet-period scans stay quote-driven.
Quote and candle observations are immutable.
Raw audit segments retain their existing ownership.

The remaining application JSONL is a compressed audit archive, not a query
database. Normalized SQL rows already hold the fields used by the application
and refer back to raw messages through segment/sequence references. Closed
segments have byte counts and SHA-256 hashes in SQL. Rewriting them into SQL
would duplicate that projection and its reference/backup contracts. Keep the
archive and its SQL index together when backing up or restoring.

Collecting every market writes roughly 200 MB of raw archive per hour. The collector
stops with a clear error when its volume has less than 5 GiB free, instead of filling
the disk. Move finished days elsewhere with
`gymctl raw-move --before YYYYMMDD --to <other-drive-folder>`; it never moves the
current UTC day and refuses if a destination day already exists. Segment files are
created exclusively, so two writers in the same hour can never share one file.

### Research backup

The executor-ledger backup does not cover research data. `gymctl backup-research <folder>`
takes one encrypted snapshot of every SQLite store in the data root (SQLite backup API, one
read transaction, safe while the collector writes), packs the other files (runs, studies,
journals; never `*.dpapi` key files or SQLite side files) into an encrypted archive, and
copies each closed raw segment once, after re-checking it against its manifest hash. A
corrupted segment is reported and not copied. Containers are scrypt + AES-256-GCM with the
name and plaintext hash in the authenticated header, so a swapped or edited file fails.

`gymctl research-restore-drill <folder>` decrypts and verifies the newest snapshot and the
newest segments in a temporary folder; `gymctl restore-research <folder> --to <empty>`
rebuilds a data root that `gymctl doctor` can check. The destination must be on another
drive unless `--allow-same-device` is given for a cloud-synced folder.
`scripts/windows/Install-ResearchBackupSchedule.ps1` schedules backup plus drill nightly
with the passphrase sealed by `gymctl key set-backup`. Keep a copy of that passphrase off
the machine: the sealed copy is lost with it.
