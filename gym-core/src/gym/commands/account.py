"""Account command implementations; invocation stays in gym.cli."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal

from ..domain.model import iso
from ..services.collector import now_utc
from .common import (
    _strict_offline_json,
    store_root,
)


def key_cmd(args) -> int:
    """Store a Wallex key DPAPI-encrypted for this Windows user; never echoes it."""
    import getpass

    from ..adapters import secret_store

    if args.op == "set-backup":
        phrase = getpass.getpass("Offline backup passphrase (sealed to this Windows user): ")
        if phrase != getpass.getpass("Repeat: "):
            raise ValueError("passphrases differ; nothing stored")
        print(f"backup passphrase stored at {secret_store.save_backup_passphrase(phrase)}")
        return 0
    if args.op == "show":
        for role in secret_store.ROLES:
            try:
                print(f"{role}: {secret_store.masked(secret_store.load(role))}")
            except ValueError:
                print(f"{role}: not stored")
        return 0
    key = os.environ.pop("WALLEX_KEY_INPUT", "") or getpass.getpass(f"Wallex {args.role} key: ")
    path = secret_store.save(args.role, key)
    print(f"{args.role} key {secret_store.masked(key.strip())} stored at {path}")
    return 0


def account_cmd(args) -> int:
    """Sanitized account observations from the selected read-only transport."""
    from ..adapters.wallex_account_read import ReadUncertain
    from ..domain.account_observations import project_account
    from ..services.external_journal import ExternalJournal

    if len(args.order) > 100 or len(set(args.order)) != len(args.order):
        print("error: provide at most 100 distinct order identities (nothing recorded)", file=sys.stderr)
        return 3

    async def observe(reader):
        balances = await reader.balances()
        fee = await reader.fee_rates()
        evidence = [await reader.manual_order_evidence(cid) for cid in args.order]
        pages = []
        for kind, field in (("OPEN", "open_orders_page"), ("HISTORY", "history_page")):
            number = getattr(args, field, None)
            if number is not None:
                pages.append(await reader.order_page(kind=kind, page=number, per_page=getattr(args, "per_page", 100)))
        by_id = {row["client_id"]: row for row in evidence}
        for page in pages:
            for row in page["orders"]:
                prior = by_id.get(row["client_id"])
                if prior is not None and prior != row:
                    raise ReadUncertain("order changed across separate observations; refresh before recording")
                by_id[row["client_id"]] = row
        evidence = list(by_id.values())
        orders = [{"client_id": row["client_id"], "status": row["raw_status"],
                   "symbol": row["symbol"], "filled": row["executed_qty"]} for row in evidence]
        return balances, fee, orders, evidence, pages, getattr(reader, "receipts", [])

    service_source = getattr(args, "source", "user") == "service"

    async def read():
        if service_source:
            from ..adapters.service_account_read import ServiceAccountReader
            return await observe(ServiceAccountReader())
        import aiohttp

        from ..adapters import secret_store
        from ..adapters.wallex_account_read import WallexAccountReader
        headers = {"x-api-key": secret_store.load("read")}
        async with aiohttp.ClientSession(headers=headers) as session:
            return await observe(WallexAccountReader(session))

    try:
        balances, fee, orders, evidence, pages, receipts = asyncio.run(read())
    except ReadUncertain as e:
        print(f"error: {e} (state UNKNOWN, nothing recorded)", file=sys.stderr)
        return 3
    observed = project_account("main", iso(now_utc()), balances=balances, orders=orders)
    if evidence:
        observed["order_evidence"] = evidence
    if pages:
        observed["order_pages"] = pages
    if receipts:
        observed["service_receipts"] = receipts
    nonzero = [b for b in observed["balances"] if Decimal(b["venue_value"]) or Decimal(b["venue_locked"])]
    fee_rates = fee
    transport = "EXECUTOR_SERVICE_WINHTTP" if service_source else "INTERACTIVE_USER_GET"
    pairs = sorted({(r["maker"], r["taker"]) for r in fee.values()})
    fee = {"symbols": len(fee), "maker_taker_rates": [list(p) for p in pairs],
           **{s: fee[s] for s in ("BTCUSDT", "USDTTMN", "BTCTMN") if s in fee}}
    print(json.dumps({"observed_at": observed["observed_at"], "fee": fee, "balances": nonzero,
                      "orders": observed["orders"], "order_evidence": evidence,
                      "order_pages": pages, "collection_complete": False,
                      "transport": transport,
                      **({"service_receipts": receipts} if receipts else {}),
                      "permission_status": "UNVERIFIED",
                      "funded_authority": False}, ensure_ascii=False, indent=2))
    if args.record:
        root = store_root(args)
        root.mkdir(parents=True, exist_ok=True)
        with ExternalJournal(root / "external_journal.db") as journal:
            print(f"{journal.record(observed, fee_rates=fee_rates, transport=transport)} order events and account snapshot recorded to the Journal")
    return 0


def external_observe_cmd(args) -> int:
    """Import only sanitized external observations, never account authority."""
    from ..services.operator_actions import operator_action
    report = operator_action(store_root(args), "external-import", _strict_offline_json(args.path, max_bytes=1_048_576))
    print(f"{report['recorded_observations']} external observations recorded (read-only, unverified; not funded).")
    return 0


def ticket_queue_add_cmd(args) -> int:
    """Persist the fully reconstructed dry-run ticket, never an approval."""
    from ..services.offline_review_journal import OfflineReviewJournal

    preview = _strict_offline_json(args.path, max_bytes=16384)
    root = store_root(args)
    root.mkdir(parents=True, exist_ok=True)
    with OfflineReviewJournal(root / "offline_reviews.db") as reviews:
        key = reviews.record(preview)
    print(json.dumps({
        "preview_sha256": key, "state": "PREVIEWED",
        "tier1_approval": False, "funded_authority": False,
        "order_submitted": False,
    }, ensure_ascii=False, indent=2))
    return 0


def ticket_queue_review_cmd(args) -> int:
    """Record offline ACKNOWLEDGE/REJECT; never issue T1 or live permission."""
    from ..services.offline_review_journal import OfflineReviewJournal

    root = store_root(args)
    root.mkdir(parents=True, exist_ok=True)
    with OfflineReviewJournal(root / "offline_reviews.db") as reviews:
        result = reviews.review(args.preview_sha256, args.decision, at=args.at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def probe_budget_stage_cmd(args) -> int:
    """Stage a fake/manual probe within an immutable offline full-loss budget."""
    from ..services.operator_actions import operator_action

    record = _strict_offline_json(args.path, max_bytes=8192)
    report = operator_action(store_root(args), "probe-stage", {"total_loss_limit": args.total_loss_limit,
                             "quote_asset": args.quote_asset, "probe": record})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def conversion_report_cmd(args) -> int:
    """Compute synthetic implementation shortfall; never submits orders."""
    from ..services.operator_actions import operator_action
    report = operator_action(store_root(args), "conversion-report", _strict_offline_json(args.path, max_bytes=65_536))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def ticket_preview_cmd(args) -> int:
    """Build an exact-cost OFFLINE preview, never an Executor order command."""
    from ..domain.assisted_ticket import prepare_preview_from_json

    params = _strict_offline_json(args.path, max_bytes=8192)
    print(json.dumps(prepare_preview_from_json(params), ensure_ascii=False, indent=2))
    return 0


def venue_fact_import_cmd(args) -> int:
    """Store strict, sanitized C1 evidence metadata; never accept raw API JSON.

    A claimed source is NOT authenticated. This command can never certify
    venue order methods, provision keys or authorize any funded operation.
    """
    from ..services.operator_actions import operator_action
    report = operator_action(store_root(args), "venue-fact-import", _strict_offline_json(args.path, max_bytes=16_384))
    print(f"VenueFacts evidence #{report['sequence']} recorded (unverified origin; no order authority).")
    return 0


def operator_review_cmd(args):
    from ..adapters.service_review import review
    from ..adapters.wallex_account_read import ReadUncertain
    try:
        result = asyncio.run(review(_strict_offline_json(args.input, max_bytes=16384)))
    except ReadUncertain:
        print(json.dumps({"error": "native review unacknowledged; inspect the same identity before retry",
            "operation_may_have_committed": True, "automatic_retry_allowed": False, "funded_authority": False, "order_submitted": False}))
        return 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 3 if result["state"] in ("DEFERRED", "REFUSED", "MISSING") else 0
