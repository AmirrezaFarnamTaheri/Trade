# Operator workspace

Status: implemented unified direction, 2026-11-02. The user chose comp-first, then supplied several explicit screen references and delegated their proper unification. That later instruction resolves the earlier composition-selection question; no new approval round is pending.

## Surface and purpose

TradingGYM is an operator workspace for an autonomous trading agent. The current application supports observation, paper research, local journals, offline previews, rules, and bounded diagnostics. Funded execution and Autopilot remain unavailable. This surface makes the available work and the execution boundary legible together.

The working app uses the existing Python/aiohttp loopback server and native HTML, CSS, and JavaScript. It introduces no UI framework or remote trading authority. Shared visual tokens and component behavior are recorded in [DESIGN.md](../../DESIGN.md); the v2 sidecar adds component previews, theme metadata, motion, and breakpoints.

## Composition authority

Unify the references through warm cream working surfaces, a charcoal sidebar, copper selected navigation and controls, ruled comparisons, restrained panels, and an equivalent dark theme. The Overview brings mission context, observed markets, paper evidence, safety, and recent records into one workspace. Detailed destinations reuse that shell and component vocabulary.

Reference assets:

- `.impeccable/mocks/mission-sequence.png`: early mission-context composition.
- `.impeccable/mocks/market-register.png`: early market-comparison composition.
- User-supplied warm Overview reference: `C:/Users/ACER/AppData/Local/Temp/codex-clipboard-0e3fa128-13ca-4759-9aea-42c62ef72a2e.png` (temporary source location; not a portable application asset).

Images are conceptual composition references. Their sample values, readiness, accounts, diagnostics, backup inventories, and implied execution controls are not application data or authority. The implementation takes its facts from existing APIs and stores. No reference image is loaded into the working UI.

## Destinations and action boundaries

| Destination | Route | Actual behavior |
| --- | --- | --- |
| Overview | `#overview` | Default workspace: mission shortcuts, observed market counts, market watch, saved paper evidence, disarmed safety, and known limits. |
| Markets | `#markets` | Pair/asset search, quote filter, exact bid/ask/spread values, quote quality, and expandable entry/exit rule provenance. |
| Paper research | `#research` | Latest 50 saved runs; selected equity, costs, baselines, rank/abstainer distinction, limitations, and latest 100 decision disclosures. |
| Account journal | `#account` | Private read-only account observations, unverified external orders, and recorded offline reviews. No balance is spendable executor cash. |
| Offline ticket | `#operate` | Structured form and JSON editor for one bounded dry-run request; synthetic example is explicitly labelled. Preview costs never submits an order. Editing invalidates the previous preview. |
| Venue rules | `#rules` | Existing preset, import, disable, and JSON export workflows; rule provenance, history, and quarantine remain inspectable. |
| System health | `#health` | Collector connection/frame age/events, quality observations, configured venue capability evidence, and saved simulated venue checks. Missing reports remain unavailable or not run. |
| Safety | `#safety` | Current disarmed response and missing executor attestation, venue-stop certification, and funded authority. |
| Backups | `#backups` | Existing protected-console backup/restore instructions. Web status is not connected; no inventory, last-success, integrity badge, or browser passphrase form is fabricated. |

The current mutation boundary is local rule management and offline preview submission. Existing private reads and mutations require the per-run token. No screen can arm trading, place/cancel/sign a venue order, activate Autopilot, certify stops, or authorize capital. Public market eligibility, simulation results, and paper evidence do not change that boundary.

## Fidelity and state contract

- Preserve source decimal strings, including trailing precision. Chart geometry may use floating point; exact textual values may not.
- Keep synthetic demo data labelled and isolated from live stores.
- Show source time in Tehran and retain provenance and full source disclosures.
- Keep loading, empty, unavailable, unknown, unverified, error, and stale states distinct. Private account errors clear previously displayed balances.
- Never replace missing observability with invented CPU/memory, model-health, predictive signals, execution readiness, account totals, or backup records.
- System health is bounded by actual collector, venue-evidence, and saved simulation endpoints. Independent provider qualification, funded execution, protective stops, backup inventory, and restore attestation are unsupported by this web surface.

## Responsive and inclusive behavior

Use the implemented 1180px, 900px, and 600px breakpoints: narrow the desktop rail, convert it to a top navigation row, then stack dense detail layouts. Wide data tables scroll within their own focusable region. English/Persian switching mirrors logical layout while isolating money, identifiers, JSON, commands, and charts left-to-right. Light/dark and language choices persist locally when storage is available. Keep keyboard access, the skip link, visible focus, status announcements, and reduced-motion handling.

## Review focus

Verify all nine destinations with actual empty and populated local stores, light/dark themes, English/Persian direction, narrow and wide screens, keyboard navigation, stale/error responses, and invalid ticket/rule input. Verify that the sidebar/topbar and any successful preview still state the execution boundary. Screenshots and builds are UI evidence, not funded-venue or provider qualification.
