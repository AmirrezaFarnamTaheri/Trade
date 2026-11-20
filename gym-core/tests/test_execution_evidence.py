from datetime import timedelta

from gym.domain.model import InstrumentId, iso
from gym.services.data_portal import DataPortal
from gym.services.execution_evidence import historical_execution_evidence
from tests.support import START, market_db


def test_historical_audit_checks_each_fill_against_its_metadata_vintage(tmp_path):
    db = market_db(tmp_path, [])
    later = START + timedelta(hours=1)
    try:
        db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {},
                             {"stepSize": 6, "minNotional": "10"}, "test", START)
        db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {},
                             {"stepSize": 6, "minNotional": "10", "tickSize": "0.01",
                              "minQty": "0.001", "isMarketTypeEnable": True}, "test", later)
        record = {"inputs": {"symbol": "BTCUSDT", "rules_mode": "point-in-time", "store": "live"},
                  "result": {"orders": [{"ref": str(i), "status": "FILLED", "fill_time": iso(at)}
                                        for i, at in enumerate((START, later))]}}
        report = historical_execution_evidence(DataPortal(db), record)
        first, last = report["fills"]
        assert report["status"] == "UNQUALIFIED"
        assert "tickSize" in first["missing"] and "tickSize" not in last["missing"]
        assert last["missing"] == ["verified_account_fee", "verified_venue_status"]
        assert first["metadata_digest"] != last["metadata_digest"]
    finally:
        db.c.close()
