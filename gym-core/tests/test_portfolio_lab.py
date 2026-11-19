import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")  # the research extra; CI installs the core only

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from portfolio_lab import (  # noqa: E402
    BORROW_PER_DAY,
    FLOOR,
    MARGIN_COST,
    SPOT_COST,
    simulate,
    strategy_blend,
    xs_momentum,
)


def panel(closes, highs=None, lows=None):
    c = np.array(closes, float)
    return {"close": c, "high": np.array(highs, float) if highs else c.copy(), "low": np.array(lows, float) if lows else c.copy(),
            "liquid": np.ones(c.shape, bool)}


def test_a_spot_long_earns_the_move_after_the_spot_cost():
    p = panel([[100], [110], [110]])
    r, counts = simulate(p, np.array([[1.0], [1.0], [0.0]]))
    assert r[1] == pytest.approx(0.10 - SPOT_COST)
    assert counts["OPEN_LONG"] == 1 and counts["HOLD"] == 1


def test_a_short_pays_the_margin_cost_and_a_day_of_borrowing():
    p = panel([[100], [90]])
    r, counts = simulate(p, np.array([[-1.0], [0.0]]))
    assert r[1] == pytest.approx(0.10 - MARGIN_COST - BORROW_PER_DAY)
    assert counts["OPEN_SHORT"] == 1


def test_a_levered_short_into_a_spike_is_liquidated_at_the_floor():
    # 2x gross book: a short adverse move of 50% breaches (1 - floor) / 2 = 42.5%
    p = panel([[100, 100], [100, 100]], highs=[[100, 100], [150, 100]])
    r, counts = simulate(p, np.array([[-1.0, 1.0], [0.0, 0.0]]))
    assert counts["LIQUIDATED"] == 1 and counts["LEVERED_DAYS"] == 1
    lost = 1.0 / 2 * (1 - FLOOR)
    assert r[1] == pytest.approx(-lost - 2 * (0.5 * SPOT_COST + 0.5 * MARGIN_COST) * 0.5 - MARGIN_COST - 1.0 * BORROW_PER_DAY, abs=0.002)


def test_xs_momentum_is_dollar_neutral_and_only_rebalances_weekly():
    rng = np.random.default_rng(0)
    closes = np.cumprod(1 + rng.normal(0, 0.03, (80, 30)), axis=0) * 100
    w = xs_momentum(panel(closes.tolist()), lookback=28, decile=0.1, every=7)
    live = w[35]
    assert live.sum() == pytest.approx(0.0) and np.abs(live).sum() == pytest.approx(1.0)
    assert (w[36] == w[35]).all() and (w[42] != w[35]).any()


def test_strategy_blend_weights_the_calmer_book_more():
    rng = np.random.default_rng(1)
    closes = np.cumprod(1 + np.column_stack([rng.normal(0, 0.01, 200), rng.normal(0, 0.04, 200)]), axis=0) * 100
    p = panel(closes.tolist())
    calm, wild = np.zeros((200, 2)), np.zeros((200, 2))
    calm[:, 0], wild[:, 1] = 1.0, 1.0
    blended = strategy_blend(p, [calm, wild], lookback=60)
    assert blended[150, 0] > 3 * blended[150, 1] > 0
    assert blended[150].sum() == pytest.approx(1.0)


def test_vol_target_scales_by_the_held_coins_volatility_not_the_books_past():
    from portfolio_lab import vol_target
    rng = np.random.default_rng(2)
    daily = rng.normal(0, 0.02, 120)
    closes = (np.cumprod(1 + daily) * 100)[:, None]
    w = np.zeros((120, 1))
    w[100:, 0] = 1.0  # flat for 100 days, then long: the old book-based estimate would jump to the cap here
    scaled = vol_target(panel(closes.tolist()), w, target=0.40, cap=3.0, lookback=30)
    realized = np.std(daily[71:101], ddof=1) * np.sqrt(365)
    assert scaled[100, 0] == pytest.approx(0.40 / realized, rel=1e-9)
    assert scaled[100, 0] < 1.5 and scaled[:100].sum() == 0


def test_vol_target_retains_covariance_for_a_signed_book():
    from portfolio_lab import vol_target

    moves = np.array([[0.0, 0.0], [0.02, 0.01], [-0.01, 0.03], [0.03, -0.02]])
    prices = 100 * np.cumprod(1 + moves, axis=0)
    weights = np.tile([0.5, -0.5], (len(prices), 1))
    covariance = np.cov(moves[1:], rowvar=False)
    annual_vol = np.sqrt(365 * (weights[-1] @ covariance @ weights[-1]))
    actual = vol_target(panel(prices.tolist()), weights, target=0.4, lookback=3)
    assert actual[-1] == pytest.approx(weights[-1] * min(3.0, 0.4 / annual_vol))


def test_drawdown_counts_a_loss_on_the_first_scored_day():
    from portfolio_lab import stats

    result = stats(np.array([0.5, -0.2, 0.1, 0.0]), {}, start=1)
    assert result["max_drawdown_pct"] == pytest.approx(20.0)
    assert result["total_pct"] == pytest.approx(-12.0)


def test_an_unlevered_book_never_borrows_to_pay_its_costs():
    rng = np.random.default_rng(3)
    closes = np.cumprod(1 + rng.normal(0, 0.03, (60, 5)), axis=0) * 100
    w = np.full((60, 5), 0.2)
    _, counts = simulate(panel(closes.tolist()), w)
    assert counts["LEVERED_DAYS"] == 0 and counts["LIQUIDATED"] == 0
