---
name: TradingGYM operator workspace
description: A calm, evidence-led workspace for an autonomous trading agent, currently disarmed.
colors:
  page: "#f6f4ef"
  surface: "#fffefa"
  surface-raised: "#eeece5"
  border: "#dcd9d0"
  text: "#282924"
  text-muted: "#686a60"
  accent: "#9b4d25"
  accent-text: "#fffaf3"
  accent-soft: "#f4e6d7"
  positive: "#287044"
  positive-soft: "#e7f1e5"
  negative: "#b52d2d"
  negative-soft: "#fbe9e5"
  caution: "#855508"
  caution-soft: "#fff1d6"
  neutral-soft: "#eae9e2"
  chart-blue: "#2f6f8f"
  chart-olive: "#596b21"
  chart-purple: "#8a4f9e"
  sidebar: "#292824"
  sidebar-text: "#eeede6"
  sidebar-muted: "#b9b7ad"
  sidebar-selected: "#754723"
  nav-selected-text: "#fff6e7"
  brand-copper: "#d69b6d"
  dark-page: "#171c20"
  dark-surface: "#20272d"
  dark-surface-raised: "#29323a"
  dark-border: "#3b454d"
  dark-text: "#eceee9"
  dark-text-muted: "#b0b9bc"
  dark-accent: "#e7ac7a"
  dark-accent-text: "#231e18"
  dark-accent-soft: "#3e3025"
  dark-positive: "#8acf9f"
  dark-positive-soft: "#263c30"
  dark-negative: "#ffaaa0"
  dark-negative-soft: "#462d2d"
  dark-caution: "#e8bf76"
  dark-caution-soft: "#3d3425"
  dark-neutral-soft: "#303a40"
  dark-chart-blue: "#79bddf"
  dark-chart-olive: "#b9cb73"
  dark-chart-purple: "#d3a2e6"
  dark-sidebar: "#12171b"
  dark-sidebar-text: "#eeede6"
  dark-sidebar-muted: "#aeb7bb"
  dark-sidebar-selected: "#59412c"
typography:
  display:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  headline:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "19px"
    fontWeight: 650
    lineHeight: 1.55
    letterSpacing: "-0.015em"
  title:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "16px"
    fontWeight: 650
    lineHeight: 1.55
  body:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.55
  control:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "12px"
    fontWeight: 550
    lineHeight: 1.55
  metric:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "25px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.02em"
  mono:
    fontFamily: '"Cascadia Code", Consolas, monospace'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.55
  chip:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.7
  metadata:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.55
  subheading:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.55
  nested-heading:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.55
  brand:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "21px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.7px"
  brand-compact:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "18px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.7px"
  brand-mobile:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "20px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.7px"
  fx-metric:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "23px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.02em"
  chart:
    fontFamily: '"Segoe UI", sans-serif'
    fontSize: "17px"
    fontWeight: 400
  waterfall:
    fontFamily: '"Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 400
rounded:
  track: "2px"
  badge: "4px"
  control: "5px"
  navigation: "6px"
  banner: "7px"
  panel: "10px"
  round: "50%"
spacing:
  tight: "5px"
  control-gap: "10px"
  row: "12px"
  group: "14px"
  section: "20px"
  panel: "21px"
  view: "22px"
  workspace-inline: "30px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-text}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  nav-selected:
    backgroundColor: "{colors.sidebar-selected}"
    textColor: "{colors.nav-selected-text}"
    rounded: "{rounded.navigation}"
    padding: "11px 13px"
  chip-neutral:
    backgroundColor: "{colors.neutral-soft}"
    textColor: "{colors.text-muted}"
    typography: "{typography.chip}"
    rounded: "{rounded.badge}"
    padding: "2px 7px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "21px"
---

# Design System: TradingGYM

## Overview

**Creative North Star: "The operator's research register"**

TradingGYM is a calm working environment for observing an autonomous agent's inputs, reviewing paper evidence, and preparing bounded offline previews. Warm cream surfaces, a charcoal navigation rail, copper selection, and ruled data bring the supplied interface references into one practical workspace.

The interface is compact enough to compare financial records, with generous separation between independent tasks. Capability statements remain visible beside the evidence they qualify. The current application is disarmed; the visual system must never imply that a successful observation, paper run, or preview grants funded authority.

**Key Characteristics:**
- Warm, quiet working surfaces with one copper action and selection accent.
- Precise tabular values, inline provenance, and plain capability language.
- Persistent context with ten clear destinations and an equivalent dark theme.
- English and Persian layouts, keyboard access, and restrained feedback motion.

