# Storage ownership

Operational records already use SQLite. Retain this layout: SQL for queries and
transactions, compressed raw segments for original exchange messages, and
individual immutable JSON files for portable research reports.

Use one explicit data root. Current Windows collector and research tasks use
`D:/GitHub/Trade/data/live`; commands run from `gym-core` need `--data ../data`.
The older `gym-core/data/live` store is separate and is not overwritten or silently
selected as a fallback.

On 7 November 2026, two missing backup receipts from the older store were appended
to the canonical journal after integrity-checked snapshots of both databases.
The source database remains intact. The merge is bounded, validates both schemas
and every receipt before writing, deduplicates exact receipt content, preserves
recording times and cannot update/delete old rows. Status selects by recording
time, so importing an older receipt does not supersede a newer operation.
The local migration evidence is `.pi/operations/backup-receipts-20261107T125534647652Z.json`;
the snapshots are under `data/maintenance-snapshots/20261107T125534647652Z`.
This consolidates historical display receipts; it does not prove current archive
availability, independent origin or physical-host recovery.

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
quiet-period scans stay quote-driven. Forward migration does not rewrite older
quote or candle history. Raw audit segments retain their existing ownership.

The remaining application JSONL is a compressed audit archive, not a query
database. Normalized SQL rows already hold the fields used by the application
and refer back to raw messages through segment/sequence references. Closed
segments have byte counts and SHA-256 hashes in SQL. Rewriting them into SQL
would duplicate that projection and require migrating raw references, backup
manifests and recovery readers. No such migration is justified by the current
workload. Keep the archive and its SQL index together when backing up or restoring.

Collecting every market writes roughly 200 MB of raw archive per hour. The collector
stops with a clear error when its volume has less than 5 GiB free, instead of filling
the disk. Move finished days elsewhere with
`gymctl raw-move --before YYYYMMDD --to <other-drive-folder>`; it never moves the
current UTC day and refuses if a destination day already exists. Segment files are
created exclusively, so two writers in the same hour can never share one file.

Read-only qualification on 2026-11-05 UTC inspected all eight existing public and
operator databases listed above: each returned `ok` from `PRAGMA quick_check(1)`.
Three recent closed raw segments matched their SQL manifest hashes. This sampled
archive check does not certify every historical message or inspect the protected
Executor database. The credential database was checked separately during the
isolated gateway qualification described in the model-gateway README.
