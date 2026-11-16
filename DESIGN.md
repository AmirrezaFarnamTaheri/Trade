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
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.55
    letterSpacing: "-0.015em"
  title:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "17px"
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
    fontSize: "21px"
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
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.55
  nested-heading:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "14px"
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
    fontSize: "17px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.7px"
  brand-mobile:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "21px"
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: "-0.7px"
  fx-metric:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Tahoma, sans-serif'
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.02em"
  chart:
    fontFamily: '"Segoe UI", sans-serif'
    fontSize: "17px"
    fontWeight: 400
  waterfall:
    fontFamily: '"Segoe UI", sans-serif'
    fontSize: "17px"
    fontWeight: 400
rounded:
  track: "2px"
  badge: "4px"
  control: "4px"
  navigation: "6px"
  banner: "6px"
  panel: "10px"
  round: "50%"
spacing:
  tight: "4px"
  control-gap: "8px"
  row: "12px"
  group: "16px"
  section: "20px"
  panel: "20px"
  view: "24px"
  workspace-inline: "32px"
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

TradingGYM is an operator's research register: warm working surfaces, a charcoal
navigation rail, copper selection and ruled data. The frontmatter owns the exact
light/dark palette, type, spacing and component tokens; implementations use the
corresponding semantic CSS properties.

## Evidence and exact values

Keep execution disarmed and show each result's source, time and scope beside it.
A healthy feed or successful paper run describes that evidence alone. Render
missing, stale, unknown and unverified states explicitly, with text as well as
color. Empty screens use the real empty state; synthetic examples carry a label.

Preserve API decimal strings for calculations, submissions, inspection and export.
Use tabular figures and bidirectional isolation. Floating-point conversion is
limited to chart geometry. Account failures remove old private balances; general
refresh failures retain a visible stale-data warning. Editing a ticket invalidates
its previous result.

## Typography and charts

Use Segoe UI Variable Text, Segoe UI, Tahoma and platform sans-serif; Cascadia Code
or Consolas for records and commands. Body text is 14px, help is 12px and compact
functional labels have an 11px floor. Leads stay within 72ch.

Charts use SVG geometry with HTML axis labels and exact text readouts. Comparison
series have distinct dash patterns as well as colors. Missing marks break paths.
Show native quote currency and separately labeled causal USDT values, including
FX freshness. Curves describe recorded paper outcomes.

## Layout

The desktop shell has a 214px sticky rail, a fluid workspace up to 1660px and 30px
inline padding. The topbar preserves destination, disarmed state, feed status and
Tehran time. Nine native hash links share the same visual system and selected state.

| Width | Layout |
| --- | --- |
| >=1700px | 42px main inline padding. |
| <=1180px | 190px rail; overview panels stack; ticket fields use two columns. |
| <=900px | Rail becomes a top header with scrolling navigation; paired panels stack. |
| <=600px | 13px inline padding; single-column forms; run list above details; compact actions at least 44px high. |

Wide tables scroll within a keyboard-focusable region. Paper reports retain the
228px saved-run rail on wider screens. English/Persian switching sets document
language and direction; logical spacing mirrors the shell. Symbols, amounts,
JSON and commands remain left-to-right. Persist theme/language locally when able.

## Components and states

Copper identifies primary actions and selection. Neutral tonal surfaces, thin
rules and spacing group records; semantic colors describe specific states.
Light panels use the faint recorded shadow, dark panels none. Use the frontmatter
radius scale and inline stroked SVG icons.

Fields have explicit labels, visible invalid states and specific errors. Standard
controls are at least 39px high. Disabled controls retain native semantics. Panels
preserve focus and open disclosures while refreshing. Tables use native headers,
aligned numeric columns and inline market details. Backups shows recorded receipts;
current archive availability and runtime recovery require separate verification.

## Accessibility and motion

Retain the skip link, focusable main region, 2px focus outline with 3px offset,
accessible names, aria-current, expanded/pressed states and live status/error
announcements. Keep the disarmed state visible on phones. State transitions use
160ms ease-out; reduced-motion removes animation. Motion carries no unique data.

Browser checks cover both languages/themes, narrow widths, keyboard operation,
chart readability and contrast. Source review alone does not establish these.

Credentials and recovery passphrases stay in protected console workflows.
