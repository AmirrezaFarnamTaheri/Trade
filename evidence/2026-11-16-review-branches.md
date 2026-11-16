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
| `codex/documentation-refresh` | branch containing this receipt | local check receipt | local check receipt |

Every row has its own full Python/native check run, Ruff lint, complexity
ratchet, Clippy, Rust format and whitespace checks. Exact source hashes, commands
and result receipts are local under `.pi/change-split/checks/<branch-suffix>/`.
Each Python run has 23 skips and the existing aiohttp timeout deprecation; the
optional Rust-kernel Python path is not installed. Native runs are on Windows.
Hosted Linux/VM, mutation and release qualification were not run for this stack.

## Review points

- Research evidence stays separate from the engine change. T10 failed ranking;
  2026 was not scored. The daily-trend accounting artifact uses engine 10. Its
  receipt explains how to reproduce that version without replacing the artifact
  or rescoring already consumed data.
- The paper batch bumps market/limit engines to 12/13. The default output hash
  stays `85bc4a119e7a2a9d`; new run IDs carry the version change. Review found a
  one-side fee override incorrectly dropping the other side's market schedule;
  two regression cases reproduced it before the fix and now pass.
- Native review frames, holds and checkpoints are separate commits. Checkpoints
  still hash the full chain; oversized snapshots fall back to verified replay.
  Background state comparison, bounded history and scale acceptance remain open.
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

## Next native work

[ADR 0008](../docs/adr/0008-balance-observation-ordering.md) records the owner's
accepted service-receipt design: conservative two-read amounts, own-activity
fencing, disagreement disarm, 120-second freshness and honest receipt naming.
Order/fill timestamps can cross-check activity; they cannot establish balance
snapshot order. Receipt production/admission and privileged arm/STOP composition
remain implementation work. No funded order or service installation is approved
by these local commits. Off-machine backup and second-host restore were canceled.
