# Structure and workflow ownership

The Python observatory owns public observations and paper research. The Node
model gateway owns provider configuration, sign-in and credentials. The Rust
executor owns privileged money-path policy and custody. Browser controls do not
combine these authorities.

| Layer | Owner | Contract |
| --- | --- | --- |
| Domain calculations | `domain/` | Exact decimals, bounded inputs, no filesystem or provider calls. `technical_features.py` is the shared streaming indicator engine; batch diagnostics, four indicator strategies and two compound strategies use it. |
| CLI composition | `cli.py`, `commands/` | One parser and dispatch entry point; command bodies grouped under research, account, maintenance and daemon owners. Common store selection and bounded offline JSON parsing have one owner. |
| Durable observations and artifacts | `adapters/` | Market storage, raw segments, run identities and protected credential helpers. DEMO and observed stores remain distinct. |
| Research workflows | `services/research_actions.py` | Fixed service actions shared by CLI and browser. No arbitrary subprocess, path, Python function or tool name is accepted. |
| Shared-cash portfolio replay | `services/portfolio.py`, `portfolio_research.py`, `ui/portfolio.js` | One native snapshot and cash book; bounded supervised calculations; verified saved records and derived performance; point-in-time FX. Separate from independent-account comparisons. |
| Margin paper workflow | `domain/margin.py`, `adapters/wallex_margin.py`, `services/margin.py`, `ui/margin.js` | Credential-free pinned public rules/loan/preview endpoints, immutable receipt clocks and currency-aware observed-quote paper positions. Shared supervised GUI/CLI actions; no margin write transport. |
| Hypotheses and schedules | `services/research_ledger.py` | Existing hypotheses, shadow observations, jobs and durable retry/report publication. |
| Availability and evaluations | `services/research_protocol.py` | Immutable observation vintages, resolution-time outcome memory and future evaluations consumed before reading holdout data. Local enforcement is not independent sealing. |
| Numeric review | `services/research_grounding.py`, `research_review.py` | Allowlisted saved-run arithmetic; performance, risk and cash-benchmark roles. Numeric agreement does not validate prose or causality. |
| Web composition | `api/server.py` | Existing observatory routes and loopback/token boundary. It installs separate model, research and offline-review workflow routes. |
| Offline ticket review | `api/offline_reviews.py`, `services/offline_review_journal.py` | The same canonical preview and hash-chain owner used by the CLI. Actual server review time, one acknowledgment/rejection, no T1 permission. |
| Protected operator intent | `api/operator_reviews.py`, `adapters/service_review.py`, `contracts/review_wire.py`, `ui/native-review.js` | Explicit token/same-origin relay to the fixed protected helper and OS-authenticated Rust pipe. Exact durable review, consume-once preparation and revocation; no money reservation, executable admission, arming, order transport or research/MCP dispatch. New binaries require installed-host qualification. |
| Browser workflows | `ui/app.js`, `models.js`, `research.js` | Existing shell/observatory views, AI settings and advanced research respectively. HTML text is escaped; returned reports use text content. Secrets are never browser storage. Each asset has a content-derived URL. |
| Model process bridge | `services/model_gateway.py` | Fixed executable/entry point, one private bounded JSON channel, correlated replies, single active request and process cleanup. No shell execution. |
| Provider controls | `model-gateway/control.mjs`, `host.mjs` | One pending OAuth session, explicit cancellation, strict configuration and encrypted stored-key operations. `runtime.mjs` remains the single completion/retry owner. |
| Credential persistence | `model-gateway/state.mjs` | Windows current-user DPAPI and private ACLs; provider/connection-scoped OAuth and API-key namespaces. Non-Windows fallback is private plaintext and disclosed by the UI. |
| Protected execution | `executor/`, `scripts/windows/` | Separate principal, permissions, durable outcomes and recovery. Research, model completions and offline acknowledgements grant no funded permission. |

## Browser capability map

