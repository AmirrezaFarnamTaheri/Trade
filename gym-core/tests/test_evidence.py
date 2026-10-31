"""Outcome maturity, diagnostic results and capital-claim restrictions."""
import json
from datetime import timedelta

import pytest
from gym.adapters.run_store import record_decision, run_path
from gym.domain.model import iso
from gym.services.diagnostics import diagnostics, first_divergence
from gym.services.reports import economic_report
from gym.services.paper import paper
from gym.services.session import outcome_marks
from tests.support import START, market_db, quote, quote_history




def test_marks_do_not_mature_early():
    decisions = [{"t": iso(START)}]
    rows = [quote(START + timedelta(minutes=16), "100", "101"), quote(START + timedelta(minutes=65), "105", "106")]
    outcome_marks(decisions, rows, START + timedelta(minutes=70))
    m = decisions[0]["marks"]
    assert m["15"]["status"] == "MATURE"
    assert m["60"]["status"] == "OBSERVED_AFTER_GAP" and m["60"]["delay_s"] == 300
    assert m["240"]["status"] == "PENDING"
    outcome_marks(decisions, [], START + timedelta(hours=5))
    assert decisions[0]["marks"]["240"]["status"] == "MISSING"


def test_diagnostics_report_and_demo_capital_guard(tmp_path):
    db = market_db(tmp_path, quote_history(n=1500))
    out = paper(db, "BTCUSDT", START, START + timedelta(hours=4), resolution="1min", fast=2, slow=3, store="demo")
    diag = diagnostics(db, out)
    assert all(v["status"] == "PASS" for v in diag["checks"].values())
    assert [r["fee_multiplier"] for r in diag["fee_stress"]] == ["0", "1", "1.25", "2", "3"]
    assert diag["warmup-stability"]["status"] == "NOT_RUN"
    report = economic_report(out, diag)
    assert report["claim_ceiling"] == "NONE" and not report["gate_eligible"]
    with pytest.raises(ValueError):
        record_decision(tmp_path, out, "EXPERIMENTAL", "1", "USDT", "test", START)
    with pytest.raises(ValueError):
        record_decision(tmp_path, out, "VALIDATED", "0", "USDT", "test", START)
    p = record_decision(tmp_path, out, "NONE", "0", "USDT", "insufficient evidence", START)
    assert json.loads(p.read_text())["permission"] == "RECORD_ONLY_NOT_EXECUTION_AUTHORITY"
    with pytest.raises(FileExistsError):
        record_decision(tmp_path, out, "NONE", "0", "USDT", "insufficient evidence", START)
    assert first_divergence([{"t":"t", "action":"HOLD"}], [{"action":"BUY_REQUEST"}])["field"] == "action"
    for rid in ("../secret", "A" * 16, "f" * 17):
        with pytest.raises(ValueError):
            run_path(tmp_path, rid)
