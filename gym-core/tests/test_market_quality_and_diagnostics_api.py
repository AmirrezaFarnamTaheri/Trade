"""Market quality, clocks, raw-SQL provenance, fee/ratio parsers, and read-only diagnostics API (M002-M022, C008, U003-U019)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.domain.model import InstrumentId, TradeTick, now_utc
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
        # One normal trade (+250ms lag) and one backward-clock trade (-100ms).
        for seconds, delay, price, is_buy in ((0, 250, "100", False), (2, 1900, "101", True)):
            tick = dict(timestamp=(START + timedelta(seconds=seconds)).isoformat(), price=price, quantity="1", isBuyOrder=is_buy)
            received = START + timedelta(milliseconds=delay)
            frame = {"push": {"channel": "public:BTCUSDT@trade", "pub": {"data": tick}}}
            ref = writer.write("ws", json.dumps(frame), received)
            db.add_trade(TradeTick.wallex("BTCUSDT", tick, received), ref)
        writer.close()
        db.add_book_top(quote(START + timedelta(seconds=5), "100", "101"), ref)
        db.add_quality(START + timedelta(seconds=6), "BTCUSDT", "GAP", "test gap")
        db.c.execute("INSERT OR REPLACE INTO collector_publication VALUES(1, ?)", ((START + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),))
        db.c.commit()

        clocks = ingestion_clock_metrics(db, symbol="BTCUSDT")
        assert clocks["samples"] == 2 and clocks["backward_event_count"] == 1 and clocks["clock_skew_warning"] is True

        prov = verify_raw_sql_provenance(db, [tmp_path / "raw"], symbol="BTCUSDT")
        assert prov["status"] == "PASS" and prov["sample_verified"] is True and prov["references_checked"] == 3
        assert prov["qualified_for_replay"] is False
        assert prov["trade_rows_content_matched"] == 2
        db.c.execute("UPDATE trades SET price='999' WHERE price='101'")
        mismatch = verify_raw_sql_provenance(db, [tmp_path / "raw"], symbol="BTCUSDT")
        assert mismatch["status"] == "FAIL" and mismatch["broken"][0]["reason"] == "TRADE_CONTENT_MISMATCH"
        db.c.execute("UPDATE trades SET price='101' WHERE price='999'")
        empty = verify_raw_sql_provenance(db, [], symbol="ETHUSDT")
        assert empty["status"] == "NO_EVIDENCE" and empty["sample_verified"] is False
        db.add_book_top(replace(quote(START, "10", "11"), symbol="ETHUSDT"), "missing.jsonl.zst#1")
        quote_only = verify_raw_sql_provenance(db, [], symbol="ETHUSDT")
        assert quote_only["status"] == "FAIL" and quote_only["references_checked"] == 1
        db.add_book_top(replace(quote(START + timedelta(seconds=1), "10", "11"), symbol="ETHUSDT"),
                        ref.partition("#")[0] + "#999")
        invalid_ref = verify_raw_sql_provenance(db, [tmp_path / "raw"], symbol="ETHUSDT")
        assert any(row["reason"] == "MISSING_RAW_FRAME" for row in invalid_ref["broken"])

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


def test_raw_trade_receipts_match_rest_request_symbol_and_multiplicity(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    writer = SegmentWriter(tmp_path / "raw", db)
    try:
        row = dict(timestamp=START.isoformat(), price="100", quantity="2", isBuyOrder=True)
        ref = writer.write("rest:/v1/trades?symbol=BTCUSDT", json.dumps({"result": {"latestTrades": [row]}}), START)
        writer.close()
        tick = TradeTick.wallex("BTCUSDT", row, START)
        db.add_trade(tick, ref)
        roots = [tmp_path / "raw"]
        assert verify_raw_sql_provenance(db, roots)["trade_rows_content_matched"] == 1
        db.add_trade(tick, ref)
        assert verify_raw_sql_provenance(db, roots)["status"] == "FAIL"
        db.add_trade(replace(tick, symbol="ETHUSDT"), ref)
        assert verify_raw_sql_provenance(db, roots, symbol="ETHUSDT")["trade_rows_content_matched"] == 0
    finally:
        writer.close()
        db.c.close()


def test_replay_window_cli_matches_both_depth_sides_and_refuses_corruption(tmp_path, capsys):
    from gym.cli import main

    root = tmp_path / "live"
    db = MarketDB(root / "market.db")
    writer = SegmentWriter(root / "raw", db)
    collector = Collector(db, writer, ["BTCUSDT"], depth_levels=2)
    try:
        for topic, prices in (("buyDepth", ("98", "99")), ("sellDepth", ("101", "102"))):
            channel = f"orderbook:BTCUSDT@{topic}"
            data = {"message": [{"price": p, "quantity": "2"} for p in prices]}
            collector.handle_frame(json.dumps({"push": {"channel": channel, "pub": {"data": data}}}), START)
        collector.tick(START)
        writer.close()
        path = tmp_path / "window.json"
        path.write_text(json.dumps({"symbol": "BTCUSDT", "from": START.isoformat(), "to": (START + timedelta(seconds=1)).isoformat()}))
        cmd = ["--data", str(tmp_path), "research", "raw-replay-audit", str(path)]
        assert main(cmd) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["book_sides_matched"] == 2 and result["book_rows"] == 1 and result["verified"]
        db.c.execute("UPDATE book_top SET ask_ref=bid_ref")
        assert main(cmd) != 0
        assert json.loads(capsys.readouterr().out)["book_sides_matched"] == 1
        db.c.execute("UPDATE book_top SET bid_ref=NULL")
        assert main(cmd) != 0
        assert json.loads(capsys.readouterr().out)["broken"][0]["reason"] == "MISSING_OR_INVALID_REFERENCE"
    finally:
        writer.close()
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
    at = now_utc()
    db.upsert_instrument(InstrumentId.wallex("USDTTMN"), {}, {}, "test", at)
    db.add_book_top(replace(quote(at, "200000", "201000"), symbol="USDTTMN"), None)
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
            assert slo["backup_chronology"]["off_machine_status"] == "UNKNOWN"
            assert slo["backup_chronology"]["off_machine_backup_age_hours"] is None

            fx = await (await client.get("/api/fx-route?amount=100000&direction=TMN_TO_USDT", headers=headers)).json()
            assert fx["order_submitted"] is False and fx["funded_authority"] is False
            assert fx["direct_available"] and fx["direct_route"] == fx["routes"][0]
            assert fx["direct_route"]["route"] == "USDTTMN" and fx["saving_vs_direct_bps"] == 0

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


def test_catalog_and_rules_preserve_separate_receipt_timestamps_and_backup_chronology(tmp_path, monkeypatch):
    """M007 & O013: catalog/rules keep independent receipt times; off-machine backup age stays UNKNOWN (never 0)."""
    import json

    from gym.services import collector as collector_mod
    from gym.services.backup_status import receipt_chronology

    db = MarketDB(tmp_path / "market.db")
    seg = SegmentWriter(tmp_path / "raw", db)
    times = iter([START, START + timedelta(seconds=7), START + timedelta(seconds=8)])
    monkeypatch.setattr(collector_mod, "now_utc", lambda: next(times))
    col = Collector(db, seg, ["BTCUSDT"])

    async def fake_rest(_session, path, **_params):
        if path == collector_mod.CATALOG_PATH:
            return json.dumps({"result": {"markets": [{"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT", "is_spot": True}]}})
        return json.dumps({"result": {"symbols": {"BTCUSDT": {"stepSize": 6, "minQty": "0.0001", "minNotional": "5"}}}})

    monkeypatch.setattr(col, "rest_text", fake_rest)
    try:
        asyncio.run(col.load_catalog(object()))
        assert col.catalog_received_at == START
        assert col.rules_received_at == START + timedelta(seconds=7)
        assert col.catalog_received_at != col.rules_received_at

        chron = receipt_chronology(tmp_path, now=START + timedelta(hours=2))
        assert chron["state"] == "NO_RECEIPTS"
        assert chron["off_machine_status"] == "UNKNOWN"
        assert chron["off_machine_backup_age_hours"] is None
        assert chron["funded_authority"] is False
    finally:
        seg.close()
        db.c.close()


def test_cross_check_feeds_historical_causality_guard_and_fill_audit(tmp_path, monkeypatch):
    """M017, M018, M021, X013, X020: proxy/TLS bounds, normalized feed check, listing causality, guard & fill audit."""
    import aiohttp

    from gym.adapters import wallex
    from gym.domain.execution_qualification import (
        build_fill_audit_trail,
        model_latency_phases,
        venue_guard_transition_check,
    )
    from gym.services.collector import RestRate
    from gym.services.market_quality import (
        cross_check_feeds,
        data_eligibility_preflight,
        time_of_day_liquidity_profile,
    )

    # M017: proxy wiring and 429 rate-limit penalty/recovery bounds
    monkeypatch.setenv("GYM_WALLEX_PROXY", "http://127.0.0.1:8888")

    async def check_http():
        async with wallex.public_session() as sess:
            assert sess._default_proxy == "http://127.0.0.1:8888"
        rate = RestRate(requests_per_second=4)
        base_interval = rate.interval
        await rate.penalize()
        assert rate.interval == base_interval * 2
        for _ in range(10):
            await rate.penalize()
        assert rate.interval == 5.0  # bounded upper cap

        class FakeResp:
            status = 302
            request_info = None
            history = ()
            headers = {"Location": "https://evil.example"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        class FakeSession:
            def get(self, *_a, **_kw):
                return FakeResp()

        with pytest.raises(aiohttp.ClientResponseError) as error:
            await wallex.get_text(FakeSession(), "/v1/markets")
        assert error.value.message == "unexpected redirect"

    asyncio.run(check_http())

    # M018: normalized feed cross-check
    assert cross_check_feeds(
        primary_symbol="BTCTMN", secondary_symbol="BTCUSDT", primary_quote="TMN", secondary_quote="USDT",
        primary_price=Decimal("5000000000"), secondary_price=Decimal("90000"), primary_at=START, secondary_at=START,
    )["status"] == "INCOMPARABLE_QUOTE_CURRENCY"
    assert cross_check_feeds(
        primary_symbol="BTCUSDT", secondary_symbol="BTCUSDT", primary_quote="USDT", secondary_quote="USDT",
        primary_price=Decimal("90000"), secondary_price=Decimal("90010"),
        primary_at=START, secondary_at=START + timedelta(minutes=5),
    )["status"] == "CLOCK_MISMATCH"
    assert cross_check_feeds(
        primary_symbol="AAPLXUSDT", secondary_symbol="AAPL", primary_quote="USDT", secondary_quote="USDT",
        primary_price=Decimal("230"), secondary_price=Decimal("225"), primary_at=START, secondary_at=START,
        corporate_action_note="ex-dividend split reference",
    )["status"] == "CORPORATE_ACTION_DISCLOSED"
    assert cross_check_feeds(
        primary_symbol="BTCUSDT", secondary_symbol="BTCUSDT", primary_quote="USDT", secondary_quote="USDT",
        primary_price=Decimal("91000"), secondary_price=Decimal("90000"), primary_at=START, secondary_at=START,
    )["contradictory"] is True

    # M021 + U013 + U017: symbol listed in the future does NOT qualify as-of an earlier cutoff
    db = MarketDB(tmp_path / "market.db")
    try:
        inst = InstrumentId.wallex("NEWUSDT")
        db.upsert_instrument(inst, {}, {"stepSize": 4, "minQty": "1", "minNotional": "5", "isMarketTypeEnable": True},
                             "rest", START + timedelta(days=2))
        for i in range(4):
            db.add_book_top(replace(quote(START + timedelta(minutes=i), "10", "10.05"), symbol="NEWUSDT"), None)
        db.c.commit()
        pre_before = data_eligibility_preflight(db, "NEWUSDT", days=7, min_bars=3, now=START + timedelta(minutes=4))
        assert pre_before["status"] == "BLOCKED" and "NO_AS_OF_LISTING_OR_SPEC" in pre_before["blockers"]
        tod = time_of_day_liquidity_profile(db, "NEWUSDT", days=7, now=START + timedelta(minutes=5))
        assert tod["timezone"] == "Asia/Tehran" and tod["total_qualified_quotes"] == 4
    finally:
        db.c.close()

    # X013: venue guard transitions fail closed
    assert venue_guard_transition_check(
        reference_price=Decimal("100"), bid=Decimal("120"), ask=Decimal("121"), reference_age_s=5.0
    )["reasons"] == ["REFERENCE_DISCONTINUITY"]
    assert "MARKET_HALTED" in venue_guard_transition_check(
        reference_price=Decimal("100"), bid=Decimal("100"), ask=Decimal("101"), reference_age_s=5.0, halted=True
    )["reasons"]
    assert venue_guard_transition_check(
        reference_price=Decimal("100"), bid=Decimal("99.9"), ask=Decimal("100.1"), reference_age_s=5.0
    )["pass"] is True

    # X020: per-fill audit trail links decision, vintage, fee source, latency, and postings
    lat = model_latency_phases(START, receive_ms=10, publish_ms=20, decide_ms=5, send_ms=50, ack_ms=30)
    trail = build_fill_audit_trail(
        decision_at=START, symbol="BTCUSDT", side="BUY", order_type="LIMIT",
        requested_qty=Decimal("0.5"), filled_qty=Decimal("0.5"), fill_price=Decimal("100"),
        fee_rate=Decimal("0.001"), fee_source="rest:/v2/structured-fee", rule_vintage_at=START,
        latency_phases=lat, matched_trade_count=2, queue_ahead_remaining=Decimal("0"),
        cash_postings=[{"currency": "USDT", "amount": "-50.05"}],
    )
    assert trail["schema"] == "fill-audit/1" and trail["authenticated_venue_fill"] is False and trail["matched_trade_count"] == 2


def test_new_diagnostic_endpoints_liquidity_size_preflight_and_cost_lab(tmp_path):
    """U013, U014, U017, U025: token-gated read-only liquidity, size-preview, preflight, and cost-lab routes."""
    import json

    db = market_db(tmp_path, [quote(START + timedelta(seconds=i * 10), "100", "101") for i in range(5)])
    seg = SegmentWriter(tmp_path / "raw", db)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "abcdef0123456789"
    (runs_dir / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id,
        "inputs": {"symbol": "BTCUSDT", "cash": "1000"},
        "result": {"symbol": "BTCUSDT", "strategy": "ema-trend", "fills": 2,
                   "end": {"net": "25.00", "waterfall": {"fees": "-4.00", "spread": "-2.00"}}},
        "evidence": {"performance": {"max_drawdown_pct": "3.5"}},
    }), encoding="utf-8")
    tok = "diag-secret-token-9876543210"

    async def check():
        col = Collector(db, seg, ["BTCUSDT"], demo=True)
        app = make_app(col, RuleService(db), tok, runs_dir)
        async with TestClient(TestServer(app)) as client:
            for path in ("/api/liquidity-profile?symbol=BTCUSDT", "/api/size-preview?symbol=BTCUSDT&side=SELL&qty=0.5",
                         "/api/preflight?symbol=BTCUSDT", f"/api/cost-lab?run_id={run_id}"):
                assert (await client.get(path)).status == 403, path

            headers = {"X-Gym-Token": tok}
            liq = await (await client.get("/api/liquidity-profile?symbol=BTCUSDT&days=14", headers=headers)).json()
            assert liq["timezone"] == "Asia/Tehran" and liq["read_only"] is True

            sz = await (await client.get("/api/size-preview?symbol=BTCUSDT&side=SELL&qty=100", headers=headers)).json()
            assert sz["order_submitted"] is False and sz["funded_authority"] is False and sz["status"] in ("FULL", "PARTIAL", "UNAVAILABLE")

            pf = await (await client.get("/api/preflight?symbol=BTCUSDT&days=14&min_bars=5", headers=headers)).json()
            assert pf["read_only"] is True and pf["status"] in ("ELIGIBLE", "ELIGIBLE_WITH_WARNINGS", "BLOCKED")

            lab = await (await client.get(f"/api/cost-lab?run_id={run_id}", headers=headers)).json()
            assert lab["creates_selection_trial"] is False and lab["diagnostic_only"] is True and len(lab["scenarios"]) == 3
            assert Decimal(lab["scenarios"][2]["net_return"]) < Decimal(lab["scenarios"][0]["net_return"])

            assert (await client.get("/api/cost-lab?run_id=bad", headers=headers)).status == 400

    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