| Workflow | Browser location | Scope or remaining difference |
| --- | --- | --- |
| Market, depth, quote/rule readiness | Markets | Existing public observations; no fabricated outage values. |
| Wallex margin rules, previews and LONG/SHORT paper replay | Paper research → Wallex margin | Actual per-market credit grid and collateral range, explicit public calculations, saved terms and source quotes. Closures/gaps do not synthesize settlement. Funded margin remains unavailable. |
| Strategy comparison and historical validation | Paper research | Twelve registry strategies, including two compound rules with explicit risk controls; native replay and saved artifacts. Historical selection is diagnostic. |
| Shared-cash portfolio replay | Paper research → Workbench | Dedicated EN/FA form, all observed market choices, 2–8 distinct bases with one quote currency; saved records, portfolio curve and FX status. The bounds are local research budgets, not venue restrictions. |
| Hypothesis/shadow/schedule registration | Advanced research workbench | Shared service validation; advanced JSON inputs. Existing job controls provide pause/resume/tick. Foreground continuous runner remains a terminal process. |
| Numeric claims, run review and outcome memory | Advanced research workbench | Saved IDs and exact allowlisted references; no invented lessons or analyst prose. |
| Future evaluation register/status/consume | Advanced research workbench | Actual clock, frozen engine/configuration, one attempt. Failures remain consumed; local ledger is not an independent custodian. |
| Observation vintages and screening | Advanced research workbench | Supplied observations plus explicit fixed official Federal Reserve RSS fetches with actual receipt clocks. Other vendor connections, independently authenticated content and rights are unverified. |
| Measurement-aligned ratios and differences | Advanced research workbench | Explicit measurement clocks, freshness/skew bounds and exact source/unit references; both inputs share a read snapshot. |
| Accounting, portfolio, forecast scoring, spreads, flow, technical timeframes | Advanced research workbench | Native calculations/recorded data with explicit absent values. This is an advanced input/report interface, not a dedicated chart for each model. |
| Provider/API-key/OAuth connections, preset sync/import/export, paid prompt | AI connections | Disabled by default. User initiates every key save/sign-in and paid prompt. SDK catalog support does not prove live entitlement. |
| Account and imported orders | Account journal and advanced workbench | Read-only sanitized observations, known-order native receipt references, saved partial-fill/fee-currency details and order-page imports. Actual protected service GETs, including explicit open/history pages, require the protected console and reviewed helper installation. Venue-key provisioning remains separate. |
| Tickets, evidence and venue rules | Offline ticket, Account journal, saved runs, Venue rules, advanced workbench | Canonical preview review, offline probe staging, modeled conversion, manual account/venue-fact imports and evidence decisions share existing native owners with the CLI. No execution permission is issued. |
| Protected operator intent | Operate, advanced JSON panel | Explicit service-context read and exact native approval/inspection/preparation/revocation through the same adapter as `gymctl operator-review`. DEMO disabled; no polling, automatic retry or order submission. Requires reviewed service/helper installation. |
| Candle crosscheck | Advanced research workbench | Bounded local reads with an exclusive receipt/fetch cutoff. Immutable candle revisions are retained from market schema 3 onward; discarded pre-migration history cannot be recovered. No provider fetch or quality-table mutation. |
| Portable HTML summary | Saved run | Token-protected download of the existing escaped, script-free allowlisted report. |
| Collector/session lifecycle | Terminal | The browser does not start arbitrary local processes or choose arbitrary filesystem paths. |
| Backup, restore, release checks, executor provisioning and STOP | Backups, Safety and protected console | Read-only sanitized backup/restore receipts now drive actual status. No current archive-presence or independent-host claim. Passphrases, service custody and executor authority stay outside browser forms. |

This map records actual interfaces and gaps. It is not a claim that every CLI
flag has a graphical equivalent or that the protected executor is qualified.
The unused generated `repo_core_source.txt` dump was removed; Git and the
maintained source tree provide versioned source history without a stale duplicate.