## Colors

The palette combines warm neutral materials with copper controls and separate semantic state colors. Frontmatter records the implemented light and dark values; dark-prefixed tokens replace the corresponding CSS custom properties when the dark theme is selected.

Equity curves use neutral copper. Comparison series use theme-specific chart
colors and distinct dash patterns; hue alone must not identify a series.
Unknown feed readiness uses caution rather than a positive indicator.
Replay axes use HTML labels so they retain their text size as the graph narrows.
Phone forms use one column, frequent compact actions have a 44px minimum height,
and chart/waterfall labels retain the 11px floor. Rendered contrast, reflow and
touch behavior still require current-build browser verification.

### Primary

- **Copper** (`accent`, `accent-text`, `accent-soft`): primary actions, selected filters, links, expanded market context, and the FX context panel.
- **Rail copper** (`sidebar-selected`, `nav-selected-text`, `brand-copper`): selected navigation and the existing brand mark on charcoal.

### Neutral

- **Warm paper** (`page`, `surface`, `surface-raised`): the page, independent work panels, and table headers or grouped controls.
- **Ink and pencil** (`text`, `text-muted`): primary reading and secondary context. Muted text still carries essential information and must remain legible.
- **Ruled edge** (`border`, `neutral-soft`): separators and neutral states; unknown data uses explicit wording.
- **Charcoal rail** (`sidebar`, `sidebar-text`, `sidebar-muted`): navigation, local controls, and the persistent disarmed reminder.

Positive, negative, and caution tokens each have a matching soft background. Use them for the reported state of a particular observation or check, with a text label; they are not alternate brand accents.

**The Evidence Rule.** A green quote, eligible rule verdict, or passed simulation describes only that evidence. It never makes the agent ready to trade. Missing, stale, unavailable, and unverified states must stay explicit.

## Typography

**Display and Body Font:** Segoe UI Variable Text, then Segoe UI, Tahoma, and the platform sans-serif.
**Label/Mono Font:** the same sans-serif for controls; Cascadia Code or Consolas for source records, identifiers, and console commands.

The single humanist family supports long records and Persian fallback without a downloaded font dependency. Hierarchy comes from size, weight, spacing, and numeric alignment rather than decorative display type. Frontmatter owns the exact roles.

- **Display:** the page heading; reduces to (25px) below the mobile breakpoint.
- **Headline:** section headings; reduces to (17px) below the mobile breakpoint.
- **Title:** panel headings. Smaller nested headings use (15px) and (13px).
- **Body:** primary reading. Leads have a maximum width of (72ch).
- **Label and control:** field labels, buttons, and table data. Help text uses (12px); functional metadata and compact states have an (11px) floor.
- **Metric:** summary values; research metrics use (19px), and mobile summary values use (21px).
- **Chart:** equity axes use (17px) and waterfall labels use (16px) in the fixed SVG viewBox; exact values remain available as text outside chart geometry.
- **Mono:** JSON disclosures and commands retain left-to-right reading even in Persian.

The literal font-size ramp is (11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 25, 30px). This includes the brand's responsive sizes, FX values, and compact headings rather than only the primary page roles. Body text remains (14px).

**The Exact Value Rule.** Calculations and submitted amounts preserve the API's decimal strings. A rounded summary must retain exact values in inspection or export. Use tabular figures and bidirectional isolation; floating-point conversion belongs only to chart geometry.

## Layout

The desktop shell uses a sticky charcoal rail (214px) beside a fluid workspace. The top context bar keeps the current destination, disarmed state, feed status, and Tehran time in view. Main content is centered with a maximum width of (1660px), desktop inline padding of (30px), and a footer that repeats the local-data boundary.

Panels use the recorded panel padding and restrained section gaps. Tables carry comparisons; paired panels group distinct tasks. The overview combines a mission sequence, four summary cells, market and research context, then safety, recent evidence, and known constraints. Paper research uses a saved-run rail (228px) beside the selected record. Offline tickets use a larger editor beside protection and authority context.

Responsive behavior follows the existing breakpoints:

| Width | Behavior |
| --- | --- |
| At or above 1700px | Main inline padding increases to (42px). |
| At or below 1180px | Rail narrows to (190px); overview panels stack; mission stages form three columns; ticket fields form two columns; FX context moves below market summary. |
| At or below 900px | Rail becomes a top header with horizontally scrollable navigation; paired panels stack; research metrics form two columns. |
| At or below 600px | Main inline padding becomes (13px); research run list stacks above details and has a bounded scroll area; venue-rule and market-detail columns stack; mission stages and overview metrics form two columns. |

