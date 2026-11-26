"""Causal order timing, fees and unsettled holdings in the fixed-input rank study."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId, iso
from gym.domain.sim import CostModel
from scripts.whole_market_panel import market_panel
from scripts.whole_market_rank_study import rank_study, read_panel
from tests.support import START, market_db, quote


@pytest.mark.parametrize("exit_receipt", [True, False])
@pytest.mark.parametrize("removed_after_seconds", [None, 1, 30])
def test_rank_study_books_fees_and_preserves_close_only_inventory(tmp_path, exit_receipt, removed_after_seconds):
    ticks = [quote(START + timedelta(seconds=offset), bid, ask)
             for offset, bid, ask in [(-62, "99", "101"), (-2, "109", "111"), (2, "109", "111"), (58, "119", "121")]]
    if exit_receipt:
        ticks.append(quote(START + timedelta(seconds=62), "119", "121"))
    db = market_db(tmp_path, ticks)
    db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {}, {"is_spot": True}, "fixture", ticks[0].ts_avail)
    if removed_after_seconds is not None:
        db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {}, {"is_spot": False}, "fixture",
                             START + timedelta(seconds=removed_after_seconds))
    try:
        header, *panel = market_panel(db, START - timedelta(minutes=2), START + timedelta(minutes=2),
                                      step_seconds=60, age_seconds=5)
        file = tmp_path / "panel.jsonl"
        file.write_text("\n".join(json.dumps(row) for row in [header, *panel]) + "\n", encoding="utf-8")
        header, panel = read_panel(file)
        cost = CostModel(fee_rate=Decimal("0.01"), max_wait=timedelta(seconds=10), max_participation=Decimal(1))
        report = rank_study(db, header, panel, top_n=1, clips={"USDT": Decimal(111)}, seed=1, cost=cost)
        block, = [row for row in report["blocks"] if row["outcomes_by_symbol"]]
        fill = block["outcomes_by_symbol"]["BTCUSDT"]
        if removed_after_seconds == 1:
            assert fill["state"] == "ENTRY_NONFILL" and fill["reason"] == "SPOT_WINDOW_ENDED"
            return
        assert fill["entry"]["fill_time"] == iso(START + timedelta(seconds=2))
        if exit_receipt:
            assert fill["state"] == "SETTLED"
            assert fill["exit"]["fill_time"] == iso(START + timedelta(seconds=62))
            assert fill["pnl"] == Decimal("5.6319")
            assert report["paired_blocks_with_fills"] == 1
        else:
            assert fill["state"] == "UNSCORED_RESIDUAL"
            assert fill["remaining"] == Decimal("0.99")
            assert report["paired_blocks"] == 0
        file.write_text(file.read_text(encoding="utf-8").replace('"119"', '"118"'), encoding="utf-8")
        with pytest.raises(ValueError, match="slice_digest mismatch"):
            read_panel(file)
    finally:
        db.c.close()
