"""PSI drift: identical regimes are stable, a widened spread or a volatility jump is flagged, thin data abstains."""
import math
import random
from datetime import timedelta
from decimal import Decimal

from gym.domain.model import BookTop
from gym.services.data_portal import DataPortal
from gym.services.drift import band, drift, psi
from tests.support import START, market_db


def history(tmp_path, *, spread_after=2, vol_after=1.0, n=6000):
    rng, px, rows = random.Random(7), 70000.0, []
    for i in range(n):  # one quote every 10 s; the regime changes halfway
        late = i >= n // 2
        px *= math.exp(rng.gauss(0, 0.0004 * (vol_after if late else 1.0)))
        half = Decimal(str(round(px * (spread_after if late else 2) / 20000, 2)))
        mid = Decimal(str(round(px, 2)))
        rows.append(BookTop("BTCUSDT", START + timedelta(seconds=10 * i), mid - half, mid + half,
                            Decimal(1), Decimal(1), frozenset()))
    return DataPortal(market_db(tmp_path, rows))


def windows(n=6000):
    middle = START + timedelta(seconds=10 * n // 2)
    return (START, middle), (middle, START + timedelta(seconds=10 * n))


def test_psi_is_zero_for_the_same_distribution_and_abstains_on_thin_data():
    values = [float(i % 97) for i in range(1000)]
    assert psi(values, values) == 0 and band(0.0) == "STABLE"
    assert psi(values[:20], values) is None and band(None) == "INSUFFICIENT_DATA"


def test_unchanged_regime_is_stable_and_shifts_are_flagged(tmp_path):
    reference, recent = windows()
    calm = drift(history(tmp_path / "a"), "BTCUSDT", reference, recent)
    assert calm["status"] == "STABLE", calm
    wide = drift(history(tmp_path / "b", spread_after=8), "BTCUSDT", reference, recent)
    assert wide["metrics"]["spread_bps"]["band"] == "SHIFTED" and wide["status"] == "SHIFTED"
    wild = drift(history(tmp_path / "c", vol_after=3.0), "BTCUSDT", reference, recent)
    assert wild["metrics"]["return_bps_1min"]["band"] in ("MODERATE", "SHIFTED")
    assert wild["metrics"]["return_bps_1min"]["psi"] > calm["metrics"]["return_bps_1min"]["psi"]