Wide market tables keep their comparison columns in a focusable horizontal scroll region rather than shrinking values into unreadable cells. English/Persian switching sets document language and direction; logical spacing and alignment mirror the shell, while symbols, decimals, JSON, commands, and chart coordinates remain isolated left-to-right. Theme and language preferences persist locally when browser storage is available.

## Elevation & Depth

Depth comes primarily from tonal surfaces, thin rules, and spacing. Light-theme panels have the existing faint ambient shadow (`0 2px 5px #4c382b08`); dark panels have no shadow. There are no decorative gradients, floating glass layers, or large entrance effects.

**The Quiet Surface Rule.** Selected controls use copper and clear state labels. Data containers stay visually steady while observations refresh.

## Shapes

Panels have gently rounded corners; controls are tighter, selected navigation slightly softer, and compact state chips nearly square. Thin borders carry structure. Source disclosures use the same control corner treatment rather than introducing another container style. Icons are simple inline stroked SVG; market initials provide modest asset markers without an external logo service.

The complete implemented radius set is (2px) for cost tracks, (4px) for chips and authority labels, (5px) for controls, (6px) for navigation and safety callouts, (7px) for banners and market initials, (10px) for panels, and (50%) for status dots.

## Components

### Buttons and fields

Primary buttons use copper with its paired text color. Secondary buttons share the panel surface and a visible rule. Standard buttons and fields have a minimum height of (39px). Hover uses the raised surface or slight copper brightening; press moves a control down (1px). Disabled controls reduce opacity to (.55) and retain their disabled semantics. Inputs have explicit labels, surface backgrounds, ruled borders, and copper caret and focus border. Invalid fields use negative borders and a specific error message. The offline ticket provides structured fields and a JSON editor for the same request.

### Navigation and mission sequence

All ten destinations are native hash links with a visible selected state and `aria-current="page"`. The mission sequence is a set of navigation shortcuts; its final execution stage stays visibly locked. At narrow widths, navigation scrolls within its own row. The mobile topbar preserves the disarmed state when the rail's longer reminder is hidden.

### Panels, tables, and disclosures

Panels group independent evidence or workflows. Table headers use raised surfaces, row hover uses the page tone, and numeric columns align at the reading edge. Selecting a market expands its quantities, blockers, warnings, rule source, and version inline. Saved runs select a detailed paper report; source records and decision details use native disclosure controls. Preserve open disclosures and focused row controls during refresh.

### States and charts

Compact chips pair semantic color with text. Render real loading, empty, error, stale, unavailable, unknown, and unverified states. A failed private account refresh removes old balances; a failed general refresh leaves a visible stale-data warning. Ticket edits invalidate the prior result, and pending previews expose busy state. Never populate empty panels with mock metrics.

Paper equity uses a labelled SVG line with currency and date context; cost bars retain exact textual values. Neither chart implies forecasting or validated performance. Shared-cash portfolios show native quote values and separately labeled causal USDT equivalents with FX freshness. Missing FX is unavailable, without a graph joining across unknown marks. Backups displays sanitized recorded backup/restore receipts; it does not infer current archive presence or physical-host recovery.

### Accessibility and motion

Keep the skip link, focusable main region, visible (2px) focus outline with (3px) offset, accessible field names, native table headers, expanded/pressed states, and live error or status announcements. Focus is copper on working surfaces and warm light copper on the rail. State transitions last (160ms) with `ease-out`; reduced-motion preference removes transitions and animations. No motion may carry unique information.

## Do's and Don'ts

### Do:

- **Do** use the same semantic CSS custom properties in light and dark themes.
- **Do** keep the disarmed boundary, evidence source, and relevant limitations near each action or result.
- **Do** preserve decimal strings, source timestamps, keyboard behavior, and English/Persian reading direction.
- **Do** use current API records for working screens and label all synthetic examples.
- **Do** expose missing integrations with precise unavailable or not-connected language.

### Don't:

- **Don't** turn a healthy feed, eligible rule, passed fixture, or paper return into a trading-readiness claim.
- **Don't** invent account assets, backup archives, diagnostic modules, protective stops, or funded authority to fill a reference composition.
- **Don't** substitute green decoration for explicit capability text or use color as the only state cue.
- **Don't** add exchange-custody secrets or recovery-passphrase inputs to ordinary browser workflows. Provider keys belong only in the existing scoped AI connections controls and never in browser storage.
- **Don't** fragment the ten destinations into unrelated themes, fonts, or component systems.
