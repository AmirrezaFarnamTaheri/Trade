# TradingGYM codebase structure review

**Recommendation.** Keep the current Python observatory, Rust executor, shared contracts and Windows tooling. Most of the maintenance cost is inside the Python package. Start by restoring its existing dependency rules, give research actions one owner for dispatch policy, and separate portfolio reporting from the mutable replay loop. Keep the currently documented command, route, artifact and privilege boundaries throughout.

**Scope.** Reviewed the November 24, 2026 working tree, including the ensemble implementation committed during this review as `6f2abe5`. Counts below are a working-tree snapshot. The dependency inventory resolves static Python imports, including imports inside functions. It omits dynamic dispatch, runtime plugin discovery and calls from scripts and tests. The proposed directory and symbol names below are recommendations.

## Where maintenance effort concentrates

| Area | Evidence | Implication |
|---|---|---|
| Python package | 206 Python modules under `src/gym`, including package initializers. Of these, 106 are in services and 68 in domain. | Retain the existing layers and add subject packages where a workflow has several related owners. Merely distributing an alphabetized file list into more folders would leave the dependencies intact. [Current architecture](../gym-core/docs/architecture.md) |
| Research dispatch | `research_actions.py` has 976 lines and imports 57 distinct internal modules. The CLI, API and supervised worker converge on its dispatcher. The handler table, CLI visibility, payload expectations and heavy-worker list are maintained in several places. | The practical question when adding an action is which handler runs, who can call it and under which execution policy. Make that answer inspectable in one place. [Handlers and dispatcher](../gym-core/src/gym/services/research_actions.py#L769) · [Worker policy](../gym-core/src/gym/services/research_process.py#L27) |
| Portfolio replay | `services/portfolio.py` has 1,208 lines. Its `_Replay` class includes FX routing, reservation-aware valuation, sizing, market events, checkpoints, input digests and output construction. | Extract deterministic output and input construction first. Retain one owner for account state, clock advancement, order priority and the database snapshot. [Replay](../gym-core/src/gym/services/portfolio.py#L151) |
| Imports and cycles | Five multi-module groups had reciprocal dependency paths. One connects `market_models`, `forecast_evaluation` and the domain portfolio module. The others connect performance/portfolio diagnostics, the strategy registry/blends, evidence/trial governance, and research/temporal validation. Some edges are deferred imports. | Break a cycle when it obstructs changing or testing a feature. High fan-in alone is healthy for a stable primitive such as the clock or money representation. [Market-model dispatcher](../gym-core/src/gym/domain/market_models.py#L370) · [Validation's private import](../gym-core/src/gym/services/temporal_validation.py#L16) |
| Operational and research scripts | 62 top-level Python scripts under `gym-core/scripts`. The earlier inventory classified 38 and identified immutable trial reproducers. CI also invokes venue scripts directly. | Classify additions as maintained commands, study runners, frozen reproducers or developer tools. Preserve the exact invocation and historical code identity for registered experiments. [Previous inventory](../evidence/2026-11-21-performance-and-hygiene-audit.md#L51) · [Recorder workflow](../.github/workflows/venue-recorder.yml) |

## Restore the domain boundary first

The current architecture tests yielded **3 passes and 1 failure**. The failure identifies `pathlib.Path` in the tracked signal gatekeeper. Its `append_mix_journal_v2` function creates directories and writes JSONL alongside statistical calculations. A full scan using the same banned-import rules also found `sqlite3` in the ensemble timeframe panel. Pytest stops at the first offender in that parametrized case. The action registry and API contract tests passed **6/6**.

Move JSONL persistence to an adapter and update the recorder, evaluator and test callers together. Keep the entry type and calculation functions pure. Put the keyed candle reader in a SQLite adapter, retain `BarPoint` and resampling in domain, and compose the daily/hourly parity audit in a research service. Check the actual receipts, serialized fields, ordering, inclusive endpoints and prior error behavior before and after extraction. Improve the architecture test to report every offending path in one failure. Exempting these imports would erase the rule that makes the ownership clear. [Architecture test](../gym-core/tests/test_architecture.py) · [Journal writer](../gym-core/src/gym/domain/signal_gatekeeper.py#L193)

## Target organization

The following are the first destinations worth introducing. Existing modules can stay where they are until a specific responsibility moves. Keep package initializers light so a public observation command can start without loading research dependencies.

```text
gym-core/src/gym/
  domain/                 Financial rules, value types and pure calculations
  adapters/               SQLite, file journals, market feeds, protected-service client
  services/
    actions/              Fixed action catalogue, dispatch and handler groups
    portfolio_replay/     Replay orchestration, valuation, receipts and checkpoints
    experiments/          Study orchestration, chronological evaluation, optional fitting
  api/                    HTTP composition, authorization and route modules
  commands/               CLI parsing and command adapters
  contracts/              Python implementation of shared wire contracts
  ui/                     Browser assets, workspace features and EN/FA vocabulary
```

The proposed `experiments/` name avoids a collision with the existing `services/research.py` entry point. Keep the top-level `contracts/` authoritative for cross-language formats and fixtures. [Wire contracts](../contracts/v1/README.md)

### Research actions and model experiments

Keep the public `research_action(...)` callable and its actual-clock, store and input checks. Extend the existing fixed handler table with declarative metadata for action names, CLI/browser availability, input kind and supervised-worker requirement. Derive the current lookup tables from it, while allowing explicit CLI-local commands such as `start`. Keep HTTP authentication, authorization and route exposure at their existing boundary. Browser visibility is a presentation decision. A list command should be able to inspect metadata without importing the collector, fitting libraries or all the handlers. Start the extraction with a read-only market-report group. Then move portfolio and protocol handlers separately, preserving the worker's indeterminate-commit and retry behavior. [API dispatch](../gym-core/src/gym/api/research.py#L46) · [CLI dispatch](../gym-core/src/gym/commands/research.py#L510) · [Action catalogue tests](../gym-core/tests/test_action_registry.py)

Use the new ensemble as the first example of a maintainable study. Its runner currently includes per-arm simulation, training, reconciliation, Markdown writing and CLI wiring. Give the research service one callable that accepts inputs and returns a structured result. Keep optional model fitting outside the default application import path. Render JSON and Markdown from that same result, and leave the named script as the reproducible launcher. Compare the new paper ledger with the existing shared-cash replay on common fixtures before sharing code. A single-currency candle simulation and a reservation-aware multi-currency book have different contracts. Consolidate only operations whose quantities, fee semantics and failure behavior match. [Research dependency group](../gym-core/pyproject.toml#L17) · [Shared-cash replay entry point](../gym-core/src/gym/services/portfolio.py#L101)

### Portfolio and dependency cycles

Split the replay in this order: receipt serialization and input manifests, read-only valuation, then route selection. Give each extraction the smallest explicit inputs it needs. Passing the entire replay object to every new module would hide the original coupling. Keep mutations of cash, units, working orders and reservations coordinated by the replay owner. After each slice compare a single-currency case, a multi-currency case, and checkpoint/resume through the normal portfolio entry point. Compare exact fees, fill order, cash, units, NAV, and saved output fields. [Valuation](../gym-core/src/gym/services/portfolio.py#L516) · [Checkpoint creation](../gym-core/src/gym/services/portfolio.py#L820) · [Output construction](../gym-core/src/gym/services/portfolio.py#L965)

For the first cycle cleanup, move the shared snapshot-comparison core out of the research dispatcher. Both comparison and temporal validation can call it directly. For market models, separate common parsing and validation from the artifact evaluation dispatcher so leaf calculations can use the primitives without importing the module that dispatches back to them. For strategy blends, let composition supply the strategy factory explicitly. Characterize previously valid and rejected nested blends first. Make one ownership change per review.

## The constraint that changes the migration plan

`_engine_digest()` hashes **both relative paths and contents of all Python files under the gym package**. Moving a file, adding a forwarding module, or editing an unrelated Python UI handler can change the identity checked by research protocols and checkpoint resumption. A compatibility import preserves callers but cannot preserve that digest. Also, moving the function deeper without changing its `parents[1]` root would change which files are covered. [Engine identity](../gym-core/src/gym/services/research_protocol.py#L25) · [Checkpoint enforcement](../gym-core/src/gym/services/replay_checkpoint.py#L43)

Before landing the first source refactor, inventory outstanding pinned evaluations and checkpoints. Retain the exact checkout or source snapshot for any in-progress work, including relevant untracked inputs. Mark new runs with their actual engine identity and verify that old receipts remain readable and mismatches are rejected. Changing what an engine fingerprint covers deserves its own versioned design and compatibility tests. Never rewrite an old receipt to give it the new digest.

## Other parts of the repository

- **Rust.** The four workspace crates already separate policy, persistence, IPC and the Windows service. PyO3 builds separately. Keep these build and privilege boundaries. If working on `offline_recovery.rs` (2,604 lines), start by extracting the record encoding/decoding functions behind the existing module interface. Verify golden bytes, previously recorded journal replay, truncated records, and checkpoint/recovery parity. Approval state transitions and durable append ordering belong in a later, independent review. [Workspace](../Cargo.toml) · [Recovery module](../executor/exec-svc/src/offline_recovery.rs)
- **Browser and API.** The 1,007-line `workspace-config.js` is mostly bilingual vocabulary with token bootstrap at the top. Separate vocabulary and bootstrap when either changes. Keep EN/FA keys paired, asset hashes and load order valid, and preserve RTL and keyboard behavior. On the server, follow the existing route installation pattern for coherent handler families. Keep the loopback/token middleware and explicit public reads centrally auditable. [Browser configuration](../gym-core/src/gym/ui/workspace-config.js) · [HTTP and asset composition](../gym-core/src/gym/api/server.py)
- **Tests and CI.** The working tree has 295 Python `test_*.py` files. They already use behavior-based names. Preserve test discovery and documented commands. Group tests by capability when moving their owner, after checking direct CI paths, relative fixtures and `__file__` lookups. Prefer action-catalogue and served-browser assertions where a test currently depends on a JavaScript source regex. In the complexity ratchet, the subprocess invocation pins a different Ruff version from the declared dev dependency and parses empty stdout as an empty result. Align the tool versions and distinguish analyzer failure from a genuinely empty finding set. [Test conventions](../gym-core/tests/README.md) · [Complexity ratchet](../gym-core/scripts/complexity_ratchet.py) · [Project dependencies](../gym-core/pyproject.toml)
- **Docs, evidence and local state.** Use the existing documentation index to distinguish operational guidance, design proposals, frozen trials and dated evidence. Update the existing ownership map with each migration. Treat `data/`, build outputs, Graphify output and the local source bundle as runtime or generated state. At inspection, `model-gateway/` contained only `node_modules/` and had no tracked files. It provides no basis for a new service boundary. [Documentation index](../gym-core/docs/README.md) · [Root layout](../README.md)

## Suggested review sequence

| Order | Deliverable | Acceptance evidence |
|---|---|---|
| 1 | Inventory active engine identities. Extract journal and candle I/O from domain. | Architecture tests pass. Journal bytes and candle/parity fixtures retain their behavior. Older engine identities remain distinguishable. |
| 2 | Consolidate action metadata and migrate one read-only handler group. | Same exported action names, input errors, CLI choices, HTTP exposure and worker selection. Existing action/API tests plus representative CLI, HTTP and child-worker calls agree. |
| 3 | Extract replay receipts, valuation and routing in individually reviewable changes. | The shared-cash cases, saved records, checkpoints and exact monetary results match the frozen reference under the documented identity policy. |
| 4 | Establish the study-runner pattern on the new ensemble, then retire a concrete import cycle. | The named research command produces the same structured result. A default install imports and starts without research extras. The targeted cycle disappears from the static graph. |
| 5 | Apply the Rust, browser and test splits during the next substantive change to those owners. | Run the affected crate/fixture checks or browser/asset checks, then the repository's maintained validation commands. |

The first two changes give a contributor a clear place to add a data reader or a research action. They also create useful boundaries for the larger portfolio extraction without requiring a repository-wide move.
