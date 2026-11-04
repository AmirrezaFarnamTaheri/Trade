"""Run identity includes independently consumed baseline and valuation evidence."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.domain.model import iso
from gym.services.paper import paper
from tests.support import START, market_db, quote_history


@pytest.mark.parametrize("dependency", ["baseline", "fx"])
def test_auxiliary_evidence_changes_run_identity(tmp_path, dependency):
    symbol, auxiliary = ("ETHUSDT", "BTCUSDT") if dependency == "baseline" else ("BTCTMN", "USDTTMN")
    db = market_db(tmp_path, quote_history(n=100, sym=symbol) + quote_history(n=100, sym=auxiliary))
    start, end = START + timedelta(seconds=1), START + timedelta(seconds=1000)
    try:
        before = paper(db, symbol, start, end, resolution="1min", fast=1, slow=2)
        for top in quote_history(n=100, sym=auxiliary):
            if dependency == "baseline" and top.ts_avail < START + timedelta(seconds=500):
                continue
            if dependency == "fx" and top.ts_avail != START:
                continue
            db.c.execute("UPDATE book_top SET bid=?,ask=? WHERE instrument_id=? AND ts_avail=?",
                         (str(top.bid * Decimal("1.2")), str(top.ask * Decimal("1.2")),
                          "wallex:" + auxiliary, iso(top.ts_avail)))
        after = paper(db, symbol, start, end, resolution="1min", fast=1, slow=2)
        assert before["inputs"]["data"] == after["inputs"]["data"]
        assert before["inputs"]["snapshots"] == after["inputs"]["snapshots"]
        assert before["outputs_digest"] != after["outputs_digest"]
        assert before["run_id"] != after["run_id"]
        assert save_run(before, tmp_path / "runs") != save_run(after, tmp_path / "runs")
        assert after == paper(db, symbol, start, end, resolution="1min", fast=1, slow=2)
    finally:
        db.c.close()
