# Review branches, 2026-11-16

The original 88-path working tree was preserved locally, then split into a stack
of review branches. Each branch starts at the previous row. No remote branch,
PR, merge or protected executor publication was performed. `master` stays at
`35a76be`. Original bytes remain in the local handoff stash and the ignored
`.pi/change-split/` snapshot; do not apply that stash over these commits.

| Local branch | Commit | Full Python passed | Full native passed |
| --- | --- | --- | --- |
| `codex/remove-retired-workflows` | `1550e13` | 1800 | 189 |
| `codex/research-evidence` | `2cd2b48` | 1802 | 189 |
| `codex/paper-fees-stops` | `6b95df0` | 1807 | 189 |
| `codex/operator-review-v2` | `0b37948` | 1807 | 189 |
| `codex/executor-active-holds` | `b064d60` | 1807 | 189 |
| `codex/executor-checkpoints` | `d1a5022` | 1807 | 193 |
| `codex/recorder-import` | `6343749` | 1808 | 193 |
| `codex/workspace-copy` | `05bb46c` | 1808 | 193 |
| `codex/documentation-refresh` | `6f83f4e` | 1808 | 193 |
| `codex/paper-time-exit-fix` | `de6dbbb` | 1809 | 193 |
| `codex/balance-receipt-contract` | `e8e1987` | 1809 | 198 |
| `codex/native-balance-receipts` | `9c3a175` | 1809 | 208 |
| `codex/arming-integration` | `9035ef6` | 1813 | 220 |
| `codex/owner-evidence-review` | `a34e72a` | 1813 | 224 |
| `codex/checkpoint-integration` | `ca520b9` | 1813 | 230 |
| `codex/local-backup-integration` | `14af3bd` | 1813 | 231 |
| `codex/native-risk-measurements` | `b4e6946` | 1813 | 238 |
| `codex/native-arm-helper` | `f81b4a4` | 1813 | 240 |
| `codex/native-arm-runtime` | `cf368fa` | 1813 | 243 |
| `codex/native-order-admission` | `c2732e0` | 1813 | 247 |
| `codex/native-order-effects` | `5bbe838` | 1813 | 255 |
| `codex/native-order-settlement` | `e1017e0` | 1813 | 261 |
| `codex/executor-authority-faults` | `16a3912` | 1813 | 263 |

Every row has its own full Python/native check run, Ruff lint, complexity
ratchet, Clippy, Rust format and whitespace checks. Exact source hashes, commands
and result receipts are local under `.pi/change-split/checks/<branch-suffix>/`.
Each Python run has 23 skips and the existing aiohttp timeout deprecation; the
optional Rust-kernel Python path is not installed. Native runs are on Windows. The arming-integration row was rerun on its exact
commit in an isolated checkout; it is not inferred from a later combined branch.
Hosted Linux/VM, mutation and release qualification were not run for this stack.

## Paper follow-up after the split

Source review found that a waiting venue stop suppressed an already due time
exit when both thresholds applied. A regression case first returned EMA warmup
instead of PAPER_TIME_EXIT, reproducing the lost exit. The separate
`codex/paper-time-exit-fix` branch selects the time exit while the venue stop
continues to depend on its trade trigger. Engines move to 14/15; saved 12/13
artifacts remain unchanged. The default output digest stays the same, and golden
run IDs change with the engine version. Its full check receipt uses the same
local checks directory as the other branches.

## Review points

- Research evidence stays separate from the engine change. `implied-toman-rate` failed ranking;
  2026 was not scored. The daily-trend accounting artifact uses engine 10. Its
  receipt explains how to reproduce that version without replacing the artifact
  or rescoring already consumed data.
- The paper batch bumps market/limit engines to 12/13. The default output hash
  stays `85bc4a119e7a2a9d`; new run IDs carry the version change. Review found a
  one-side fee override incorrectly dropping the other side's market schedule;
  two regression cases reproduced it before the fix and now pass.
- Native review frames, holds and checkpoints are separate commits. Checkpoints
  still hash the full chain; oversized snapshots fall back to verified replay.
  Independent background state comparison, indexed bounded history and scale checks are complete in later rows.
  These checks do not qualify funded execution. The owner reviews every change
  to `domain/` and `executor/` before publication.
- The recorder's first scheduled run after branch switching exited 2. Its
  installer now publishes a hash-checked standalone script under local data,
  independent of the checkout. The task was exercised using that copy and
  completed with result 0 on 2026-11-16; next run is 2026-11-17 04:15 Tehran.
  It uses the existing limited interactive-user task, not an off-machine backup.
- Fresh Edge verification passed all nine DEMO routes, EN/FA, light/dark,
  375/600-pixel mobile controls, keyboard/dialog/recovery interactions, and axe
  with zero violations. All 23 UI tests passed. English strings over 160
  characters: zero. Real account, venue fills and native installation were not
  inferred from this synthetic browser run.
- Python dependency audit and the axe test dependency's npm audit reported no
  known vulnerabilities. The local project itself is not a PyPI package.

## Formatting decision

Keep Ruff lint and scoped edits. A fresh `ruff format --check` on `src` and
`tests` would reformat 372 files, with 11 already formatted. A blanket rewrite
would obscure the requested money/authority review, so it is not part of this
change set. Rust formatting remains enforced.

## Current native boundary

[ADR 0008](../../../docs/adr/0008-balance-observation-ordering.md) is implemented in
the native producer and consumers. Exact service-side fees/books, own-fill loss
and inventory, committed cash, holds, elevated approval, one-shot LIMIT transport
and atomic settlement now compose. The final readiness branch adds the direct
producer-fault-to-controller regression and refreshes the status documentation;
its full receipt is in `executor-review-readiness` alongside these local logs.

The original master and handoff stash are retained. No remote PR, push, merge,
protected publication, real arming or order occurred. Review branches form a
stack and must be reviewed in order; the owner reviews every domain/executor
change. Code completeness and synthetic local fault checks do not qualify the
installed host or establish a trading edge.

Publication/installed-host qualification and the registered 2027-02-08 prospective
decision remain pending. Off-machine backup and second-host restore were canceled.
The native backup primitive makes local verified copies only and installs no schedule.
See [native lifecycle](../../../executor/docs/native-order-lifecycle.md) for the exact
manual LIMIT scope, owner evidence and uncertain-order boundaries.
