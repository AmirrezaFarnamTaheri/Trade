"""The shortcut for a quote inside the forming bar must give the bars the general path gives."""
import random
from datetime import timedelta
from decimal import Decimal

from gym.domain.bars import BarSpec, Consolidator
from gym.domain.model import parse_ts


def test_quotes_inside_a_forming_bar_build_the_same_bars_as_the_general_path():
    rng = random.Random(7)
    fast, general = (Consolidator("BTCUSDT", BarSpec("1min"), publication_lag=timedelta(seconds=2)) for _ in range(2))
    general._gridded = False
    t, seen = parse_ts("2026-11-01T00:00:00Z"), ([], [])
    for _ in range(3000):
        t += timedelta(seconds=rng.choice((0, 1, 5, 40, 200)))
        price, qty = Decimal(rng.randint(90, 110)), Decimal(rng.randint(0, 3))
        for consolidator, out in zip((fast, general), seen, strict=True):
            out += consolidator.update(t, price, qty)
            out += consolidator.scan(t)
    assert seen[0] == seen[1] and len(seen[0]) > 500
    assert fast.forming(t) == general.forming(t)
