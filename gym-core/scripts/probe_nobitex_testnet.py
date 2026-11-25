"""Offline & public-read dry-run verification harness for Nobitex Testnet Ed25519 execution primitives.

Strictly pinned to https://testnetapiv2.nobitex.ir with dry_run=True by default (DISARMED).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

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
    verify_nobitex_signature,
)


def run_offline_dry_run_suite() -> dict:
    """Verify Ed25519 signing, OCO/StopLimit/Limit/Cancel envelopes, and HTTP-200 failure parsing offline."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    client = NobitexTestnetClient(
        base_url=NOBITEX_TESTNET_BASE_URL,
        scopes=("READ", "TRADE"),
        api_key="testnet-ephemeral-key",
        private_key_bytes=priv_bytes,
        dry_run=True,
    )
    ts_ms = int(time.time() * 1000)
    cid_lim = make_client_order_id("tgym", "BTCUSDT", "buy", ts_ms)
    cid_oco = make_client_order_id("tgym", "BTCUSDT", "sell", ts_ms + 1)

    envelopes = {
        "limit": client.prepare_signed_request(
            "POST",
            "/market/orders/add",
            build_limit_order_payload(
                side="buy", src_currency="btc", dst_currency="usdt",
                amount="0.001", price="85000", client_order_id=cid_lim,
            ),
        ),
        "stop_limit": client.prepare_signed_request(
            "POST",
            "/market/orders/add",
            build_stop_limit_order_payload(
                side="sell", src_currency="btc", dst_currency="usdt",
                amount="0.001", price="82800", stop_price="83000", client_order_id=cid_lim + "sl",
            ),
        ),
        "oco": client.prepare_signed_request(
            "POST",
            "/market/orders/add",
            build_oco_order_payload(
                side="sell", src_currency="btc", dst_currency="usdt",
                amount="0.001", price="92000", stop_price="83000", stop_limit_price="82800",
                reference_price="87000", client_order_id=cid_oco,
            ),
        ),
        "status": client.prepare_signed_request(
            "POST", "/market/orders/status", build_order_status_payload(client_order_id=cid_lim),
        ),
        "cancel": client.prepare_signed_request(
            "POST", "/market/orders/update-status", build_order_cancel_payload(client_order_id=cid_lim),
        ),
        "list_get": client.prepare_signed_request("GET", "/market/orders/list?status=open"),
    }

    verified = {
        name: verify_nobitex_signature(pub_bytes, env["headers"], env["method"], env["full_path"], env["raw_body"])
        for name, env in envelopes.items()
    }
    blocked = asyncio.run(client.send_signed_request("POST", "/market/orders/add", {"clientOrderId": cid_lim}))
    http200_fail = parse_nobitex_response(
        200,
        {"status": "failed", "code": "DuplicateClientOrderId", "message": "Duplicate clientOrderId", "clientOrderId": cid_lim},
    )
    return {
        "base_url": client.base_url,
        "dry_run": client.dry_run,
        "all_signatures_verified": all(verified.values()),
        "verified_envelopes": verified,
        "dry_run_blocked_code": blocked.error_code,
        "http200_failed_detected": (not http200_fail.ok and http200_fail.error_code == "DuplicateClientOrderId"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Nobitex testnet Ed25519 dry-run execution harness")
    parser.add_argument("--live-public-check", action="store_true", help="Also probe public testnet /v3/orderbook/BTCUSDT")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()

    report = {"offline_dry_run": run_offline_dry_run_suite()}
    if args.live_public_check:
        client = NobitexTestnetClient(dry_run=True)
        try:
            report["testnet_public_orderbook"] = asyncio.run(client.fetch_public_orderbook(args.symbol))
        except Exception as exc:  # noqa: BLE001
            report["testnet_public_orderbook"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2))
    return 0 if report["offline_dry_run"]["all_signatures_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