## Research workspace owners

`services/research_market.py` owns bounded coverage/readiness and comparable
recorded-market ranking. `services/replay_debugger.py` owns verified decision
inspection and supplied-fill comparisons. `domain/portfolio.py` owns exact
offline rebalance planning alongside existing entry sizing.

`services/experiment_registry.py` owns the append-only experiment/attempt/note
journal. Scenario runs reuse `paper.py` and `DataPortal` under one read snapshot;
outages filter receipts without changing the market store. `session.py` records
actual pre-decision balances and deduplicated rule snapshots. Its engine-version
change keeps new trace outputs from colliding with older immutable runs.

`replay_checkpoint.py` rebuilds a verified prefix and checks continuation against
both the saved result and a fresh full native replay. `replay_annotations.py`
keeps operator notes separate from immutable decision evidence. Registry pages
retain a fixed sequence ceiling across requests. `entry_locks.py` uses the
existing persistent rule ledger; `operator_actions.py` shares the existing
journal/conversion/probe owners between terminal and authenticated workbench.
The chart links recorded price, pre-decision equity and numeric feature panes
by actual decision index, without reconstructing missing historical features.

`research_process.py` supervises fixed heavy calculations in disposable isolated-
import Python processes with a 120-second deadline, bounded JSON and no inherited
credentials, PYTHONPATH or executable search path. It reaps the exact child before
releasing locks and distinguishes uncertain delivery from rollback. These ordinary
operator processes do not replace the separately qualified R0 AppContainer.
CLI, scheduler and web calculations reuse the same supervisor; API inspection
and explicit claim interruption remain available during work.

`news_feed.py` fetches only one pinned official public RSS URL on explicit request.
It records actual receipt knowledge through `ResearchProtocol`; it does not provide
general URL fetching, earlier vintages, a paid news provider or verified sentiment.
`backup_status.py` serializes append-only sanitized operation receipts for the
protected-console commands and authenticated GUI reads. It never handles a
passphrase or infers current archive availability from an old receipt.

`services/research_notes.py` prepares allowlisted saved-evidence packets and
validates role/citation/numeric-claim notes. Paid sending remains an explicit
operation through the existing model gateway. `ui/research.js` provides dedicated
coverage/recovery/replay controls plus advanced inputs for the other models.
See [research workspace contracts](../research-workspace.md) for CLI/API fields,
work limits, unknown historical state and unauthenticated input boundaries.

## Source adaptation

Archive follow-up owners: `strategy_audit.py` reuses the native paper engine and
point-in-time portal for selected causality/prehistory comparisons;
`return_bootstrap.py` reads verified saved equity with explicit gap/dependence
assumptions. `ui/replay-chart.js` renders bounded saved decisions, using the
existing replay route and exact labels rather than a second chart calculation
engine. `ResearchLedger` stores claim ownership in the existing version-1 report
JSON and retains attempt audit events; exact-claim interruption prevents stale
publication. It does not certify process liveness or termination. Inspection
and interruption bypass the workbench calculation lock while retaining token
authentication and SQLite serialization of mutations.

The exact Penguin source supplied in Downloads was inspected for provider-fleet
controls, encrypted storage, redaction and PKCE lifecycle concepts. The exact Pi
source was inspected for provider auth interactions, callback/manual input and
credential ownership. These concepts use native owners above, rather than a
second React server, credential database, login account or desktop framework.
The already-pinned public Pi SDK supplies actual provider OAuth and completion
implementations. No donor credential state, application runtime, private keys,
environment files or copied cryptographic implementation was imported.

The reviewed source entry points are Penguin's `packages/core/src/fleet/`
credential/OAuth modules and Pi's `packages/ai/src/auth/oauth/anthropic.ts` and
related provider modules. Source error bodies can contain tokens; the gateway
returns fixed local error codes and deliberately omits those diagnostics.
