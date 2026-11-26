"""Tests for Level 3 passive cancel/replace + Wallex structured fees and Level 4 governance + e-process upgrades."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.domain.execution_qualification import simulate_passive_cancel_replace
from gym.domain.model import TradeTick
from gym.services.cost_defaults import calibrated_cost, published_structured_fees
from gym.services.evidence import evidence


def test_passive_cancel_replace_models_adverse_race_fills_and_requotes():
    t0 = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)
    trades = [
        # During leg 0 cancel-in-flight race [t0+5.0s, t0+5.25s), a sell print hits old bid 100.
        TradeTick("BTCUSDT", t0 + timedelta(seconds=5, milliseconds=100),
                  t0 + timedelta(seconds=5, milliseconds=120), Decimal("100"), Decimal("0.4"), "SELL"),
        # After leg 1 is active at t0+5.25s with lower bid 99, a sell print fills the remaining 0.6.
        TradeTick("BTCUSDT", t0 + timedelta(seconds=7),
                  t0 + timedelta(seconds=7, milliseconds=50), Decimal("99"), Decimal("1.0"), "SELL"),
    ]
    plan = [
        {"sent_at": t0, "limit_price": Decimal("100"), "queue_ahead": Decimal("0"), "best_opposite_price": Decimal("101")},
        {"sent_at": t0 + timedelta(seconds=5), "limit_price": Decimal("99"), "queue_ahead": Decimal("0"), "best_opposite_price": Decimal("100")},
    ]
    report = simulate_passive_cancel_replace(
        side="BUY",
        total_qty=Decimal("1.0"),
        quotes_plan=plan,
        trades=trades,
        maker_fee_rate=Decimal("0.001"),
        send_latency=timedelta(milliseconds=250),
        cancel_latency=timedelta(milliseconds=250),
    )
    assert report["model"] == "passive-cancel-replace/1"
    assert report["status"] == "FILLED"
    assert report["filled_qty"] == "1.0"
    assert report["remaining_qty"] == "0.0"
    assert report["adverse_race_filled_qty"] == "0.4"
    assert Decimal(report["gross_quote"]) == Decimal("0.4") * Decimal("100") + Decimal("0.6") * Decimal("99")
    assert Decimal(report["maker_fee_quote"]) == Decimal(report["gross_quote"]) * Decimal("0.001")
    assert report["authenticated_settlement"] is False
    assert len(report["legs"]) == 2


def test_published_structured_fees_distinguish_tmn_and_usdt_maker_taker(tmp_path):
    now = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
    tmn = calibrated_cost(tmp_path, "BTCTMN", order_type="limit", now=now, use_published_fees=True)
    usdt = calibrated_cost(tmp_path, "BTCUSDT", order_type="limit", now=now, use_published_fees=True)
    assert tmn.maker_fee == Decimal("0.0025") and tmn.fee_rate == Decimal("0.0030")
    assert usdt.maker_fee == Decimal("0.0010") and usdt.fee_rate == Decimal("0.0013")
    assert tmn.calibration["fee_source"] == "PUBLISHED_STRUCTURED_FEE_L1"

    # A fresh structured_fees.json vintage overrides the hardcoded Level-1 table.
    vintage = {
        "schema": "structured-fee-vintage/1",
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "groups": {
            "TMN": [{"level": 1, "maker": "0.0020", "taker": "0.0028"}],
            "USDT": [{"level": 1, "maker": "0.0008", "taker": "0.0012"}],
        },
    }
    (tmp_path / "structured_fees.json").write_text(json.dumps(vintage), encoding="utf-8")
    maker, taker, _, source = published_structured_fees(tmp_path, "BTCTMN", now)
    assert maker == Decimal("0.0020") and taker == Decimal("0.0028") and source == "PUBLIC_STRUCTURED_FEE_VINTAGE"

    # Also verify live Wallex nested {"levels": [...]} payload shape parses cleanly.
    from gym.services.market_quality import parse_structured_fee

    parsed = parse_structured_fee(
        {
            "result": {
                "TMN": {"currency": "TMN", "levels": [{"threshold": 0, "name": "L1", "maker_fee": 0.0025, "taker_fee": 0.003}]},
                "USDT": {"currency": "USDT", "levels": [{"threshold": 0, "name": "L1", "maker_fee": 0.001, "taker_fee": 0.0013}]},
            }
        },
        fetched_at=now,
    )
    assert parsed["groups"]["TMN"][0]["maker"] == "0.0025"
    assert parsed["groups"]["USDT"][0]["taker"] == "0.0013"


def test_evidence_unblocks_background_monitors_and_computes_forward_e_process(tmp_path):
    alloc = tmp_path / "allocation"
    alloc.mkdir()
    # 7 consecutive rising days + 1 gap day (Nov 20 skipped -> gap must not invent zero return).
    rows = []
    eq = Decimal("1000")
    for idx, day in enumerate(["2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-21"]):
        eq = eq + Decimal(idx * 5)
        rows.append({
            "symbol": "BTCUSDT",
            "day": f"{day}T00:00:00.000000Z",
            "at": f"{day}T01:00:00Z",
            "status": "READY",
            "equity": str(eq),
            "holdings": {"base": "0", "quote": str(eq)},
            "decision": {"close": 65000 + idx * 100},
        })
    (alloc / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    ev = evidence(tmp_path)
    budget = ev["trial_budget"]
    assert budget["limit"] == 2
    assert budget["background_monitors_open"] == 2
    assert budget["active"] == 0
    assert budget["remaining"] == 2
    eproc = ev["forward"]["e_process"]
    assert eproc["schema"] == "sequential-e-process/1"
    # 7 consecutive days yield 6 adjacent daily returns; the 2-day jump (19->21) is excluded.
    assert eproc["observations"] == 6
    assert eproc["final_e_value"] >= 1.0
