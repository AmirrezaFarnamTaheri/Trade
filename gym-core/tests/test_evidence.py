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
    db = market_db(tmp_path, quote_history(n=2000))
    t0, t1 = START + timedelta(hours=1), START + timedelta(hours=4)
    out = paper(db, "BTCUSDT", t0, t1, resolution="1min", fast=2, slow=3, store="demo")
    diag = diagnostics(db, out)
    assert all(v["status"] == "PASS" for v in diag["checks"].values())
    assert [r["cost_multiplier"] for r in diag["cost_stress"]] == ["0", "1", "1.25", "2", "3"]
    assert diag["cost_stress"][1]["net"] == out["result"]["end"]["net"]
    assert set(diag["cost_stress"][2]["components"]) == {"spread", "fees", "latency_drift"}
    assert diag["warmup-stability"]["status"] == "PASS"
    assert diag["warmup-stability"]["prehistory_observations"] > 0
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


@pytest.mark.parametrize(("age", "status"), [(0, "CURRENT"), (120, "CURRENT"), (121, "STALE")])
def test_evidence_discloses_end_price_age(age, status):
    out = {
        "run_id": "fixture", "outputs_digest": "fixture", "baselines": {}, "warnings": [],
        "inputs": {"from": iso(START), "to": iso(START + timedelta(seconds=age)),
                   "store": "live", "cost": {}},
        "result": {"quote": "USDT", "orders": [], "end": {"mark_time": iso(START)}},
    }
    report = economic_report(out)
    assert report["valuation"] == {"status": status, "as_of": iso(START), "age_seconds": age}
    assert report["gate_eligible"] is False
    if status == "STALE":
        assert "stale" in report["primary_limitation"].lower()


@pytest.mark.parametrize(("mark_time", "status"), [(None, "UNAVAILABLE"), (iso(START + timedelta(seconds=1)), "INVALID")])
def test_evidence_rejects_missing_or_future_valuation(mark_time, status):
    out = {"run_id": "fixture", "outputs_digest": "fixture", "baselines": {}, "warnings": [],
           "inputs": {"from": iso(START), "to": iso(START), "store": "live", "cost": {}},
           "result": {"quote": "USDT", "orders": [], "end": {"mark_time": mark_time} if mark_time else None}}
    assert economic_report(out)["valuation"]["status"] == status
