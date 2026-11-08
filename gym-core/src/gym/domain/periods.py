"""Period definitions for the canonical streaming consolidator."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import UTC


def instant(t: datetime) -> datetime:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("timestamp must be an aware instant")
    return t.astimezone(UTC)


@dataclass(frozen=True)
class Fixed:
    step: timedelta
    anchor: datetime = datetime(1970, 1, 1, tzinfo=UTC)

    def __post_init__(self):
        if not isinstance(self.step, timedelta) or self.step <= timedelta(0):
            raise ValueError("fixed step must be positive")
        object.__setattr__(self, "anchor", instant(self.anchor))

    def __call__(self, t):
        start = self.anchor + ((instant(t) - self.anchor) // self.step) * self.step
        return start, start + self.step


@dataclass(frozen=True)
class Count:
    n: int

    def __post_init__(self):
        if type(self.n) is not int or self.n <= 0:
            raise ValueError("trade count must be a positive integer")


@dataclass(frozen=True)
class Volume:
    q: Decimal

    def __post_init__(self):
        if not isinstance(self.q, Decimal) or not self.q.is_finite() or self.q <= 0:
            raise ValueError("volume threshold must be a positive finite Decimal")


@dataclass(frozen=True)
class Calendar:
    """Exact supplied boundaries (e.g. Jalali); no Gregorian relabeling or approximation."""
    fn: Callable[[datetime], tuple[datetime, datetime]]

    def __post_init__(self):
        if not callable(self.fn):
            raise ValueError("calendar requires a boundary function")

    def __call__(self, t):
        return self.fn(t)


@dataclass(frozen=True)
class Mixed:
    """First limit wins; a threshold-crossing trade stays whole in the closing bar."""
    periods: tuple

    def __post_init__(self):
        object.__setattr__(self, "periods", tuple(self.periods))
        if len(self.periods) < 2 or any(not isinstance(p, (Fixed, Calendar, Count, Volume)) for p in self.periods):
            raise ValueError("mixed requires at least two time/count/volume limits")


@dataclass(frozen=True)
class DirectionalChange:
    """Log-return reversal bars, bid-confirmed upward and ask-confirmed downward."""
    delta_up: Decimal
    delta_down: Decimal | None = None

    def __post_init__(self):
        if self.delta_down is None:
            object.__setattr__(self, "delta_down", self.delta_up)
        for value in (self.delta_up, self.delta_down):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("directional thresholds must be positive finite Decimals")


PeriodSpec = Fixed | Count | Volume | Mixed | Calendar | DirectionalChange
