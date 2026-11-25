"""Tests for Nobitex testnet-only Ed25519 dry-run adapter, dashboard live venue panel, and 1h catchup helper."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from gym.adapters.nobitex_testnet import (
    NOBITEX_TESTNET_BASE_URL,
    NobitexTestnetClient,
    build_limit_order_payload,
    build_oco_order_payload,
    build_order_cancel_payload,
    build_order_status_payload,
    build_stop_limit_order_payload,
    make_client_order_id,
    parse_nobitex_response,
    validate_api_scopes,
    validate_testnet_base_url,
    verify_nobitex_signature,
)
from gym.services.experiments.research_dashboard import generate_research_dashboard


def _ephemeral_ed25519() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    return (
        priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
    )


def test_nobitex_testnet_url_and_scope_guards() -> None:
    assert validate_testnet_base_url(NOBITEX_TESTNET_BASE_URL) == NOBITEX_TESTNET_BASE_URL
    with pytest.raises(ValueError, match="strictly restricted"):
        validate_testnet_base_url("https://apiv2.nobitex.ir")
    with pytest.raises(ValueError, match="strictly restricted"):
        validate_testnet_base_url("http://testnetapiv2.nobitex.ir")

    assert validate_api_scopes(["trade", "read"]) == ("READ", "TRADE")
    for banned in ("WITHDRAW", "DEPOSIT", "ADDRESS_BOOK", "OTP"):
        with pytest.raises(ValueError, match="Forbidden"):
            validate_api_scopes(["READ", banned])


def test_nobitex_ed25519_signing_and_dry_run_block() -> None:
    priv_b, pub_b = _ephemeral_ed25519()
    client = NobitexTestnetClient(
        scopes=("READ", "TRADE"),
        api_key="test-key-1",
        private_key_bytes=priv_b,
        dry_run=True,
    )
    cid = make_client_order_id("tgym", "BTCUSDT", "buy", 1764000000000)
    lim = build_limit_order_payload(
        side="buy", src_currency="btc", dst_currency="usdt", amount="0.01", price="85000", client_order_id=cid,
    )
    env_post = client.prepare_signed_request("POST", "/market/orders/add", lim, timestamp=1764000000)
    assert verify_nobitex_signature(pub_b, env_post["headers"], "POST", "/market/orders/add", env_post["raw_body"])
    assert not verify_nobitex_signature(pub_b, env_post["headers"], "POST", "/market/orders/add", env_post["raw_body"] + " ")

    env_get = client.prepare_signed_request("GET", "/market/orders/list?status=open", timestamp=1764000001)
    assert env_get["raw_body"] == ""
    assert verify_nobitex_signature(pub_b, env_get["headers"], "GET", "/market/orders/list?status=open", "")

    blocked = asyncio.run(client.send_signed_request("POST", "/market/orders/add", lim))
    assert not blocked.ok and blocked.error_code == "DRY_RUN_ONLY"

    ro_client = NobitexTestnetClient(scopes=("READ",), api_key="ro", private_key_bytes=priv_b, dry_run=True)
    with pytest.raises(PermissionError, match="TRADE"):
        ro_client.prepare_signed_request("POST", "/market/orders/add", lim)


def test_nobitex_oco_and_stop_limit_invariants_and_http200_failure_parser() -> None:
    buy_oco = build_oco_order_payload(
        side="buy", src_currency="btc", dst_currency="usdt",
        amount="0.01", price="42390", stop_price="42700", stop_limit_price="42715",
        reference_price="42500", client_order_id="cid-oco-buy",
    )
    assert buy_oco["mode"] == "oco" and buy_oco["stopLimitPrice"] == "42715"
    with pytest.raises(ValueError, match="Buy OCO"):
        build_oco_order_payload(
            side="buy", src_currency="btc", dst_currency="usdt",
            amount="0.01", price="42600", stop_price="42700", stop_limit_price="42715",
            reference_price="42500", client_order_id="bad-oco",
        )
    with pytest.raises(ValueError, match="Sell stop_limit"):
        build_stop_limit_order_payload(
            side="sell", src_currency="btc", dst_currency="usdt",
            amount="0.01", price="43100", stop_price="43000", client_order_id="bad-sl",
        )
    assert build_order_status_payload(client_order_id="c1") == {"clientOrderId": "c1"}
    assert build_order_cancel_payload(order_id=99) == {"status": "canceled", "order": 99}

    # HTTP 200 business failure must parse as ok=False
    failed = parse_nobitex_response(
        200, {"status": "failed", "code": "InvalidOrderPrice", "message": "Price Validation Failed", "clientOrderId": "c1"},
    )
    assert not failed.ok and failed.error_code == "InvalidOrderPrice" and failed.client_order_id == "c1"

    # HTTP 200 cancel race where order already filled
    cancel_race = parse_nobitex_response(
        200,
        {
            "status": "failed",
            "updatedStatus": "Done",
            "order": {"id": 5684, "type": "sell", "execution": "Limit", "market": "BTC-USDT", "status": "Done", "price": "85000", "amount": "0.01"},
        },
    )
    assert not cancel_race.ok and cancel_race.updated_status == "Done" and len(cancel_race.orders) == 1

    # OCO dual-order success response
    oco_ok = parse_nobitex_response(
        200,
        {
            "status": "ok",
            "orders": [
                {"id": 27, "type": "buy", "execution": "Limit", "market": "BTC-USDT", "status": "Active", "price": "42390", "amount": "0.01", "pairId": 28, "clientOrderId": "cid-oco-buy"},
                {"id": 28, "type": "buy", "execution": "StopLimit", "market": "BTC-USDT", "status": "Inactive", "price": "42715", "amount": "0.01", "pairId": 27, "clientOrderId": None},
            ],
        },
    )
    assert oco_ok.ok and len(oco_ok.orders) == 2 and oco_ok.orders[0].pair_id == 28


def test_dashboard_live_venue_panel_and_hourly_catchup_window(tmp_path: Path) -> None:
    mv_db = tmp_path / "mv.sqlite3"
    con = sqlite3.connect(mv_db)
    con.execute("CREATE TABLE venue_quotes (id INTEGER PRIMARY KEY, ts_avail TEXT, venue TEXT, symbol TEXT, bid REAL, ask REAL, spread_bps REAL)")
    con.execute("CREATE TABLE venue_liquidity_pools (id INTEGER PRIMARY KEY, ts_avail TEXT, venue TEXT, currency TEXT, apr_pct REAL, capacity REAL, filled_capacity REAL)")
    con.execute("CREATE TABLE venue_margin_ratios (id INTEGER PRIMARY KEY, ts_avail TEXT, venue TEXT, symbol TEXT, long_pct TEXT, short_pct TEXT)")
    con.execute("CREATE TABLE venue_fair_prices (id INTEGER PRIMARY KEY, ts_avail TEXT, venue TEXT, symbol TEXT, fair_price TEXT)")
    con.execute("INSERT INTO venue_quotes VALUES (1, '2026-11-25T12:00:00Z', 'nobitex', 'BTCUSDT', 90000, 90050, 5.55)")
    con.execute("INSERT INTO venue_quotes VALUES (2, '2026-11-25T12:00:00Z', 'wallex', 'BTCUSDT', 89990, 90120, 14.44)")
    con.execute("INSERT INTO venue_liquidity_pools VALUES (1, '2026-11-25T12:00:00Z', 'nobitex', 'USDT', 2.64, 7000000, 6580000)")
    con.execute("INSERT INTO venue_margin_ratios VALUES (1, '2026-11-25T12:00:00Z', 'wallex', 'BTCUSDT', '62.0', '38.0')")
    con.execute("INSERT INTO venue_fair_prices VALUES (1, '2026-11-25T12:00:00Z', 'wallex', 'BTCUSDT', '90025.0')")
    con.commit()
    con.close()

    v2_j = tmp_path / "v2.jsonl"
    v2_j.write_text(
        json.dumps({"as_of": "2026-11-25T12:00:00Z", "nobitex_margin_2x_eligible_triggers": ["SOLUSDT"], "live_idle_usdt_pool_apr_pct": 2.64}) + "\n",
        encoding="utf-8",
    )

    out_html = tmp_path / "dash.html"
    res = generate_research_dashboard(tmp_path, out_html, db_path=None, multi_venue_db=mv_db, v2_journal_path=v2_j)
    html = out_html.read_text(encoding="utf-8")
    assert res["live_venue_spreads"] == 1 and res["live_pools"] == 1
    assert res["live_margin_ratios"] == 1 and res["live_fair_prices"] == 1
    assert "c-live-venue" in html and "t-live-pools" in html and "t-live-ratios" in html
    assert "http://" not in html and "https://" not in html

    # Load script module to verify catchup window bounds
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "refresh_hourly_candles.py"
    spec = importlib.util.spec_from_file_location("refresh_hourly_candles", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    now = datetime(2026, 11, 25, 13, 0, tzinfo=UTC)
    s1, e1 = mod.compute_catchup_window(now - timedelta(days=8), now, lookback_hours=48, max_catchup_days=14)
    assert e1 == now and (now - s1) == timedelta(days=8, hours=2)
    s2, e2 = mod.compute_catchup_window(now - timedelta(days=30), now, lookback_hours=48, max_catchup_days=14)
    assert e2 == now and (now - s2) == timedelta(days=14)
    assert "PAXGUSDT" in mod.DEFAULT_HOURLY_SYMBOLS and "SLVONUSDT" in mod.DEFAULT_HOURLY_SYMBOLS
