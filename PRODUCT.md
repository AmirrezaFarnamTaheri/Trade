# TradingGYM

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

An individual researcher monitoring Wallex markets and reviewing paper results. Confirmed by the user on 2026-11-02, with the clarification that the main product goal is an autonomous trading agent.

## Product Purpose

An operator workspace for an autonomous trading agent: understand the market, inspect research evidence, and see exactly which capabilities are available or blocked.

## Operating Context

The current Python/aiohttp application runs on loopback and serves a dependency-free HTML/CSS/JavaScript interface. Public market observations, saved paper runs, local account observations, venue rules, offline ticket previews, and system diagnostics are existing workflows.

## Capabilities and Constraints

- The current application is DISARMED. It has no funded order-submission path or enabled Autopilot. Autonomous trading is the product goal, not an available capability to invent in this redesign.
- Private local reads and mutations use the per-run token. Do not expose credentials or echo ticket input into errors.
- Monetary values arrive as exact decimal strings. Display them without floating-point rounding.
- Account observations and external orders are unverified, and do not establish spendable balances or settlement.
- Demo observations are synthetic and must remain labelled. Paper results cannot authorize real capital.
- Existing rule import, preset, disable, and export operations remain available.

## Brand Commitments

Preserve the TradingGYM name. The user requested a complete redesign and invoked Impeccable, Redesign Existing Projects, and GPT Taste. User chose comp-first for this redesign.

## Evidence on Hand

Source contracts in gym-core/src/gym/api/server.py and domain/services modules; existing local demo/live stores; deterministic tests under gym-core/tests. There are no customer claims, testimonials, or qualified live-trading results to add.

## Product Principles

- Put actual agent readiness and restrictions within view.
- Make market and research evidence understandable before action.
- Preserve the distinction between observation, simulation, and execution authority.
- Keep the working stack and local-data isolation.

## Accessibility & Inclusion

Preserve English/Persian and correct RTL layout, keyboard access, visible focus, responsive screens, and light/dark preferences.
