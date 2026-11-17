"""The workspace's answer panel reads the trial log itself, and a missing log is said, not guessed."""
import json

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.evidence import TRIAL_LOG, evidence, trials
from gym.services.rules import RuleService
from tests.support import market_db, quote_history

LOG = """| ID | Registered | Hypothesis | Data | Pass mark | Result |
| --- | --- | --- | --- | --- | --- |
| T1 | 2026-11-13 | A beats B. | Candles. | Mark one. | **FAIL** (2026-11-14). Best 0.001. |
| T2 | 2026-11-14 | C beats D. | Quotes. | Mark two. | **PASS, narrowly** (2026-11-14). 0.917. |
| T3 | 2026-11-15 | E beats F. | Dailies. | Mark three. | |
"""


def test_verdicts_come_from_the_result_column_and_an_unrun_trial_is_open(tmp_path):
    path = tmp_path / "trial-log.md"
    path.write_text(LOG, encoding="utf-8")
    value = evidence(None, path)
    assert [row["verdict"] for row in value["trials"]] == ["FAIL", "NARROW_PASS", "OPEN"]
    assert value["tally"] == {"registered": 3, "FAIL": 1, "NARROW_PASS": 1, "PASS": 0, "OPEN": 1}
    assert value["forward"] is None and value["funded_authority"] is False
    assert evidence(None, tmp_path / "absent.md")["state"] == "NO_TRIAL_LOG"


def test_the_real_trial_log_parses_every_registered_row():
    rows = trials()
    lines = [line for line in TRIAL_LOG.read_text(encoding="utf-8").splitlines() if line.startswith("| T")]
    assert len(rows) == len(lines) >= 9 and all(row["verdict"] != "OPEN" for row in rows[:8])


def test_forward_record_counts_days_missing_days_fees_and_the_hold_comparison(tmp_path):
    (tmp_path / "allocation").mkdir()
    rows = [{"at": "2026-11-14T15:03:55Z", "day": "2026-11-13T00:00:00Z", "symbol": "BTCUSDT", "status": "READY",
             "equity": "1000.0", "holdings": {"base": "0", "quote": "1000"}, "decision": {"trade": False, "close": 100}},
            {"at": "2026-11-15T08:02:36Z", "day": "2026-11-14T00:00:00Z", "symbol": "BTCUSDT", "status": "NO_QUOTE",
             "equity": "1000.0", "holdings": {"base": "0", "quote": "1000"}, "decision": {"trade": True, "close": 104}},
            {"at": "2026-11-17T08:02:36Z", "day": "2026-11-16T00:00:00Z", "symbol": "BTCUSDT", "status": "READY",
             "equity": "1003.5", "holdings": {"base": "0.01", "quote": "340"}, "decision": {"trade": True, "close": 110},
             "fill": {"side": "BUY", "qty": "0.01", "price": "66000", "fee": "0.66"}}]
    (tmp_path / "allocation/journal.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    assert evidence(tmp_path, tmp_path / "none.md")["forward"] == {
        "symbol": "BTCUSDT", "started": "2026-11-14T15:03:55Z", "latest": "2026-11-17T08:02:36Z", "latest_day": "2026-11-16",
        "days": 3, "missing_days": 1, "start_equity": "1000.0", "equity": "1003.5", "net": "3.5", "hold_net": "100.00",
        "fees": "0.66", "in_market": True, "trades": 1, "withheld": 1}


def test_forward_net_keeps_all_decimal_places(tmp_path):
    (tmp_path / "allocation").mkdir()
    rows = [{"at": "2026-11-14T00:00:00Z", "symbol": "BTCUSDT",
             "equity": "10000000000000000000000000000.000000000000000001",
             "holdings": {"base": "0"}, "decision": {}, "status": "READY"},
            {"at": "2026-11-15T00:00:00Z", "symbol": "BTCUSDT",
             "equity": "10000000000000000000000000000.000000000000000003",
             "holdings": {"base": "0.000000000000000000000000000001"}, "decision": {}, "status": "READY"}]
    (tmp_path / "allocation/journal.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    value = evidence(tmp_path, tmp_path / "none.md")["forward"]
    assert value["net"] == "0.000000000000000002" and value["in_market"] is True


def test_evidence_api_needs_the_session_token(tmp_path):
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)

    async def check():
        col = Collector(db, seg, ["BTCUSDT"])
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            assert (await client.get("/api/evidence")).status == 403
            response = await client.get("/api/evidence", headers={"X-Gym-Token": "tok"})
            value = await response.json()
            assert response.status == 200 and value["state"] == "READY" and value["forward"] is None

    import asyncio
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
