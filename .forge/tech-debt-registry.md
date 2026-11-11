# Trade technical debt registry

Updated: 2026-11-11. Findings and reproductions: [audit](../docs/audit-2026-11-11.md).
Estimates are planning estimates, not measured delivery times. Owners require maintainer assignment.

| ID | Location | Type | Owner | Estimated fix cost | Cost of deferral | Trigger | Acceptance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEBT-001 | `model-gateway/control.mjs:27`, `gym-core/src/gym/ui/models.js:16` | Incorrect protection status | Unassigned maintainer | Half day | Operator sees misleading credential-protection state | Before next provider-settings release | Distinguish sealed, explicit plaintext, unavailable and legacy-plaintext state; use synthetic credentials |
| DEBT-002 | `gym-core/src/gym/ui/models.js:49` | UI state loss | Unassigned maintainer | Half day | Paid response and draft lost on language toggle | Before next AI-connections change | EN/FA toggle retains nonsecret prompt/response, clears credential inputs, sends no additional paid request |
| DEBT-003 | `gym-core/src/gym/ui/portfolio.js:8`, `margin.js:8` | Inconsistent timezone rendering | Unassigned maintainer | One day | Saved portfolio/margin results retain old display zone | Before next portfolio/margin UI change | Zone-only toggle updates visible times, keeps ISO instants and inputs, issues no new replay |
| DEBT-004 | `gym-core/src/gym/ui/styles.css:127`, `:138`, `:330` | Mobile accessibility gap | Unassigned maintainer | Half day plus browser verification | Some touch targets may remain below the requested minimum | Before mobile UI acceptance | Computed action/tab targets >=44px at 375px/600px, both languages/themes, no overflow |

No speculative rewrite, dependency removal or dead-code deletion is scheduled. The reviewed Python/Rust/Node seams have actual cross-process, cross-language or authorization responsibilities.

## Current refresh

See the [current audit](../docs/audit-2026-11-11.md) for skill execution, research findings and rendered interface evidence.

- DEBT-001 is repaired in the current working tree; storage-mode and legacy-warning regressions pass.
- DEBT-002 remains reproduced in two Node regressions and the actual DEMO browser.
- DEBT-003 remains source-confirmed; do not change ISO instants or repeat research to fix presentation.
- DEBT-004 is partly repaired. Ordinary actions/tabs meet the source floor, but actual `.symbol-button` market controls remain about 38.65px high at 375px in both languages/themes. Retain browser geometry in acceptance.
- DEBT-005: allocation preview ignores known venue precision/minimum notional. Owner: unassigned maintainer. Trigger: before treating allocations as venue-feasible paper fills. Acceptance: enforce known specifications or block explicitly, retaining decimal strings and nonfunded status.
- DEBT-006: duplicate allocation symbols append the same market/day twice. Owner: unassigned maintainer. Trigger: before scheduled repeated allocation use. Acceptance: deduplicate or reject duplicate symbols before writing; prove one daily record per requested market.
- DEBT-007: zero/negative allocation lookback is not validated. Owner: unassigned maintainer. Trigger: before accepting untrusted allocation inputs. Acceptance: reject nonpositive windows at the shared boundary without division failure or READY output.

The new stale prospective-comparison defect is repaired with shared valuation; its related 52-test set and independent change review pass. These facts do not close the remaining debt above.
