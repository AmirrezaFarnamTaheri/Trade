"""Phase D item 35: saved empirical paper fractions are opt-in and never funded."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.run_store import save_run
from gym.domain.model import iso
from gym.domain.strategy import digest
from gym.services.fractional_sizing import load_fractional_report
from gym.services.paper import paper
from tests.support import START, market_db, quote_history


def _source(tmp_path):
    db = market_db(tmp_path, quote_history(n=320))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=40),
                    resolution="1min", params={"fast": 2, "slow": 3})
    finally:
        db.c.close()
    save_run(out, tmp_path / "runs")
    return out


def _report(tmp_path, source, *, cap="0.12", status="DESCRIPTIVE_ONLY"):
    record = {
        "schema": "fractional-sizing/2", "store": "demo", "synthetic": True,
        "status": status, "capped_fraction": cap,
        "run_id": source["run_id"], "source_outputs_digest": source["outputs_digest"],
        "source_test_to": source["inputs"]["to"],
        "source_config_hash": source["inputs"]["config_hash"],
        "independent_final_evidence": False, "funded_authority": False}
    key = digest(record)[:16]
    record["report_id"] = key
    save_run({"run_id": key, "report": record}, tmp_path / "runs" / "fractional_sizing")
    return key


def test_fractional_report_reference_requires_prior_native_provenance(tmp_path):
    """A source run later than the proposed replay cannot influence its sizing."""
    source = _source(tmp_path)
    key = _report(tmp_path, source)
    kwargs = {"root": tmp_path, "report_id": key, "store": "demo",
              "as_of": START + timedelta(hours=2), "strategy": "ema-trend",
              "params": {"fast": 2, "slow": 3}, "resolution": "1min",
              "symbols": ["BTCUSDT", "ETHUSDT"], "fee_rate": "0.001"}
    checked = load_fractional_report(**kwargs)
    assert checked["fraction"] == "0.12"
    assert checked["report_id"] == key
    assert checked["source_outputs_digest"] == source["outputs_digest"]
    with pytest.raises(ValueError):
        load_fractional_report(**{**kwargs, "as_of": START + timedelta(minutes=30)})
    with pytest.raises(ValueError):
        load_fractional_report(**{**kwargs, "params": {"fast": 3, "slow": 5}})
    with pytest.raises(ValueError):
        load_fractional_report(**{**kwargs, "fee_rate": "0.01"})


def test_fractional_report_rejects_unverified_or_nonpositive_cap(tmp_path):
    source = _source(tmp_path)
    for cap, status in (("0", "DESCRIPTIVE_ONLY"), ("0.15", "INSUFFICIENT_OOS_EVIDENCE")):
        key = _report(tmp_path, source, cap=cap, status=status)
        with pytest.raises(ValueError):
            load_fractional_report(tmp_path, key, store="demo",
                as_of=START + timedelta(hours=2), strategy="ema-trend",
                params={"fast": 2, "slow": 3}, resolution="1min",
                symbols=["BTCUSDT", "ETHUSDT"], fee_rate="0.001")
