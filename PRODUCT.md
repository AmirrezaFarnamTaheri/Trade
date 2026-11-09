# TradingGYM

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

An individual researcher monitoring Wallex markets and reviewing paper results. The product goal is an autonomous trading agent.

## Product Purpose

An operator workspace for an autonomous trading agent: understand the market, inspect research evidence, and see exactly which capabilities are available or blocked.

## Operating Context

The current Python/aiohttp application runs on loopback and serves a dependency-free HTML/CSS/JavaScript interface. Public market observations, saved paper runs, local account observations, venue rules, offline ticket previews, and system diagnostics are existing workflows.

## Capabilities and Constraints

- The current application is DISARMED. It has no funded order-submission path or enabled Autopilot. Autonomous trading is the product goal, not an available capability to invent in this redesign.
- Private local reads and mutations use the per-run token. Do not expose credentials or echo ticket input into errors.
- Monetary values arrive as exact decimal strings. Calculate with exact decimals; rounded summaries retain exact inspection and export.
- Account observations and external orders are unverified, and do not establish spendable balances or settlement.
- Demo observations are synthetic and must remain labelled. Paper results cannot authorize real capital.
- Existing rule import, preset, disable, and export operations remain available.
- Excluded strategy families: grid, martingale and averaging-down. They add exposure as a position loses, so a
  small or negative edge becomes a tail loss, and closed-bar paper fills cannot show the gap and liquidity risk that
  decides their outcome. Do not re-explore them without a written reason that addresses this.

## Brand Commitments

Use the TradingGYM name and the visual, language and accessibility contracts in DESIGN.md.

## Evidence on Hand

Source contracts in gym-core/src/gym/api/server.py and domain/services modules; existing local demo/live stores; deterministic tests under gym-core/tests. There are no customer claims, testimonials, or qualified live-trading results to add.

## Product Principles

- Put actual agent readiness and restrictions within view.
- Make market and research evidence understandable before action.
- Preserve the distinction between observation, simulation, and execution authority.
- Keep the working stack and local-data isolation.

## Accessibility & Inclusion

Preserve English/Persian and correct RTL layout, keyboard access, visible focus, responsive screens, and light/dark preferences.

## Current delivery contract

The current [implementation plan](gym-core/docs/implementation-plan.md),
[system status](gym-core/docs/system-status.md) and
[acceptance gates](gym-core/docs/acceptance-status.md) own delivery state.
- Observe the eligible public market universe and expose selection, exclusions,
  per-market freshness, missing periods and receipt-time knowledge separately.
- Keep exact SQL observations and raw archives, immutable run identities, failed
  attempts, revisions and source attribution.
- Share the native engine across historical replay, prospective paper sessions,
  matched comparisons and shared-cash portfolios, with disclosed costs and gaps.
- Distinguish chronological selection, exploratory diagnostics, future evaluation
  and independent custody. No statistical label establishes a profitable edge.
- Expose provider connections, advisory research and evidence-linked notes through
  explicit bounded workflows. Models have no order authority or silent paid calls.
- Keep spot long/flat, margin credit ratios, debt, FX units and settlement as
  separate contracts. New paper mechanisms do not qualify funded equivalents.
- Preserve separate Windows principals, custody, exact operator intent, durable
  uncertain outcomes and emergency stop for the protected execution boundary.
- Enforce the existing zero funded-loss budget until a separate funded probe is
  explicitly authorized. Physical-host and elapsed-time evidence remain actual
  acceptance requirements; neither can be replaced by simulated success.

Predictive ML/RL training remains outside the accepted delivery scope. Current
rule-based and statistical work remains visible in the plan. Unrelated runtimes
do not expand authority.
