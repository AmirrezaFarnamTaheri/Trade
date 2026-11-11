"""Every registered strategy passes truncation, future-perturbation and warm-up checks; seeded leaks are caught."""
import math
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop
from gym.domain.registry import STRATEGIES
from gym.domain.strategy import long_flat
from gym.services import bias_harness
from gym.services.bias_harness import build_store, check, perturbed
from tests.support import START

STEP, N, RES = 30, 3200, "5min"
WINDOW = timedelta(seconds=STEP * N)
T0, T1 = START + WINDOW / 4, START + WINDOW  # the first quarter is prehistory for the warm-up check
CUTS = [START + WINDOW * 9 // 20, START + WINDOW * 3 // 4]
# The fixture's reference quotes share timestamps with the traded market but can trail a bar close by one step.
PARAMS = {"lead-lag": {"max_skew_seconds": 120}, "toman-premium": {"max_skew_seconds": 120}}
SYMBOL = {"toman-premium": "BTCTMN"}


def series(sym, base, amp=0.04, period=900, phase=0.0):
    out = []
    for i in range(N):
        px = Decimal(str(round(base * (1 + amp * math.sin(2 * math.pi * i / period + phase) + 0.00002 * i), 2)))
        half = px * Decimal("0.0002")
        out.append(BookTop(sym, START + timedelta(seconds=STEP * i), px - half, px + half, Decimal(1), Decimal(1), frozenset()))
    return out


ROWS = (series("BTCUSDT", 70000) + series("ETHUSDT", 2500, phase=0.6)
        + series("USDTTMN", 100000, amp=0.01, period=1300) + series("BTCTMN", 7_000_000_000, phase=0.1))


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    root = tmp_path_factory.mktemp("bias")
    base = build_store(root / "base.db", ROWS)
    after = {cut: build_store(root / f"after-{i}.db", perturbed(ROWS, cut)) for i, cut in enumerate(CUTS)}
    return base, after


def run_check(stores, name, params=None, symbol=None):
    base, after = stores
    symbol = symbol or SYMBOL.get(name, "BTCUSDT")
    cash = Decimal(10**9) if symbol.endswith("TMN") else Decimal(1000)
    return check(base, after, name, PARAMS.get(name, {}) if params is None else params, symbol, T0, T1, RES, cash,
                 cuts=CUTS, prehistory=WINDOW / 4)


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_registered_strategy_has_no_lookahead_and_settles_after_warmup(stores, name):
    report = run_check(stores, name)
    assert report["decisions"] >= 200 and report["acting"] > 0, report
    assert report["warmup"]["compared"] >= 30, report["warmup"]
    assert report["passed"], report


class Oracle:
    """A deliberately leaky strategy: it precomputes from the whole stored history, then reads two bars ahead."""
    name = "oracle"
    portal = None  # the portal of the store being replayed, captured below

    def __init__(self):
        self.params, self.feature_values, self.future = {}, {}, None

    def decide(self, snap, holding):
        if self.future is None:
            self.future = {r.ts_avail: r.bid for r in Oracle.portal.tops("BTCUSDT", START, T1 + timedelta(days=1))}
        ahead = self.future.get(snap.as_of + timedelta(minutes=10))
        trend = None if ahead is None else ahead > snap.bar.close
        self.feature_values = {"ahead": str(ahead), "trend": trend}
        return long_flat(snap, holding, trend, self.feature_values)


def test_a_strategy_that_reads_the_future_is_caught(stores, monkeypatch):
    real_init = bias_harness.DataPortal.__init__

    def capture(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        Oracle.portal = self
    monkeypatch.setattr(bias_harness.DataPortal, "__init__", capture)
    monkeypatch.setitem(STRATEGIES, "oracle", (Oracle, "Oracle", {}))
    report = run_check(stores, "oracle", params={})
    assert not report["passed"]
    # Truncation cannot see this leak (the full history is still stored); repricing the future can.
    assert all(report["perturbation"].values())


def test_a_data_layer_that_publishes_quotes_early_is_caught(stores, monkeypatch):
    # Classic event-time versus availability-time bug: every quote is treated as available one minute early.
    real = bias_harness.DataPortal.tops

    def early(self, symbol, t0, t1):
        rows = real(self, symbol, t0, t1 + timedelta(minutes=1))
        shifted = [BookTop(r.symbol, r.ts_avail - timedelta(minutes=1), r.bid, r.ask, r.bid_qty, r.ask_qty, r.flags) for r in rows]
        return [r for r in shifted if t0 <= r.ts_avail < t1]
    monkeypatch.setattr(bias_harness.DataPortal, "tops", early)
    report = run_check(stores, "ema-trend")
    assert not report["passed"] and any(report["perturbation"].values())


class AllHistoryMean:
    """Recursively unstable: long above the mean of every close since the replay began, so the start date matters forever."""
    name = "all-history-mean"

    def __init__(self):
        self.params, self.feature_values, self.total, self.count = {}, {}, Decimal(0), 0

    def decide(self, snap, holding):
        self.total, self.count = self.total + snap.bar.close, self.count + 1
        mean = self.total / self.count
        self.feature_values = {"mean": str(mean), "trend": snap.bar.close > mean if self.count >= 5 else None}
        return long_flat(snap, holding, self.feature_values["trend"], self.feature_values)


def test_a_signal_that_depends_on_the_replay_start_fails_warmup(stores, monkeypatch):
    monkeypatch.setitem(STRATEGIES, "all-history-mean", (AllHistoryMean, "All-history mean", {}))
    report = run_check(stores, "all-history-mean", params={})
    assert not any(report["truncation"].values()) and not any(report["perturbation"].values())
    assert report["warmup"]["first_mismatch"] and not report["passed"]
