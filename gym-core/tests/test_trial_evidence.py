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
| alpha-reversion | 2026-11-13 | A beats B. | Candles. | Mark one. | **FAIL** (2026-11-14). Best 0.001. |
| beta-trend | 2026-11-14 | C beats D. | Quotes. | Mark two. | **PASS, narrowly** (2026-11-14). 0.917. |
| gamma-carry | 2026-11-15 | E beats F. | Dailies. | Mark three. | |
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
    log = TRIAL_LOG.read_text(encoding="utf-8")
    registry = log.split("| --- |", 1)[1].split("\n\n", 1)[0]
    lines = [line for line in registry.splitlines()[1:] if line.startswith("| ")]
    assert len(rows) == len(lines) >= 14 and all(row["verdict"] != "OPEN" for row in rows[:14])
    assert rows[5]["id"] == "btc-daily-trend" and rows[5]["verdict"] == "NARROW_PASS"


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


def test_programme_score_adjusts_the_best_result_for_everything_tried():
    from gym.services.evidence import programme
    rows = [{"id": "a", "verdict": "NARROW_PASS", "probability": 0.95},
            {"id": "b", "verdict": "FAIL", "probability": 0.50},
            {"id": "c", "verdict": "FAIL", "probability": None},
            {"id": "d", "verdict": "OPEN", "probability": None}]
    assert programme(rows) == {"completed": 3, "best": "a", "best_probability": 0.95, "best_q": 0.15}
    assert programme([{"id": "x", "verdict": "OPEN", "probability": None}]) is None


def test_the_last_stage_reached_supplies_the_probability():
    from gym.services.evidence import _final_probability
    assert _final_probability("**FAIL**: deflated 0.994; held out probability 0.586.") == 0.586
    assert _final_probability("**FAIL** on ranking, deflated 0.723; not scored.") == 0.723
    assert _final_probability("**FAIL**: no market met every condition.") is None


def test_the_mix_record_reports_equity_from_1000_usdt_and_the_invested_share(tmp_path):
    from gym.services.evidence import forward_mix
    (tmp_path / "allocation").mkdir()
    rows = [{"day": "2026-11-17T00:00:00Z", "at": "2026-11-18T00:15:00Z", "status": "READY", "equity": "990", "usdt": "396"},
            {"day": "2026-11-18T00:00:00Z", "at": "2026-11-19T00:15:00Z", "status": "READY", "equity": "1010", "usdt": "404"}]
    (tmp_path / "allocation/mix-journal.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    assert forward_mix(tmp_path) == {"started": "2026-11-17", "latest": "2026-11-19T00:15:00Z", "days": 2,
                                     "equity": "1010.00", "net_pct": "1.00", "invested_pct": "60.0"}
    assert forward_mix(tmp_path / "missing") is None
