"""Fraction-preserving target-position protocol & legacy strategy adapter (spec §5.3)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .strategy import Snapshot


@dataclass(frozen=True)
class TargetIntent:
    version_id: int
    predecessor_version_id: int | None
    decided_at: datetime
    expires_at: datetime               # entry intent expires if unfilled; held exit follows inventory policy
    target_weight: Decimal             # desired account weight in [0, 1] on spot
    expected_gross_bps: Decimal        # horizon expected gross return in common currency
    urgency: str                       # "PASSIVE_MAKER" | "OPPORTUNISTIC" | "URGENT_TAKER" | "ABSTAIN"
    limit_offset_bps: Decimal | None
    reasons: tuple[str, ...]
    feature_values: dict[str, str | float | int | bool | None]

    def is_expired(self, as_of: datetime) -> bool:
        return as_of >= self.expires_at


def compute_required_child_delta(
    target_units: Decimal,
    held_units: Decimal,
    working_uncanceled_units: Decimal,
) -> Decimal:
    """Exact remaining signed child delta accounting for held + working uncanceled remainder."""
    return target_units - held_units - working_uncanceled_units


class LegacyStrategyAdapter:
    """Exact free-cash-preserving wrapper turning legacy decide(snap, holding) strategies into TargetIntent."""

    def __init__(
        self,
        legacy_strategy,
        *,
        default_ttl_s: float = 300.0,
        default_urgency: str = "PASSIVE_MAKER",
    ) -> None:
        self._strategy = legacy_strategy
        self._default_ttl_s = default_ttl_s
        self._default_urgency = default_urgency
        self._version = 0

    def evaluate(
        self,
        snap: Snapshot,
        *,
        held_base_qty: Decimal,
        free_cash_quote: Decimal,
        equity_quote: Decimal,
        expected_gross_bps: Decimal = Decimal(0),
    ) -> TargetIntent:
        if equity_quote <= 0:
            raise ValueError("equity_quote must be > 0")
        mark_bid = snap.bid if snap.bid is not None and snap.bid > 0 else snap.bar.close
        w_held = max(Decimal(0), min(Decimal(1), (held_base_qty * mark_bid) / equity_quote))
        w_free = max(Decimal(0), min(Decimal(1), free_cash_quote / equity_quote))
        holding_flag = w_held > Decimal("0.01")

        action, fraction, reasons, _ = self._strategy.decide(snap, holding_flag)
        prev_ver = self._version if self._version > 0 else None
        self._version += 1
        expires_at = snap.as_of + timedelta(seconds=self._default_ttl_s)
        feats = dict(getattr(self._strategy, "feature_values", {}) or {})

        if action.startswith("ABSTAIN"):
            return TargetIntent(
                version_id=self._version,
                predecessor_version_id=prev_ver,
                decided_at=snap.as_of,
                expires_at=expires_at,
                target_weight=w_held,
                expected_gross_bps=Decimal(0),
                urgency="ABSTAIN",
                limit_offset_bps=None,
                reasons=(action, *reasons),
                feature_values=feats,
            )
        if action == "BUY_REQUEST":
            target_w = min(Decimal(1), w_held + fraction * w_free)
            return TargetIntent(
                version_id=self._version,
                predecessor_version_id=prev_ver,
                decided_at=snap.as_of,
                expires_at=expires_at,
                target_weight=target_w,
                expected_gross_bps=expected_gross_bps,
                urgency=self._default_urgency,
                limit_offset_bps=Decimal(0),
                reasons=reasons,
                feature_values=feats,
            )
        if action == "SELL_REQUEST":
            target_w = max(Decimal(0), w_held * (Decimal(1) - fraction))
            return TargetIntent(
                version_id=self._version,
                predecessor_version_id=prev_ver,
                decided_at=snap.as_of,
                expires_at=expires_at,
                target_weight=target_w,
                expected_gross_bps=expected_gross_bps,
                urgency=self._default_urgency,
                limit_offset_bps=Decimal(0),
                reasons=reasons,
                feature_values=feats,
            )
        return TargetIntent(
            version_id=self._version,
            predecessor_version_id=prev_ver,
            decided_at=snap.as_of,
            expires_at=expires_at,
            target_weight=w_held,
            expected_gross_bps=expected_gross_bps,
            urgency="PASSIVE_MAKER",
            limit_offset_bps=None,
            reasons=reasons,
            feature_values=feats,
        )
