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
| Web composition | `api/server.py` | Existing observatory routes and loopback/token boundary. It installs separate model, research and offline-review workflow routes. Deliberate public reads (loopback Host check only, no token): `PUBLIC_READS` in `api/__init__.py` plus the full record at `GET /api/runs/{id}`, which holds paper results and no credentials; its `/summary` views stay token-gated. `tests/test_api_contract.py` fails when a route becomes public without being listed. |
| Offline ticket review | `api/offline_reviews.py`, `services/offline_review_journal.py` | The same canonical preview and hash-chain owner used by the CLI. Actual server review time, one acknowledgment/rejection, no T1 permission. |
| Protected operator intent | `api/operator_reviews.py`, `adapters/service_review.py`, `contracts/review_wire.py`, `ui/native-review.js` | Explicit token/same-origin relay to the fixed protected helper and OS-authenticated Rust pipe. Exact durable review, consume-once preparation and revocation; no money reservation, executable admission, arming, order transport or research/MCP dispatch. New binaries require installed-host qualification. |
| Browser workflows | `ui/app.js`, `markets.js`, `research-controls.js`, `operations.js`, `runs.js`, `models.js`, `research.js` | Shell/common state, markets, comparisons/jobs, operator journals/safety, saved results, AI settings and advanced research respectively. HTML text is escaped; returned reports use text content. Secrets are never browser storage. Each asset has a content-derived URL. |
| Model process bridge | `services/model_gateway.py` | Fixed executable/entry point, one private bounded JSON channel, correlated replies, single active request and process cleanup. No shell execution. |
| Provider controls | `model-gateway/control.mjs`, `host.mjs` | One pending OAuth session, explicit cancellation, strict configuration and encrypted stored-key operations. `runtime.mjs` remains the single completion/retry owner. |
| Credential persistence | `model-gateway/state.mjs` | Windows current-user DPAPI and private ACLs; provider/connection-scoped OAuth and API-key namespaces. Non-Windows fallback is private plaintext and disclosed by the UI. |
| Protected execution | `executor/`, `scripts/windows/` | Separate principal, permissions, durable outcomes and recovery. Research, model completions and offline acknowledgements grant no funded permission. |

## Browser capability map

| Workflow | Browser location | Scope or remaining difference |
| --- | --- | --- |
| Market, depth, quote/rule readiness | Markets | Existing public observations; no fabricated outage values. |
| Wallex margin rules, previews and LONG/SHORT paper replay | Paper research → Wallex margin | Actual per-market credit grid and collateral range, explicit public calculations, saved terms and source quotes. Closures/gaps do not synthesize settlement. Funded margin remains unavailable. |
| Strategy comparison and historical validation | Paper research | Sixteen registry strategies, including two compound rules with explicit risk controls; native replay and saved artifacts. Historical selection is diagnostic. |
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
| Candle crosscheck | Advanced research workbench | Bounded local reads with an exclusive receipt/fetch cutoff. Missing historical revisions remain unavailable. No provider fetch or quality-table mutation. |
| Portable HTML summary | Saved run | Token-protected download of the existing escaped, script-free allowlisted report. |
| Collector/session lifecycle | Terminal | The browser does not start arbitrary local processes or choose arbitrary filesystem paths. |
| Backup, restore, release checks, executor provisioning and STOP | Backups, Safety and protected console | Read-only sanitized backup/restore receipts now drive actual status. No current archive-presence or independent-host claim. Passphrases, service custody and executor authority stay outside browser forms. |

This map records actual interfaces and gaps. It is not a claim that every CLI
flag has a graphical equivalent or that the protected executor is qualified.

## Research workspace owners

| Owner | Responsibility |
| --- | --- |
| research_market.py | Recorded coverage, readiness, screening and comparable market groups |
| replay_debugger.py, replay_checkpoint.py, replay_annotations.py | Verified inspection, continuation and separate operator notes |
| experiment_registry.py, research_notes.py | Durable trials/failures, evidence packets and analyst notes |
| research_process.py | Bounded isolated calculation supervisor shared by CLI/API/scheduler |
| operator_actions.py | Existing local journal, conversion and offline probe workflows |
| news_feed.py | Explicit fixed-origin public receipt retrieval |
| backup_status.py | Append-only operation receipts and chronological status |

Request fields, limits, clock semantics and recovery behavior have one maintained
owner: [research workspace contracts](research-workspace.md). Portfolio-specific
contracts are in [portfolio replay](portfolio-replay.md).
