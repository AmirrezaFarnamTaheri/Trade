"""Market quality, clocks, raw-SQL provenance, fee/ratio parsers, and read-only diagnostics API (M002-M022, C008, U003-U019)."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.domain.model import InstrumentId, TradeTick
from gym.services.collector import Collector
from gym.services.market_quality import (
    as_of_rule_index,
    feed_slo_report,
    ingestion_clock_metrics,
    parse_margin_ratio,
    parse_structured_fee,
    symbol_quality_calendar,
    verify_raw_sql_provenance,
)
from gym.services.rules import RuleService
from tests.support import START, market_db, quote


def test_ingestion_clocks_provenance_vintages_calendar_and_slo(tmp_path):
    """M002, M006, M008, M010, M011, M012, M019, M022, O021."""
    db = MarketDB(tmp_path / "market.db")
    try:
        inst = InstrumentId.wallex("BTCUSDT")
        db.upsert_instrument(inst, {}, {"stepSize": 6, "minQty": "0.0001"}, "rest", START)
        db.upsert_instrument(
            inst, {}, {"stepSize": 6, "minQty": "0.0001", "minNotional": "5", "isMarketTypeEnable": True},
            "rest", START + timedelta(minutes=5),
        )
        writer = SegmentWriter(tmp_path / "raw", db)
        ref = writer.write("ws", '{"ok":true}', START)
        writer.close()

        # One normal trade (+250ms lag) and one backward-clock trade (-100ms).
        db.add_trade(TradeTick("BTCUSDT", START, START + timedelta(milliseconds=250), Decimal("100"), Decimal("1"), "BUY"), ref)
        db.add_trade(TradeTick("BTCUSDT", START + timedelta(seconds=2), START + timedelta(seconds=1, milliseconds=900),
                               Decimal("101"), Decimal("1"), "SELL"), ref)
        db.add_book_top(quote(START + timedelta(seconds=5), "100", "101"), ref)
        db.add_quality(START + timedelta(seconds=6), "BTCUSDT", "GAP", "test gap")
        db.c.execute("INSERT OR REPLACE INTO collector_publication VALUES(1, ?)", ((START + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),))
        db.c.commit()

        clocks = ingestion_clock_metrics(db, symbol="BTCUSDT")
        assert clocks["samples"] == 2 and clocks["backward_event_count"] == 1 and clocks["clock_skew_warning"] is True

        prov = verify_raw_sql_provenance(db, [tmp_path / "raw"], symbol="BTCUSDT")
        assert prov["status"] == "PASS" and prov["qualified_for_replay"] is True and prov["references_checked"] == 1

        # Corrupt the archived segment file -> provenance verifier fails closed (M006).
        seg_file = next((tmp_path / "raw").rglob("*.jsonl.zst"))
        seg_file.write_bytes(b"corrupted")
        bad_prov = verify_raw_sql_provenance(db, [tmp_path / "raw"], symbol="BTCUSDT")
        assert bad_prov["status"] == "FAIL" and bad_prov["broken"][0]["reason"] == "DIGEST_MISMATCH"

        vintages = as_of_rule_index(db, "BTCUSDT")
        assert vintages["vintage_count"] == 2
        assert vintages["vintages"][0]["complete"] is False and "minNotional" in vintages["vintages"][0]["missing_fields"]
        assert vintages["vintages"][1]["complete"] is True

        cal = symbol_quality_calendar(db, "BTCUSDT", days=3, now=START + timedelta(seconds=30))
        assert cal["freshness_status"] == "FRESH"
        today_entry = cal["calendar"][-1]
        assert today_entry["quotes"] == 1 and today_entry["trades"] == 2 and today_entry["completeness_status"] == "PARTIAL_GAPPED"

        slo = feed_slo_report(db, tmp_path, now=START + timedelta(seconds=30))
        assert slo["status"] == "WITHIN_SLO" and slo["breaches"] == []
    finally:
        db.c.close()


def test_structured_fee_and_public_margin_ratio_parsers():
    """M009 & C008: parse Wallex /v2/structured-fee and /public/ratio/{market} cleanly."""
    fee_v = parse_structured_fee(
        {"result": {"USDT": [{"level": 1, "maker_fee": "0.001", "taker_fee": "0.0013"}]}},
        fetched_at=START,
    )
    assert fee_v["groups"]["USDT"][0] == {"level": 1, "maker": "0.001", "taker": "0.0013"}

    with pytest.raises(ValueError, match="out of"):
        parse_structured_fee({"result": {"USDT": [{"maker_fee": "1.2", "taker_fee": "0.1"}]}}, fetched_at=START)

    ratio = parse_margin_ratio("BTCUSDT", {"result": {"long": "0.62", "short": "0.38"}}, fetched_at=START)
    assert ratio["long_ratio"] == "0.62" and ratio["account_borrow_eligibility_established"] is False


def test_diagnostics_api_routes_enforce_token_and_return_read_only_payloads(tmp_path):
    """U003, U008, U011, U012, U015, U019: new diagnostic routes are token-gated and strictly read-only."""
    db = market_db(tmp_path, [quote(START, "100", "101")])
    seg = SegmentWriter(tmp_path / "raw", db)
    tok = "diag-secret-token-1234567890"

    async def check():
        col = Collector(db, seg, ["BTCUSDT"], demo=True)
        app = make_app(col, RuleService(db), tok, tmp_path / "runs")
        async with TestClient(TestServer(app)) as client:
            for path in ("/api/quality-calendar?symbol=BTCUSDT", "/api/slo",
                         "/api/fx-route?amount=100000&direction=TMN_TO_USDT", "/api/action-registry"):
                assert (await client.get(path)).status == 403, path

            headers = {"X-Gym-Token": tok}
            qc = await (await client.get("/api/quality-calendar?symbol=BTCUSDT&days=7", headers=headers)).json()
            assert qc["read_only"] is True and qc["funded_authority"] is False and qc["calendar"]["days"] == 7

            slo = await (await client.get("/api/slo", headers=headers)).json()
            assert slo["read_only"] is True and "breaches" in slo["slo"] and isinstance(slo["attention"], list)

            fx = await (await client.get("/api/fx-route?amount=100000&direction=TMN_TO_USDT", headers=headers)).json()
            assert fx["order_submitted"] is False and fx["funded_authority"] is False

            reg = await (await client.get("/api/action-registry", headers=headers)).json()
            assert reg["count"] > 0 and reg["arbitrary_subprocess"] is False and reg["funded_authority"] is False

            # Malformed symbol / amount return 400 cleanly.
            assert (await client.get("/api/quality-calendar?symbol=bad!sym", headers=headers)).status == 400
            assert (await client.get("/api/fx-route?amount=-5&direction=TMN_TO_USDT", headers=headers)).status == 400

    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
