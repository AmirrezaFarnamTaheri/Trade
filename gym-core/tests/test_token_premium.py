"""Premium statistics report the middle and spread of the gap, and a half-life that grows with persistence."""
import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("token_premium", SCRIPTS / "token_premium.py")
premium = importlib.util.module_from_spec(spec)
spec.loader.exec_module(premium)


def test_a_slowly_closing_gap_has_a_longer_half_life_than_a_quickly_closing_one():
    slow, fast, gap_s, gap_f = [], [], 0.05, 0.05
    for k in range(200):
        gap_s, gap_f = gap_s * 0.9 + (0.01 if k % 50 == 0 else 0), gap_f * 0.3 + (0.01 if k % 50 == 0 else 0)
        slow.append(gap_s)
        fast.append(gap_f)
    assert premium.premium_stats(slow)["half_life_days"] > premium.premium_stats(fast)["half_life_days"]
    assert premium.premium_stats(slow)["p10"] <= premium.premium_stats(slow)["median"] <= premium.premium_stats(slow)["p90"]
