# Architecture Specifications

Design specs, adversarial reviews, and structural audits for TradingGYM's research and execution layers. For binding authority and custody decisions, see [../adr/README.md](../adr/README.md).

| Document | Scope |
| --- | --- |
| [Cross-layer trading design decisions](cross-layer-trading-design-decisions.md) | Ambiguous fills, competing capital, time to research decisions and further product, modeling and operational experiments |
| [Post-repair and experiment review](2026-11-26-post-repair-and-experiment-review.md) | Results through `113528c`, independent treasury and gold counterexamples, disposition of all 15 experiments, and next engineering priorities |
| [42-commit implementation review](2026-11-25-last-42-commits-review.md) | Verified replay, accounting and journal defects through `97dd9c8`, research conclusions, bottlenecks and refactor sequence |
| [codebase-structure-review.md](codebase-structure-review.md) | Static dependency, pure-domain boundary, and package-layout audit of `gym-core` |
| [ensemble-gateway-design.md](ensemble-gateway-design.md) | Uncorrelated multi-timeframe ensemble (`1d` Slow Core + `2h` Ignition) & calibrated ML meta-gateway spec |
| [ensemble-gateway-design-review.md](ensemble-gateway-design-review.md) | Adversarial review of ensemble gateway design & financial-engine bottlenecks |
| [ensemble-gateway-repair-plan.md](ensemble-gateway-repair-plan.md) | Engine repair plan and first shared-ledger paper verification blueprint |
| [dynamic-instrument-resolver-design.md](dynamic-instrument-resolver-design.md) | v3 per-moment Spot / Isolated Margin / Perp / Leverage / Short resolver architecture & 4-way evaluation spec |
