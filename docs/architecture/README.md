# Architecture Specifications

Design specs, adversarial reviews, and structural audits for TradingGYM's research and execution layers. For binding authority and custody decisions, see [../adr/README.md](../adr/README.md).

| Document | Scope |
| --- | --- |
| [codebase-structure-review.md](codebase-structure-review.md) | Static dependency, pure-domain boundary, and package-layout audit of `gym-core` |
| [ensemble-gateway-design.md](ensemble-gateway-design.md) | Uncorrelated multi-timeframe ensemble (`1d` Slow Core + `2h` Ignition) & calibrated ML meta-gateway spec |
| [ensemble-gateway-design-review.md](ensemble-gateway-design-review.md) | Adversarial review of ensemble gateway design & financial-engine bottlenecks |
| [ensemble-gateway-repair-plan.md](ensemble-gateway-repair-plan.md) | Engine repair plan and first shared-ledger paper verification blueprint |
| [dynamic-instrument-resolver-design.md](dynamic-instrument-resolver-design.md) | v3 per-moment Spot / Isolated Margin / Perp / Leverage / Short resolver architecture & 4-way evaluation spec |
