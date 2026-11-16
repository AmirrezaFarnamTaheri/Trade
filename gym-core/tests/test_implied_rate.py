"""T10's arithmetic: the gap to the implied rate, acting one close after the signal, cost on both sides."""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("implied_rate", Path(__file__).parents[1] / "scripts/implied_rate.py")
ir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ir)


def rows(prices, implied=100.0, start=datetime(2025, 1, 1, tzinfo=UTC)):
    stamps = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S.000000Z") for i in range(len(prices))]
    return ir.gaps(dict(zip(stamps, prices, strict=True)), dict.fromkeys(stamps, implied * 50_000.0), dict.fromkeys(stamps, 50_000.0))


def test_a_spike_is_sold_at_the_next_close_and_bought_back_one_close_after_the_gap_closes():
    prices = [100.0] * 30 + [103.0, 102.0, 100.0, 99.0, 100.0]  # signal at 103, sell at 102; gap gone at 99, buy at 100
    found = ir.trades(rows(prices), 24, 0.01, 0.0015)
    assert len(found) == 1 and found[0][0].startswith("2025-01-02T07")
    assert found[0][1] == pytest.approx(102 / 100 - 1)
    assert found[0][2] == pytest.approx(1.02 * (1 - 0.0015) ** 2 - 1)
    assert found[0][3].startswith("2025-01-02T10")


def test_a_position_is_closed_after_a_day_even_if_the_gap_stays_open():
    prices = [100.0] * 30 + [103.0] + [104.0] * 40
    found = ir.trades(rows(prices), 72, 0.01, 0.0)
    assert found[0][1] == pytest.approx(0.0)  # sold at 104, bought back at 104 a day later


def test_a_move_shared_with_the_implied_rate_is_not_a_signal():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    stamps = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S.000000Z") for i in range(60)]
    price = {at: 100.0 * (1.05 if i >= 30 else 1.0) for i, at in enumerate(stamps)}
    shared = ir.gaps(price, {at: value * 50_000 for at, value in price.items()}, dict.fromkeys(stamps, 50_000.0))
    assert ir.trades(shared, 24, 0.005, 0.0015) == []


def test_the_decision_uses_nothing_after_its_own_close():
    base = [100.0] * 30 + [103.0, 102.0, 100.0, 99.0, 100.0]
    calm, wild = ir.trades(rows([*base, 100.0, 100.0]), 24, 0.01, 0.0), ir.trades(rows([*base, 200.0, 300.0]), 24, 0.01, 0.0)
    assert calm[0] == wild[0] and len(calm) == 1


def test_an_entry_before_the_split_cannot_import_its_later_exit_into_ranking(monkeypatch, capsys):
    start = datetime(2025, 12, 30, tzinfo=UTC)
    observations = rows([100.0] * 40 + [103.0, 102.0] + [104.0] * 35, start=start)
    found = ir.trades(observations, 24, 0.01, ir.COST)
    assert found[0][0] < ir.SPLIT <= found[0][3]
    original = ir.trades
    inspected = []

    def ranking_only(data, *args):
        assert all(row[0] < ir.SPLIT for row in data)
        inspected.append(len(data))
        return original(data, *args)

    monkeypatch.setattr(ir, "trades", ranking_only)
    assert ir.verdict(observations) is False
    assert len(inspected) == len(ir.HOURS) * len(ir.THRESHOLDS)
    assert "on 0 trades" in capsys.readouterr().out
