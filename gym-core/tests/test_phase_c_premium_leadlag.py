"""Phase C items 25-26: point-in-time premium and lead-lag contract tests."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.bars import Bar, BarSpec
from gym.domain.cross_market_models import CausalPremiumMoments, ar1_half_life
from gym.domain.model import BookTop
from gym.domain.registry import create_strategy
from gym.domain.strategy import Snapshot
from gym.services.premium_lead_lag import analyze_lead_lag
from tests.support import START


def test_ar1_half_life_fits_known_single_bar_decay():
    """AR(1) phi=0.5 has exactly one bar half-life with the intercept fitted."""
    samples = []
    value = Decimal(16)
    for _ in range(50):
        samples.append(value)
        value /= 2
    fit = ar1_half_life(samples)
    assert fit["status"] == "IDENTIFIED"
    assert abs(Decimal(fit["phi"]) - Decimal("0.5")) < Decimal("1e-20")
    assert abs(Decimal(fit["half_life_bars"]) - 1) < Decimal("1e-16")


def test_premium_ewma_uses_only_prior_discounts_and_resets_when_gap():
    stats = CausalPremiumMoments()
    for i in range(24):
        assert stats.score(Decimal(300)) is None if i < 20 else stats.score(Decimal(300)) is not None
        stats.observe(Decimal(i % 4))
    before = stats.score(Decimal(300))
    assert before > Decimal(2)
    stats.observe(Decimal(300))
    assert stats.score(Decimal(300)) < before
    stats.reset()
    assert stats.score(Decimal(300)) is None


def _snap(i, primary_mid, reference=Decimal(100)):
    """One causal bar and references qualified before the close."""
    start = START + timedelta(minutes=i)
    bar = Bar("BTCTMN", BarSpec("1min"), start, start + timedelta(minutes=1),
              start + timedelta(minutes=1), primary_mid, primary_mid,
              primary_mid, primary_mid, Decimal(1), 2)
    observed = start + timedelta(seconds=40)
    return Snapshot(
        as_of=bar.end, symbol="BTCTMN", bar=bar,
        bid=primary_mid - Decimal("0.5"), ask=primary_mid + Decimal("0.5"),
        quote_time=observed, execution={"fee_rate": "0.001"},
        auxiliary_quotes=(
            BookTop("BTCUSDT", observed, reference, reference + Decimal("0.01"),
                    Decimal(10), Decimal(10), frozenset()),
            BookTop("USDTTMN", observed, Decimal(100), Decimal("100.01"),
                    Decimal(10), Decimal(10), frozenset()),
        ),
    )


def test_z_premium_is_opt_in_and_uses_prior_history_for_entry():
    default = create_strategy("toman-premium")
    assert default.version == 1
    assert "z_entry" not in default.params
    candidate = create_strategy("toman-premium", {"z_entry": 2, "z_exit": 0,
                                                  "half_life_multiple": 2})
    assert candidate.version == 2
    assert candidate.config_hash != default.config_hash
    for i in range(24):
        # Center varies by a few basis points to seed a strictly positive EWMA variance.
        discount = Decimal(i % 4)
        price = Decimal(10000) / (1 + discount / 10000) - Decimal("0.5")
        candidate.decide(_snap(i, price), False)
    spike = Decimal(10000) / Decimal("1.05") - Decimal("0.5")
    action, _, _, _ = candidate.decide(_snap(24, spike), False)
    assert action == "BUY_REQUEST"
    assert Decimal(candidate.feature_values["discount_z"]) > 2
    assert "half_life_bars" in candidate.feature_values
    with pytest.raises(ValueError):
        create_strategy("toman-premium", {"half_life_multiple": 2})


def _lag_snap(i, primary, leader):
    start = START + timedelta(minutes=i)
    bar = Bar("SOLUSDT", BarSpec("1min"), start, start + timedelta(minutes=1),
              start + timedelta(minutes=1), Decimal(primary), Decimal(primary),
              Decimal(primary), Decimal(primary), Decimal(1), 1)
    observed = start + timedelta(seconds=59)
    return Snapshot(as_of=bar.end, symbol="SOLUSDT", bar=bar,
                    bid=Decimal(primary) - Decimal("0.05"),
                    ask=Decimal(primary) + Decimal("0.05"),
                    quote_time=observed, execution={"fee_rate": "0.001"},
                    reference=BookTop("BTCUSDT", observed, Decimal(leader) - Decimal("0.05"),
                                      Decimal(leader) + Decimal("0.05"),
                                      Decimal(10), Decimal(10), frozenset()))


def test_lag_strategy_default_identity_and_explicit_delay_feature():
    default = create_strategy("lead-lag")
    assert default.version == 1 and "delay_bars" not in default.params
    candidate = create_strategy("lead-lag", {"lookback": 2, "delay_bars": 2})
    assert candidate.version == 2
    for i, price in enumerate(["100", "120", "130", "140", "160"]):
        candidate.decide(_lag_snap(i, "100", price), False)
    assert Decimal(candidate.feature_values["leader_return_bps"]) == Decimal(3000)
    assert candidate.feature_values["delay_bars"] == 2
    with pytest.raises(ValueError):
        create_strategy("lead-lag", {"delay_bars": 13})


def test_lead_lag_delay_scan_selects_on_earlier_partition_only():
    leader_changes = [Decimal((i * 17) % 19 - 9) / 10000 for i in range(90)]
    follower_changes = [Decimal(0), Decimal(0), *leader_changes[:-2]]
    leader, follower = Decimal(100), Decimal(100)
    leader_books, follower_books = [], []
    for i, (lr, fr) in enumerate(zip(leader_changes, follower_changes)):
        leader *= 1 + lr
        follower *= 1 + fr
        at = START + timedelta(minutes=i, seconds=50)
        leader_books.append(BookTop("BTCUSDT", at, leader, leader + Decimal("0.01"),
                                    Decimal(10), Decimal(10), frozenset()))
        follower_books.append(BookTop("SOLUSDT", at, follower, follower + Decimal("0.01"),
                                      Decimal(10), Decimal(10), frozenset()))
    report = analyze_lead_lag(
        follower_books, leader_books, START, START + timedelta(minutes=90),
        resolution="1min", max_age_seconds=90, max_skew_seconds=5,
        min_overlap=20, max_delay_bars=3, store="demo",
    )
    assert report["schema"] == "lead-lag/2"
    assert report["selection_basis"] == "CHRONOLOGICAL_TRAIN_ONLY"
    assert report["best_training_delay"] == 2
    assert len(report["delay_scan"]) == 3
    assert report["held_out"] is False
    assert report["established_edge"] is False
    assert Decimal(report["delay_scan"][1]["holdout_correlation"]) > Decimal("0.9")


def test_premium_z_signal_is_not_marked_ready_before_its_prior_warmup():
    candidate = create_strategy("toman-premium", {"z_entry": 2})
    action, _, _, _ = candidate.decide(_snap(0, Decimal(9500)), False)
    assert action == "ABSTAIN_WARMUP"
    assert candidate.ready is False


def test_z_premium_preserves_holding_age_across_quote_gap():
    """A gap clears estimation history, not the age of an already held paper position."""
    candidate = create_strategy("toman-premium", {"z_entry": 2, "half_life_multiple": 2})
    for i in range(24):
        candidate.decide(_snap(i, Decimal(9800) + Decimal(i % 3)), False)
    candidate.decide(_snap(24, Decimal(9500)), True)
    entered = candidate.holding_since
    assert entered == _snap(24, Decimal(9500)).bar.start

    action, _, _, _ = candidate.decide(_snap(30, Decimal(9500)), True)
    assert action == "HOLD"
    assert candidate.holding_since == entered
    assert candidate.feature_values["discount_z"] is None
    assert candidate.ready is False


def test_z_premium_can_exit_on_reversion_during_gap_warmup():
    """No new entry is allowed during warmup, but a held position can exit."""
    candidate = create_strategy("toman-premium", {"z_entry": 2})
    for i in range(24):
        candidate.decide(_snap(i, Decimal(9800) + Decimal(i % 3)), False)
    candidate.decide(_snap(24, Decimal(9500)), True)
    action, _, _, _ = candidate.decide(_snap(30, Decimal(11000)), True)
    assert action == "SELL_REQUEST"
    assert candidate.feature_values["discount_z"] is None
    assert candidate.ready is False
