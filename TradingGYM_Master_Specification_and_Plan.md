# TradingGYM: Master Specification and Plan

This historical specification is retained in the [full reference](gym-core/docs/archive/master-specification.md).
Current product commitments live in [PRODUCT](PRODUCT.md); delivery state and acceptance work live in the
[implementation plan](gym-core/docs/implementation-plan.md) and [current status](gym-core/docs/system-status.md).
The original section headings below preserve existing inbound links. They do not certify implementation.

### How to read this document

[Read the retained section](gym-core/docs/archive/master-specification.md#how-to-read-this-document).

### Executive summary

[Read the retained section](gym-core/docs/archive/master-specification.md#executive-summary).

### Why the plan looks like this (findings that shaped it)

[Read the retained section](gym-core/docs/archive/master-specification.md#why-the-plan-looks-like-this-findings-that-shaped-it).

## 0. The product in one page

[Read the retained section](gym-core/docs/archive/master-specification.md#0-the-product-in-one-page).

### 0.1 What the operator should experience

[Read the retained section](gym-core/docs/archive/master-specification.md#01-what-the-operator-should-experience).

### 0.2 Non-negotiable boundaries and deliberate simplifications

[Read the retained section](gym-core/docs/archive/master-specification.md#02-non-negotiable-boundaries-and-deliberate-simplifications).

### 0.3 Labels and evidence

[Read the retained section](gym-core/docs/archive/master-specification.md#03-labels-and-evidence).

### 0.4 Users, jobs and success measures

[Read the retained section](gym-core/docs/archive/master-specification.md#04-users-jobs-and-success-measures).

### 0.5 The mode ladder

[Read the retained section](gym-core/docs/archive/master-specification.md#05-the-mode-ladder).

## 1. Scope, product principles and operator control

[Read the retained section](gym-core/docs/archive/master-specification.md#1-scope-product-principles-and-operator-control).

### 1.1 Fixed scope

[Read the retained section](gym-core/docs/archive/master-specification.md#11-fixed-scope).

### 1.2 Principles applied as engineering decisions

[Read the retained section](gym-core/docs/archive/master-specification.md#12-principles-applied-as-engineering-decisions).

### 1.3 Low-friction safety policy

[Read the retained section](gym-core/docs/archive/master-specification.md#13-low-friction-safety-policy).

## 2. Wallex facts, economics and unresolved questions

[Read the retained section](gym-core/docs/archive/master-specification.md#2-wallex-facts-economics-and-unresolved-questions).

### 2.1 Documented interface - verify before real use

[Read the retained section](gym-core/docs/archive/master-specification.md#21-documented-interface---verify-before-real-use).

### 2.2 The economic constraint

[Read the retained section](gym-core/docs/archive/master-specification.md#22-the-economic-constraint).

### 2.3 Domestic FX is not crypto alpha

[Read the retained section](gym-core/docs/archive/master-specification.md#23-domestic-fx-is-not-crypto-alpha).

### 2.4 Probe order and evidence budget

[Read the retained section](gym-core/docs/archive/master-specification.md#24-probe-order-and-evidence-budget).

### 2.5 Regulatory, market-access and connectivity regime

[Read the retained section](gym-core/docs/archive/master-specification.md#25-regulatory-market-access-and-connectivity-regime).

### 2.6 Currency unit and redenomination

[Read the retained section](gym-core/docs/archive/master-specification.md#26-currency-unit-and-redenomination).

### 2.7 Economic baseline, the numéraire and the first funded workload

[Read the retained section](gym-core/docs/archive/master-specification.md#27-economic-baseline-the-numéraire-and-the-first-funded-workload).

### 2.8 Regulation as editable, versioned data (Settings → Venue rules)

[Read the retained section](gym-core/docs/archive/master-specification.md#28-regulation-as-editable-versioned-data-settings--venue-rules).

### 2.9 The venue's product surface: spot, trade credit, margin and instant trade

[Read the retained section](gym-core/docs/archive/master-specification.md#29-the-venues-product-surface-spot-trade-credit-margin-and-instant-trade).

#### 2.9.1 Trade credit

[Read the retained section](gym-core/docs/archive/master-specification.md#291-trade-credit).

#### 2.9.2 Margin, observed read-only

[Read the retained section](gym-core/docs/archive/master-specification.md#292-margin-observed-read-only).

#### 2.9.3 Instant trade, operator-initiated only

[Read the retained section](gym-core/docs/archive/master-specification.md#293-instant-trade-operator-initiated-only).

#### 2.9.4 External exposure (normative)

[Read the retained section](gym-core/docs/archive/master-specification.md#294-external-exposure-normative).

## 3. Architecture, trust boundaries and runtime

[Read the retained section](gym-core/docs/archive/master-specification.md#3-architecture-trust-boundaries-and-runtime).

### 3.1 Minimal deployable topology

[Read the retained section](gym-core/docs/archive/master-specification.md#31-minimal-deployable-topology).

### 3.2 Security boundary and authoritative reads

[Read the retained section](gym-core/docs/archive/master-specification.md#32-security-boundary-and-authoritative-reads).

### 3.3 Money and stop sequences

[Read the retained section](gym-core/docs/archive/master-specification.md#33-money-and-stop-sequences).

### 3.4 Ports and message contracts

[Read the retained section](gym-core/docs/archive/master-specification.md#34-ports-and-message-contracts).

### 3.5 Ownership, bounded work and minimal independent checking

[Read the retained section](gym-core/docs/archive/master-specification.md#35-ownership-bounded-work-and-minimal-independent-checking).

### 3.6 Generalized core types and flexibility mechanics

[Read the retained section](gym-core/docs/archive/master-specification.md#36-generalized-core-types-and-flexibility-mechanics).

### 3.7 Process topology and IPC catalog

[Read the retained section](gym-core/docs/archive/master-specification.md#37-process-topology-and-ipc-catalog).

### 3.8 Code structure, layering and concurrency

[Read the retained section](gym-core/docs/archive/master-specification.md#38-code-structure-layering-and-concurrency).

### 3.9 Optional execution relay (Cloudflare or a server the operator controls)

[Read the retained section](gym-core/docs/archive/master-specification.md#39-optional-execution-relay-cloudflare-or-a-server-the-operator-controls).

### 3.10 Optional private account stream

[Read the retained section](gym-core/docs/archive/master-specification.md#310-optional-private-account-stream).

## 4. Data collection, point-in-time semantics and research inputs

[Read the retained section](gym-core/docs/archive/master-specification.md#4-data-collection-point-in-time-semantics-and-research-inputs).

### 4.1 Raw observation, collection and quality

[Read the retained section](gym-core/docs/archive/master-specification.md#41-raw-observation-collection-and-quality).

### 4.2 Publication, clocks and the immutable snapshot

[Read the retained section](gym-core/docs/archive/master-specification.md#42-publication-clocks-and-the-immutable-snapshot).

### 4.3 Timeframes, consolidation and evaluation clocks

[Read the retained section](gym-core/docs/archive/master-specification.md#43-timeframes-consolidation-and-evaluation-clocks).

### 4.4 FX attribution, market microstructure and research factors

[Read the retained section](gym-core/docs/archive/master-specification.md#44-fx-attribution-market-microstructure-and-research-factors).

### 4.5 Storage, retention and reproducibility

[Read the retained section](gym-core/docs/archive/master-specification.md#45-storage-retention-and-reproducibility).

### 4.6 Reference feeds and proxy history

[Read the retained section](gym-core/docs/archive/master-specification.md#46-reference-feeds-and-proxy-history).

### 4.7 Multi-asset and multi-venue design

[Read the retained section](gym-core/docs/archive/master-specification.md#47-multi-asset-and-multi-venue-design).

## 5. Event records, money accounting and durable storage

[Read the retained section](gym-core/docs/archive/master-specification.md#5-event-records-money-accounting-and-durable-storage).

### 5.1 Stores and their authority

[Read the retained section](gym-core/docs/archive/master-specification.md#51-stores-and-their-authority).

### 5.2 Durable event envelope

[Read the retained section](gym-core/docs/archive/master-specification.md#52-durable-event-envelope).

#### The canonical Decision Record

[Read the retained section](gym-core/docs/archive/master-specification.md#the-canonical-decision-record).

### 5.3 Dual-asset, fee-aware accounting

[Read the retained section](gym-core/docs/archive/master-specification.md#53-dual-asset-fee-aware-accounting).

### 5.4 Reservations versus venue balances

[Read the retained section](gym-core/docs/archive/master-specification.md#54-reservations-versus-venue-balances).

### 5.5 Settlement-aware reconciliation

[Read the retained section](gym-core/docs/archive/master-specification.md#55-settlement-aware-reconciliation).

### 5.6 WAL, recovery and backups

[Read the retained section](gym-core/docs/archive/master-specification.md#56-wal-recovery-and-backups).

### 5.7 Minimal storage schemas and migrations

[Read the retained section](gym-core/docs/archive/master-specification.md#57-minimal-storage-schemas-and-migrations).

### 5.8 Data lifecycle, export and decommissioning

[Read the retained section](gym-core/docs/archive/master-specification.md#58-data-lifecycle-export-and-decommissioning).

## 6. Execution, risk, stops and order recovery

[Read the retained section](gym-core/docs/archive/master-specification.md#6-execution-risk-stops-and-order-recovery).

### 6.1 Independent permissions and modes

[Read the retained section](gym-core/docs/archive/master-specification.md#61-independent-permissions-and-modes).

### 6.2 Lifecycle and monotone state transitions

[Read the retained section](gym-core/docs/archive/master-specification.md#62-lifecycle-and-monotone-state-transitions).

### 6.3 Idempotency and identity recovery

[Read the retained section](gym-core/docs/archive/master-specification.md#63-idempotency-and-identity-recovery).

#### Evidence required to resolve an ambiguous order

[Read the retained section](gym-core/docs/archive/master-specification.md#evidence-required-to-resolve-an-ambiguous-order).

### 6.4 Entry policy: clear, adjustable, measurable

[Read the retained section](gym-core/docs/archive/master-specification.md#64-entry-policy-clear-adjustable-measurable).

### 6.5 Protective exits: not hostage to entry filters

[Read the retained section](gym-core/docs/archive/master-specification.md#65-protective-exits-not-hostage-to-entry-filters).

### 6.6 Reconciliation scope and manual trading

[Read the retained section](gym-core/docs/archive/master-specification.md#66-reconciliation-scope-and-manual-trading).

### 6.7 Request scheduling and execution capabilities

[Read the retained section](gym-core/docs/archive/master-specification.md#67-request-scheduling-and-execution-capabilities).

### 6.8 Execution quality, cost attribution and calibration

[Read the retained section](gym-core/docs/archive/master-specification.md#68-execution-quality-cost-attribution-and-calibration).

### 6.9 Emergency controls

[Read the retained section](gym-core/docs/archive/master-specification.md#69-emergency-controls).

### 6.10 Trade-credit risk controls

[Read the retained section](gym-core/docs/archive/master-specification.md#610-trade-credit-risk-controls).

## 7. Strategies, protection and optional intelligence

[Read the retained section](gym-core/docs/archive/master-specification.md#7-strategies-protection-and-optional-intelligence).

### 7.1 First funded strategy contract

[Read the retained section](gym-core/docs/archive/master-specification.md#71-first-funded-strategy-contract).

### 7.2 Signals, FX conditions and protection

[Read the retained section](gym-core/docs/archive/master-specification.md#72-signals-fx-conditions-and-protection).

### 7.3 User-friendly changes without erasing provenance

[Read the retained section](gym-core/docs/archive/master-specification.md#73-user-friendly-changes-without-erasing-provenance).

### 7.4 Progressive strategy composition

[Read the retained section](gym-core/docs/archive/master-specification.md#74-progressive-strategy-composition).

#### Strategy SDK, components and portfolio composition

[Read the retained section](gym-core/docs/archive/master-specification.md#strategy-sdk-components-and-portfolio-composition).

### 7.5 Observers, explainers and comparisons

[Read the retained section](gym-core/docs/archive/master-specification.md#75-observers-explainers-and-comparisons).

### 7.6 Model gateway - optional, off by default

[Read the retained section](gym-core/docs/archive/master-specification.md#76-model-gateway---optional-off-by-default).

#### Model and agent governance

[Read the retained section](gym-core/docs/archive/master-specification.md#model-and-agent-governance).

#### Advisory tools and automation

[Read the retained section](gym-core/docs/archive/master-specification.md#advisory-tools-and-automation).

### 7.7 Research evidence, specialist agents and memory

[Read the retained section](gym-core/docs/archive/master-specification.md#77-research-evidence-specialist-agents-and-memory).

### 7.8 Research tools, generated strategies and RL - later

[Read the retained section](gym-core/docs/archive/master-specification.md#78-research-tools-generated-strategies-and-rl---later).

## 8. Simulation, virtual accounts and the Research workspace

[Read the retained section](gym-core/docs/archive/master-specification.md#8-simulation-virtual-accounts-and-the-research-workspace).

### 8.1 Honest simulation and complete paper-session lifecycle

[Read the retained section](gym-core/docs/archive/master-specification.md#81-honest-simulation-and-complete-paper-session-lifecycle).

#### Simulated order/fill contract

[Read the retained section](gym-core/docs/archive/master-specification.md#simulated-orderfill-contract).

#### Paper-session state and readiness

[Read the retained section](gym-core/docs/archive/master-specification.md#paper-session-state-and-readiness).

### 8.2 Virtual accounts and baseline fairness

[Read the retained section](gym-core/docs/archive/master-specification.md#82-virtual-accounts-and-baseline-fairness).

### 8.3 Research objects without excess bureaucracy

[Read the retained section](gym-core/docs/archive/master-specification.md#83-research-objects-without-excess-bureaucracy).

### 8.4 Validation and diagnostic commands

[Read the retained section](gym-core/docs/archive/master-specification.md#84-validation-and-diagnostic-commands).

### 8.5 Research speed and the evidence boundary

[Read the retained section](gym-core/docs/archive/master-specification.md#85-research-speed-and-the-evidence-boundary).

### 8.6 What research reports must say

[Read the retained section](gym-core/docs/archive/master-specification.md#86-what-research-reports-must-say).

### 8.7 Strategy examples and experiments

[Read the retained section](gym-core/docs/archive/master-specification.md#87-strategy-examples-and-experiments).

### 8.8 Post-trade evidence loop

[Read the retained section](gym-core/docs/archive/master-specification.md#88-post-trade-evidence-loop).

### 8.9 Directional change (Workstream D)

[Read the retained section](gym-core/docs/archive/master-specification.md#89-directional-change-workstream-d).

### 8.10 Strategy zoo additions (Workstream D)

[Read the retained section](gym-core/docs/archive/master-specification.md#810-strategy-zoo-additions-workstream-d).

### 8.11 RL Environment Registry (Workstream E)

[Read the retained section](gym-core/docs/archive/master-specification.md#811-rl-environment-registry-workstream-e).

## 9. Validation and promotion - fast where risk is tiny, rigorous when scaling

[Read the retained section](gym-core/docs/archive/master-specification.md#9-validation-and-promotion---fast-where-risk-is-tiny-rigorous-when-scaling).

### 9.1 Distinguish three different questions

[Read the retained section](gym-core/docs/archive/master-specification.md#91-distinguish-three-different-questions).

### 9.2 Promotion stages and minimum evidence

[Read the retained section](gym-core/docs/archive/master-specification.md#92-promotion-stages-and-minimum-evidence).

### 9.3 What is hard versus advisory at promotion

[Read the retained section](gym-core/docs/archive/master-specification.md#93-what-is-hard-versus-advisory-at-promotion).

### 9.4 Quantitative validation when evidence matters

[Read the retained section](gym-core/docs/archive/master-specification.md#94-quantitative-validation-when-evidence-matters).

## 10. Windows security, reliability and everyday operations

[Read the retained section](gym-core/docs/archive/master-specification.md#10-windows-security-reliability-and-everyday-operations).

### 10.1 Security proportional to the threat

[Read the retained section](gym-core/docs/archive/master-specification.md#101-security-proportional-to-the-threat).

### 10.2 Dependency and external-code policy

[Read the retained section](gym-core/docs/archive/master-specification.md#102-dependency-and-external-code-policy).

### 10.3 Operational safety that does not demand babysitting

[Read the retained section](gym-core/docs/archive/master-specification.md#103-operational-safety-that-does-not-demand-babysitting).

### 10.4 Useful response to failures

[Read the retained section](gym-core/docs/archive/master-specification.md#104-useful-response-to-failures).

### 10.5 Threat model summary

[Read the retained section](gym-core/docs/archive/master-specification.md#105-threat-model-summary).

### 10.6 Releases, updates and supply-chain integrity

[Read the retained section](gym-core/docs/archive/master-specification.md#106-releases-updates-and-supply-chain-integrity).

## 11. Interface and interaction design

[Read the retained section](gym-core/docs/archive/master-specification.md#11-interface-and-interaction-design).

### 11.1 Simple information architecture

[Read the retained section](gym-core/docs/archive/master-specification.md#111-simple-information-architecture).

### 11.2 Operate - answer six questions instantly

[Read the retained section](gym-core/docs/archive/master-specification.md#112-operate---answer-six-questions-instantly).

### 11.3 Markets and Research

[Read the retained section](gym-core/docs/archive/master-specification.md#113-markets-and-research).

### 11.4 Journal and forensic replay

[Read the retained section](gym-core/docs/archive/master-specification.md#114-journal-and-forensic-replay).

### 11.5 The most useful visuals, introduced progressively

[Read the retained section](gym-core/docs/archive/master-specification.md#115-the-most-useful-visuals-introduced-progressively).

#### Widget catalog (dockable, fed only from projections)

[Read the retained section](gym-core/docs/archive/master-specification.md#widget-catalog-dockable-fed-only-from-projections).

### 11.6 English/Persian, amounts and accessible controls

[Read the retained section](gym-core/docs/archive/master-specification.md#116-englishpersian-amounts-and-accessible-controls).

### 11.7 User effort budget

[Read the retained section](gym-core/docs/archive/master-specification.md#117-user-effort-budget).

### 11.8 Screen inventory

[Read the retained section](gym-core/docs/archive/master-specification.md#118-screen-inventory).

### 11.9 Settings information architecture

[Read the retained section](gym-core/docs/archive/master-specification.md#119-settings-information-architecture).

### 11.10 Design system

[Read the retained section](gym-core/docs/archive/master-specification.md#1110-design-system).

### 11.11 End-to-end journeys

[Read the retained section](gym-core/docs/archive/master-specification.md#1111-end-to-end-journeys).

### 11.12 Keyboard and command palette

[Read the retained section](gym-core/docs/archive/master-specification.md#1112-keyboard-and-command-palette).

### 11.13 Onboarding and demo mode

[Read the retained section](gym-core/docs/archive/master-specification.md#1113-onboarding-and-demo-mode).

## 12. Observability, diagnostics and incident workflow

[Read the retained section](gym-core/docs/archive/master-specification.md#12-observability-diagnostics-and-incident-workflow).

### 12.1 Actionable, local-first telemetry

[Read the retained section](gym-core/docs/archive/master-specification.md#121-actionable-local-first-telemetry).

### 12.2 Incident procedure, not a workflow ceremony

[Read the retained section](gym-core/docs/archive/master-specification.md#122-incident-procedure-not-a-workflow-ceremony).

### 12.3 Notification matrix

[Read the retained section](gym-core/docs/archive/master-specification.md#123-notification-matrix).

### 12.4 Local service objectives

[Read the retained section](gym-core/docs/archive/master-specification.md#124-local-service-objectives).

### 12.5 Reports and digests

[Read the retained section](gym-core/docs/archive/master-specification.md#125-reports-and-digests).

## 13. Contracts, API and technical conventions

[Read the retained section](gym-core/docs/archive/master-specification.md#13-contracts-api-and-technical-conventions).

### 13.1 Minimal contract inventory

[Read the retained section](gym-core/docs/archive/master-specification.md#131-minimal-contract-inventory).

### 13.2 Numerical, time and event rules

[Read the retained section](gym-core/docs/archive/master-specification.md#132-numerical-time-and-event-rules).

### 13.3 Local API and emergency path

[Read the retained section](gym-core/docs/archive/master-specification.md#133-local-api-and-emergency-path).

### 13.4 Folder/build conventions

[Read the retained section](gym-core/docs/archive/master-specification.md#134-folderbuild-conventions).

### 13.5 `gymctl` command reference

[Read the retained section](gym-core/docs/archive/master-specification.md#135-gymctl-command-reference).

### 13.6 Configuration layering

[Read the retained section](gym-core/docs/archive/master-specification.md#136-configuration-layering).

## 14. Tests, acceptance evidence and release quality

[Read the retained section](gym-core/docs/archive/master-specification.md#14-tests-acceptance-evidence-and-release-quality).

### 14.1 Test philosophy

[Read the retained section](gym-core/docs/archive/master-specification.md#141-test-philosophy).

### 14.2 Core acceptance matrix

[Read the retained section](gym-core/docs/archive/master-specification.md#142-core-acceptance-matrix).

### 14.3 Bounded fake venue scenario example

[Read the retained section](gym-core/docs/archive/master-specification.md#143-bounded-fake-venue-scenario-example).

#### Regression fixtures and acceptance mapping

[Read the retained section](gym-core/docs/archive/master-specification.md#regression-fixtures-and-acceptance-mapping).

### 14.4 UI and docs verification without unnecessary process

[Read the retained section](gym-core/docs/archive/master-specification.md#144-ui-and-docs-verification-without-unnecessary-process).

### 14.5 Test pyramid and CI pipeline

[Read the retained section](gym-core/docs/archive/master-specification.md#145-test-pyramid-and-ci-pipeline).

### 14.6 Resource and performance budgets

[Read the retained section](gym-core/docs/archive/master-specification.md#146-resource-and-performance-budgets).

## 15. Implementation sequence and usable release gates

[Read the retained section](gym-core/docs/archive/master-specification.md#15-implementation-sequence-and-usable-release-gates).

### 15.1 Five workstreams; no calendar promises

[Read the retained section](gym-core/docs/archive/master-specification.md#151-five-workstreams-no-calendar-promises).

#### 15.1.1 Expansion backlog (Workstreams D and E)

[Read the retained section](gym-core/docs/archive/master-specification.md#1511-expansion-backlog-workstreams-d-and-e).

### 15.2 Daily operator work after launch

[Read the retained section](gym-core/docs/archive/master-specification.md#152-daily-operator-work-after-launch).

### 15.3 Definition of a finished release

[Read the retained section](gym-core/docs/archive/master-specification.md#153-definition-of-a-finished-release).

### 15.4 Work breakdown by workstream

[Read the retained section](gym-core/docs/archive/master-specification.md#154-work-breakdown-by-workstream).

### 15.5 Delivery risk register

[Read the retained section](gym-core/docs/archive/master-specification.md#155-delivery-risk-register).

### 15.6 Decision record

[Read the retained section](gym-core/docs/archive/master-specification.md#156-decision-record).

### 15.7 Open decisions for the operator (with defaults)

[Read the retained section](gym-core/docs/archive/master-specification.md#157-open-decisions-for-the-operator-with-defaults).

## 16. Scope decisions, extension triggers and exclusions

[Read the retained section](gym-core/docs/archive/master-specification.md#16-scope-decisions-extension-triggers-and-exclusions).

### 16.1 Included in the dependable core

[Read the retained section](gym-core/docs/archive/master-specification.md#161-included-in-the-dependable-core).

### 16.2 Useful future capabilities - explicit contracts, conditional delivery

[Read the retained section](gym-core/docs/archive/master-specification.md#162-useful-future-capabilities---explicit-contracts-conditional-delivery).

### 16.3 Deliberately excluded or not used as blanket rules

[Read the retained section](gym-core/docs/archive/master-specification.md#163-deliberately-excluded-or-not-used-as-blanket-rules).

## 17. Venue facts, open questions and the decisions they affect

[Read the retained section](gym-core/docs/archive/master-specification.md#17-venue-facts-open-questions-and-the-decisions-they-affect).

### A.1 Buy/sell cost and break-even

[Read the retained section](gym-core/docs/archive/master-specification.md#a1-buysell-cost-and-break-even).

### A.2 Exposure, capital, cost and FX

[Read the retained section](gym-core/docs/archive/master-specification.md#a2-exposure-capital-cost-and-fx).

### A.3 Example of a straightforward session

[Read the retained section](gym-core/docs/archive/master-specification.md#a3-example-of-a-straightforward-session).

## Appendix B. Glossary and product language

[Read the retained section](gym-core/docs/archive/master-specification.md#appendix-b-glossary-and-product-language).

## Appendix E. External sources

[Read the retained section](gym-core/docs/archive/master-specification.md#appendix-e-external-sources).
