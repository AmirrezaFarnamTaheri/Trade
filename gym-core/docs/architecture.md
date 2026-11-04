# Structure and workflow ownership

The Python observatory owns public observations and paper research. The Node
model gateway owns provider configuration, sign-in and credentials. The Rust
executor owns privileged money-path policy and custody. Browser controls do not
combine these authorities.

| Layer | Owner | Contract |
| --- | --- | --- |
| Domain calculations | `domain/` | Exact decimals, bounded inputs, no filesystem or provider calls. `technical_features.py` is the shared streaming indicator engine; batch diagnostics and the four new strategies use it. |
| Durable observations and artifacts | `adapters/` | Market storage, raw segments, run identities and protected credential helpers. DEMO and observed stores remain distinct. |
| Research workflows | `services/research_actions.py` | Fixed service actions shared by CLI and browser. No arbitrary subprocess, path, Python function or tool name is accepted. |
| Hypotheses and schedules | `services/research_ledger.py` | Existing hypotheses, shadow observations, jobs and durable retry/report publication. |
| Availability and evaluations | `services/research_protocol.py` | Immutable observation vintages, resolution-time outcome memory and future evaluations consumed before reading holdout data. Local enforcement is not independent sealing. |
| Numeric review | `services/research_grounding.py`, `research_review.py` | Allowlisted saved-run arithmetic; performance, risk and cash-benchmark roles. Numeric agreement does not validate prose or causality. |
| Web composition | `api/server.py` | Existing observatory routes and loopback/token boundary. It installs separate model, research and offline-review workflow routes. |
| Offline ticket review | `api/offline_reviews.py`, `services/offline_review_journal.py` | The same canonical preview and hash-chain owner used by the CLI. Actual server review time, one acknowledgment/rejection, no T1 permission. |
| Browser workflows | `ui/app.js`, `models.js`, `research.js` | Existing shell/observatory views, AI settings and advanced research respectively. HTML text is escaped; returned reports use text content. Secrets are never browser storage. Each asset has a content-derived URL. |
| Model process bridge | `services/model_gateway.py` | Fixed executable/entry point, one private bounded JSON channel, correlated replies, single active request and process cleanup. No shell execution. |
| Provider controls | `model-gateway/control.mjs`, `host.mjs` | One pending OAuth session, explicit cancellation, strict configuration and encrypted stored-key operations. `runtime.mjs` remains the single completion/retry owner. |
| Credential persistence | `model-gateway/state.mjs` | Windows current-user DPAPI and private ACLs; provider/connection-scoped OAuth and API-key namespaces. Non-Windows fallback is private plaintext and disclosed by the UI. |
| Protected execution | `executor/`, `scripts/windows/` | Separate principal, permissions, durable outcomes and recovery. Research, model completions and offline acknowledgements grant no funded permission. |

## Browser capability map

| Workflow | Browser location | Scope or remaining difference |
| --- | --- | --- |
| Market, depth, quote/rule readiness | Markets | Existing public observations; no fabricated outage values. |
| Strategy comparison and historical validation | Paper research | Ten registry strategies; native replay and saved artifacts. Historical selection is diagnostic. |
| Hypothesis/shadow/schedule registration | Advanced research workbench | Shared service validation; advanced JSON inputs. Existing job controls provide pause/resume/tick. Foreground continuous runner remains a terminal process. |
| Numeric claims, run review and outcome memory | Advanced research workbench | Saved IDs and exact allowlisted references; no invented lessons or analyst prose. |
| Future evaluation register/status/consume | Advanced research workbench | Actual clock, frozen engine/configuration, one attempt. Failures remain consumed; local ledger is not an independent custodian. |
| Observation vintages and screening | Advanced research workbench | User-supplied source/series/unit-specific observations. No vendor connection or authenticated news feed is implied. |
| Measurement-aligned ratios and differences | Advanced research workbench | Explicit measurement clocks, freshness/skew bounds and exact source/unit references; both inputs share a read snapshot. |
| Accounting, portfolio, forecast scoring, spreads, flow, technical timeframes | Advanced research workbench | Native calculations/recorded data with explicit absent values. This is an advanced input/report interface, not a dedicated chart for each model. |
| Provider/API-key/OAuth connections, preset sync/import/export, paid prompt | AI connections | Disabled by default. User initiates every key save/sign-in and paid prompt. SDK catalog support does not prove live entitlement. |
| Account and imported orders | Account journal | Existing read-only observations. Venue-key provisioning remains protected-console work. |
| Tickets, evidence and venue rules | Offline ticket, Account journal, saved runs, Venue rules | Canonical preview saving and offline acknowledgment/rejection are available in the GUI. Probe-budget staging, conversion evaluation, manual journal imports and some evidence decision commands still have terminal-only inputs. |
| Candle crosscheck | Advanced research workbench | Bounded local reads with explicit exclusive receipt/fetch cutoff. No provider fetch or quality-table mutation. Superseded venue vintages are unavailable. |
| Portable HTML summary | Saved run | Token-protected download of the existing escaped, script-free allowlisted report. |
| Collector/session lifecycle | Terminal | The browser does not start arbitrary local processes or choose arbitrary filesystem paths. |
| Backup, restore, release checks, executor provisioning and STOP | Backups, Safety and protected console | Explicit guidance/status limits. Passphrases, service custody and executor authority stay outside browser forms. |

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

`services/research_notes.py` prepares allowlisted saved-evidence packets and
validates role/citation/numeric-claim notes. Paid sending remains an explicit
operation through the existing model gateway. `ui/research.js` provides dedicated
coverage/recovery/replay controls plus advanced inputs for the other models.
See [research workspace contracts](research-workspace.md) for CLI/API fields,
work limits, unknown historical state and unauthenticated input boundaries.

## Source adaptation

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
