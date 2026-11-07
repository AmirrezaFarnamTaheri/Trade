# Storage ownership

Operational records already use SQLite. Retain this layout: SQL for queries and
transactions, compressed raw segments for original exchange messages, and
individual immutable JSON files for portable research reports.

Use one explicit data root. Current Windows collector and research tasks use
`D:/GitHub/Trade/data/live`; commands run from `gym-core` need `--data ../data`.

Backup/restore receipts are append-only, bounded and sanitized. Current status
selects the latest recorded time, independent of append order. A receipt does not
prove current archive availability, independent origin or physical-host recovery.

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
Older read-only snapshots remain usable; missing watermarks are disclosed and
quiet-period scans stay quote-driven. Quote and candle observations are immutable.
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
