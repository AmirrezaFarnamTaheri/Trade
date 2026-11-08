# Phase 0 housekeeping — repository change log and operator gate

Scope: paper-only research, repo hygiene and reports. **No live execution, credentials,
order authority or automatic funded actions.** This log distinguishes repository
changes from cleanup that must be performed on the operator's Windows machine.

| Item | Repository change | Operator-machine acceptance |
| --- | --- | --- |
| 1 | PR #18 was merged to `master` before this branch was created. Feature branches were confirmed to have zero commits ahead of `master`. | Local branch cleanup and **remote branch deletion** remain unperformed; remote deletion requires explicit approval. |
| 2 | `.impeccable/` and `.ruff_cache/` are ignored. Tracked design references remain in Git; ignore rules do not erase tracked files. | Move `.pi`, `.impeccable`, `.statamcp`, `.unipi` outside the checkout after reviewing contents. Review `target/` and `review/` before removing temporary outputs. |
| 3 | `gymctl` from a source checkout defaults to the repository's `data/` independent of working directory; explicit `--data` is preserved. Regressions cover both working directories. | Stop all writers, preserve both stores and migrate any legacy SQLite receipt journal using SQLite backup APIs and review. Do not overwrite a canonical file or delete the legacy journal. |
| 4 | Exact contract fixtures already have `-text` Git attributes. Windows CI now verifies these attributes and a clean tracked checkout. | If a local working tree still shows two line-ending-only fixture changes, restore just those known files after preserving any intentional edits. Do not discard unrelated work. |
| 5 | Consolidate the scheduler into the CLI and review/notes/derived-series functions into the research action owner. Update regression-test imports. | No operator action. |
| 6 | Move translations, shared formatting, overview, alerts and per-view events from `ui/app.js` into deferred classic scripts, leaving routing/loading in `app.js`. Protect with syntax, DOM and browser checks. | Confirm current-build EN/FA and Windows browser behavior where deployed. |
| 7 | Retain ambiguous identical public trade prints, count potential duplicate capacity per limit fill, and label first observed Tehran-day-mid price-band references as estimates. Use a new engine identity only for limit runs. | These are paper estimates, **not** proven venue duplicate fills, band rules or live cost evidence. |

## Operator safeguards

Never move or delete `data/live`, `data/demo`, protected Executor ledgers,
credentials, backups, immutable run artifacts or signed recovery evidence as
part of a tool-cache cleanup.

Before changing the old receipt location, inspect both
`gym-core/data/live/backup_status.sqlite3` and
`data/live/backup_status.sqlite3`. An open SQLite database may have unflushed
WAL content: stop producers, take a consistent SQLite backup, verify immutable
receipt guards and preserve originals. If both files exist, reconcile their
append-only receipts with an explicitly reviewed migration—**never overwrite**.

This PR can validate the repository implementation, but it cannot attest that
cleanup, database relocation or installed-host checks happened on a machine
that the GitHub connector cannot access. The operator must record that evidence
separately before treating Phase 0 as physically complete.
