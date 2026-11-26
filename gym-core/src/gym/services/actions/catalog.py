"""Single declarative source of truth for research action metadata, CLI/browser exposure, and worker policy.

Import-light by design: inspecting action metadata never imports the collector, database store,
or optional research fitting libraries.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..operator_actions import OPERATOR_ACTIONS

PROTOCOL_ACTIONS = frozenset((
    "outcome-add", "outcomes", "final-register", "final-run",
    "final-status", "observe-import", "screen", "derived", "unit-convert",
))

WORKSPACE_ACTIONS = (
    *OPERATOR_ACTIONS,
    "premium-research", "lead-lag-research", "twap-preview", "stop-preview",
    "credit-packages", "credit-replay", "arm-policy-read", "arm-policy-save",
    "execution-choice-preview", "adaptive-twap-preview", "postfill-check",
    "shadow-drift-screen", "feed-divergence-screen", "feed-divergence-lock",
    "fairprice-observe", "fairprice-read", "prospective-register",
    "prospective-status", "prospective-evaluate", "experiment-scorecard",
    "fractional-sizing", "campaign-status", "universe-manifest",
    "market-products", "robustness", "execution-calibration",
    "execution-model-calibrate", "walk-forward", "portfolio-replay",
    "portfolio-read", "portfolio-list", "margin-markets", "margin-preview",
    "margin-replay", "margin-pairs-replay", "combine-oos",
    "strategy-retirement-screen", "unit-convert", "market-breadth",
    "depth-audit", "entry-lock-add", "entry-locks", "replay-checkpoint",
    "replay-resume", "registry-page", "annotation-add", "annotation-list",
    "coverage", "market-screen", "return-correlations", "replay", "rebalance",
    "execution-quality", "experiment-run", "experiment-list",
    "experiment-status", "job-recover", "job-catch-up", "job-interrupt",
    "strategy-audit", "return-bootstrap", "watchlist-save", "watchlist-read",
)

LEDGER_ACTIONS = (
    "register", "shadow-open", "shadow-close", "schedule", "tick", "start",
    "pause", "resume", "list", "claim-check", "review",
)

MARKET_REPORT_ACTIONS = (
    "candles", "technicals", "spreads", "trade-flow", "diagnostic",
    "factor-ic-lab", "trend-replay", "verify-release-attestation",
    "raw-replay-audit", "spot-receipt-replay",
)

CLI_ACTIONS = tuple(dict.fromkeys((
    *LEDGER_ACTIONS, *sorted(PROTOCOL_ACTIONS), *MARKET_REPORT_ACTIONS, *WORKSPACE_ACTIONS,
)))

CLI_ONLY_ACTIONS = {
    "raw-replay-audit": "read-only archived frame comparison for a bounded receipt interval",
    "spot-receipt-replay": "offline spot orders sharing one recorded best level",
    "trend-replay": "bounded offline daily bid/ask and spot lot rules",
    "factor-ic-lab": "bounded offline factor and forward-label JSON",
    "verify-release-attestation": "trusted key and expected release digest are supplied offline",
    "tick": "scheduler step; the browser uses the dedicated research runner",
    "start": "long-running scheduler process",
    "pause": "browser pauses jobs through /api/research/jobs/{id}/pause",
    "resume": "browser resumes jobs through /api/research/jobs/{id}/resume",
    "adaptive-twap-preview": "no browser form yet",
    "fairprice-observe": "no browser form yet",
    "fairprice-read": "no browser form yet",
    "feed-divergence-lock": "no browser form yet",
    "feed-divergence-screen": "no browser form yet",
    "postfill-check": "no browser form yet",
    "shadow-drift-screen": "no browser form yet",
}

_NON_OBJECT_WORKSPACE = frozenset((
    "portfolio-list", "experiment-list", "experiment-status", "entry-locks",
    "margin-markets", "credit-packages", "prospective-status",
    "prospective-evaluate", "arm-policy-read",
))

OBJECT_ACTIONS = frozenset((
    "register", "shadow-open", "shadow-close", "schedule", "review",
    "claim-check", "final-register", "observe-import", "screen", "derived",
    "diagnostic", "candles", "factor-ic-lab", "verify-release-attestation",
    "trend-replay", "raw-replay-audit", "spot-receipt-replay",
    *OPERATOR_ACTIONS,
    *(a for a in WORKSPACE_ACTIONS if a not in _NON_OBJECT_WORKSPACE),
))

HEAVY_ACTIONS = frozenset((
    "premium-research", "lead-lag-research", "twap-preview", "stop-preview",
    "credit-packages", "credit-replay", "execution-choice-preview",
    "adaptive-twap-preview", "postfill-check", "shadow-drift-screen",
    "prospective-evaluate", "experiment-scorecard", "fractional-sizing",
    "campaign-status", "tick", "job-catch-up", "experiment-run",
    "walk-forward", "execution-calibration", "robustness", "strategy-audit",
    "return-bootstrap", "replay-checkpoint", "replay-resume", "final-run",
    "comparison", "validation", "margin-markets", "margin-preview",
    "margin-replay", "margin-pairs-replay", "combine-oos",
    "strategy-retirement-screen", "portfolio-replay",
    "execution-model-calibrate",
))


@dataclass(frozen=True)
class ActionPolicy:
    action: str
    cli: bool
    browser: bool
    browser_note: str | None
    object_input: bool
    heavy_worker: bool


def action_policy(action: str) -> ActionPolicy:
    if action not in CLI_ACTIONS:
        raise ValueError(f"unknown research action: {action!r}")
    return ActionPolicy(
        action=action,
        cli=True,
        browser=action not in CLI_ONLY_ACTIONS,
        browser_note=CLI_ONLY_ACTIONS.get(action),
        object_input=action in OBJECT_ACTIONS,
        heavy_worker=action in HEAVY_ACTIONS,
    )


def action_catalog() -> list[dict]:
    """Every research action with where it can be used (CLI, browser), input kind, and worker policy."""
    return [
        {
            "action": action,
            "cli": True,
            "browser": action not in CLI_ONLY_ACTIONS,
            "browser_note": CLI_ONLY_ACTIONS.get(action),
            "object_input": action in OBJECT_ACTIONS,
            "heavy_worker": action in HEAVY_ACTIONS,
        }
        for action in sorted(CLI_ACTIONS)
    ]
