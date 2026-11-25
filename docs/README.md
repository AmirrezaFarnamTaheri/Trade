# TradingGYM Documentation Index

Top-level governance, architecture decisions, and system specifications. For `gym-core` application, research contract, and runbook documentation, see [gym-core/docs/README.md](../gym-core/docs/README.md). For quantitative study reports and live forward tracking, see [evidence/README.md](../evidence/README.md) and [evidence/studies/SUMMARY.md](../evidence/studies/SUMMARY.md).

## Governance, Safety & Checkpoints

| Document | Role |
| --- | --- |
| [2027-02-08-checkpoint-protocol.md](2027-02-08-checkpoint-protocol.md) | Frozen funded-path stop/go gate (`G1–G4`) and decision ownership matrix *(path pinned by contract tests)* |
| [arming-policy.md](arming-policy.md) | Owner arming policy schema, limits, and fail-closed custody preconditions *(path referenced by CLI & preflight)* |
| [operator-rebinding.md](operator-rebinding.md) | Elevated operator account and custody rebinding procedure |
| [review-coverage.md](review-coverage.md) | Audit review coverage matrix across Python, Rust, and host boundaries |
| [review-disposition.md](review-disposition.md) | Master disposition tracker for integrated audit findings |
| [onboarding.md](onboarding.md) | Developer environment setup, safety boundaries, and evidence conventions |

## Roadmaps & Architecture

| Document | Role |
| --- | --- |
| [profitable-system-plan.md](profitable-system-plan.md) | Master engineering & quant specification (Wallex-core financial engine, multi-signal framework, multi-venue plug-ins) |
| [whole-market-research-plan.md](whole-market-research-plan.md) | Whole-market coverage, residual-inventory, and liquidity research framework |
| [adr/README.md](adr/README.md) | Architecture Decision Records (`ADR 0001`–`ADR 0008`) governing authority split, fail-closed custody, and executor contracts |
| [architecture/codebase-structure-review.md](architecture/codebase-structure-review.md) | Static dependency, module boundary, and package-layout review of `gym-core` |
| [architecture/ensemble-gateway-design.md](architecture/ensemble-gateway-design.md) | Uncorrelated multi-timeframe ensemble & calibrated ML meta-gateway specification |
| [architecture/ensemble-gateway-design-review.md](architecture/ensemble-gateway-design-review.md) | Adversarial design review of the ensemble gateway & financial-engine bottlenecks |
| [architecture/ensemble-gateway-repair-plan.md](architecture/ensemble-gateway-repair-plan.md) | Engine repair and first paper experiment implementation plan |
| [venues/README.md](venues/README.md) | Canonical Nobitex OpenAPI YAML & Wallex Swagger JSON specs, WebSocket v2 channels, and execution guardrails |

## Runtime & Evidence Docs

- [gym-core/docs/README.md](../gym-core/docs/README.md) — Capabilities, trial log, roadmap, storage, metrics, and operational runbooks
- [executor/README.md](../executor/README.md) — Rust protected executor (`DISARMED / NOT CERTIFIED`)
- [evidence/README.md](../evidence/README.md) — Organized quantitative studies, forward journals, interactive dashboard, and archive
