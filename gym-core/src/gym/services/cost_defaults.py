"""Dated, read-only cost defaults from local account and calibration evidence.

Fee observations are account GET receipts. Feed timing is only a lower bound for order
latency; paper slippage is circular and remains a display-only diagnostic.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..domain.model import iso, now_utc, parse_ts
from ..domain.sim import CostModel
from ..domain.strategy import digest

_MAX_AGE = timedelta(hours=24)
_FALLBACK_FEE = Decimal(os.environ.get("GYM_FEE_RATE", "0.001"))
_FALLBACK_LATENCY_MS = 500
# Wallex published Level-1 structured-fee schedule (/v2/structured-fee):
# TMN spot markets: 0.25% maker / 0.30% taker; USDT spot markets: 0.10% maker / 0.13% taker.
PUBLISHED_LEVEL1_FEES: dict[str, tuple[Decimal, Decimal]] = {
    "TMN": (Decimal("0.0025"), Decimal("0.0030")),
    "USDT": (Decimal("0.0010"), Decimal("0.0013")),
}


def _quote_group(symbol: str) -> str | None:
    upper = symbol.upper()
    if upper.endswith("TMN"):
        return "TMN"
    if upper.endswith("USDT"):
        return "USDT"
    return None


def published_structured_fees(root: Path | None, symbol: str, now: datetime) -> tuple[Decimal, Decimal, str, str] | None:
    """Resolve Wallex quote-currency maker/taker rates from a recent /v2/structured-fee snapshot or Level-1 table."""
    group = _quote_group(symbol)
    if group is None:
        return None
    if root is not None:
        path = Path(root) / "structured_fees.json"
        if not path.is_symlink() and path.is_file():
            try:
                data = json.loads(path.read_text("utf-8"))
                fetched_at = data.get("fetched_at", "")
                if data.get("schema") == "structured-fee-vintage/1" and _recent(fetched_at, now):
                    rows = (data.get("groups") or {}).get(group) or []
                    if rows:
                        maker = Decimal(str(rows[0]["maker"]))
                        taker = Decimal(str(rows[0]["taker"]))
                        if 0 <= maker < 1 and 0 <= taker < 1:
                            return maker, taker, fetched_at, "PUBLIC_STRUCTURED_FEE_VINTAGE"
            except (ValueError, KeyError, TypeError, ArithmeticError, OSError):
                pass
    maker, taker = PUBLISHED_LEVEL1_FEES[group]
    return maker, taker, iso(now), "PUBLISHED_STRUCTURED_FEE_L1"


def save_calibration(root: Path, report: dict, *, at: datetime | None = None) -> Path:
    """Append a bounded, immutable calibration receipt without overwriting past estimates."""
    at = at or now_utc()
    document = {"schema": "paper-cost-calibration/1", "as_of": iso(at),
                "feed": report["feed"], "paper_fills": report["paper_fills"],
                "synthetic": report.get("synthetic", False),
                "limits": ["Feed timing lower-bounds order latency, not verified round-trip time.",
                           "Paper fill slippage reuses modeled costs, so no independent slippage parameter is applied."]}
    key = digest(document)
    directory = Path(root) / "cost_calibrations"
    if directory.is_symlink():
        raise ValueError("calibration receipts cannot be symlinks")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (key[:32] + ".json")
    encoded = json.dumps({"id": key, **document}, sort_keys=True, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 128_000:
        raise ValueError("calibration exceeds receipt limit")
    if path.exists():
        if path.is_symlink() or path.read_text("utf-8") != encoded:
            raise ValueError("conflicting calibration receipt")
    else:
        try:
            with path.open("x", encoding="utf-8") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if path.is_symlink() or path.read_text("utf-8") != encoded:
                raise ValueError("conflicting concurrent calibration receipt") from None
    return path


def _recent(stamp: str, now: datetime) -> bool:
    try:
        age = now - parse_ts(stamp)
    except (ValueError, TypeError):
        return False
    return timedelta(0) <= age <= _MAX_AGE


def _recent_calibration(root: Path, symbol: str, now: datetime) -> tuple[int, str] | None:
    """Use per-market measured feed delay only if enough recent nonnegative samples exist."""
    directory = root / "cost_calibrations"
    if directory.is_symlink() or not directory.is_dir():
        return None
    # Receipt filenames are content hashes, not chronological names.
    def mtime(path):
        try:
            return path.stat().st_mtime if not path.is_symlink() else -1
        except OSError:
            return -1

    eligible = []
    for path in sorted(directory.glob("*.json"), key=mtime, reverse=True)[:500]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128_000:
            continue
        try:
            item = json.loads(path.read_text("utf-8"))
            fingerprint = item.pop("id")
            if digest(item) != fingerprint or item.get("schema") != "paper-cost-calibration/1":
                continue
            if item.get("synthetic") is True or not _recent(item["as_of"], now):
                continue
            feed = item["feed"]
            by_symbol = feed.get("by_symbol", {})
            rates = by_symbol.get(symbol)
            # Global percentiles can mix markets. Do not promote a cross-market timing proxy.
            if (not isinstance(rates, dict) or int(rates.get("n", 0)) < 20
                    or int(feed.get("negative_samples", -1)) != 0
                    or not _recent(feed["last_receipt"], now)):
                continue
            millis = int(rates["p90"])
            if not 0 <= millis <= 60_000:
                continue
            eligible.append((parse_ts(item["as_of"]), millis, item["as_of"]))
        except (KeyError, TypeError, ValueError, OSError):
            continue
    if not eligible:
        return None
    _, latency, at = max(eligible)
    return latency, at


def _recent_fees(root: Path, symbol: str, now: datetime) -> tuple[Decimal, Decimal, str, dict] | None:
    """Use only a recent authenticated GET account snapshot for exact maker/taker fee rates."""
    path = root / "external_journal.db"
    if path.is_symlink() or not path.is_file():
        return None
    from .external_journal import ExternalJournal

    try:
        with ExternalJournal(path) as journal:
            row = journal.latest_snapshot("main", at=now)
    except (ValueError, sqlite3.Error, OSError):
        return None
    if (row is None or row.get("transport") not in ("INTERACTIVE_USER_GET", "EXECUTOR_SERVICE_WINHTTP")
            or not _recent(row["observed_at"], now)):
        return None
    fees = (row.get("fee_rates") or {}).get(symbol)
    if not fees:
        return None
    try:
        maker, taker = Decimal(fees["maker"]), Decimal(fees["taker"])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if not all(x.is_finite() and 0 <= x < 1 for x in (maker, taker)):
        return None
    return maker, taker, row["observed_at"], row["fee_rates"]


def calibrated_cost(root: Path, symbol: str, *, fee: str | None = None,
                    maker_fee: str | None = None, latency_ms: int | None = None,
                    order_type: str = "market", now: datetime | None = None,
                    use_published_fees: bool = False, **options) -> CostModel:
    """Resolve explicit overrides first, otherwise use recent receipts with dated provenance."""
    now = now or now_utc()
    need_fees = fee is None or (order_type == "limit" and maker_fee is None)
    fees = _recent_fees(root, symbol, now) if need_fees else None
    pub = published_structured_fees(root, symbol, now) if (need_fees and fees is None and use_published_fees) else None
    timing = _recent_calibration(root, symbol, now) if latency_ms is None else None
    fee_value = Decimal(fee) if fee is not None else fees[1] if fees else pub[1] if pub else _FALLBACK_FEE
    maker_value = Decimal(maker_fee) if maker_fee is not None else fees[0] if fees else pub[0] if pub else None
    latency = latency_ms if latency_ms is not None else timing[0] if timing else _FALLBACK_LATENCY_MS
    provenance = {}
    if fees and need_fees:
        provenance["fee_observed_at"] = fees[2]
        provenance["fee_source"] = "READ_ONLY_ACCOUNT_GET"
        provenance["maker_taker_separate"] = True
    elif pub and need_fees:
        provenance["fee_observed_at"] = pub[2]
        provenance["fee_source"] = pub[3]
        provenance["maker_taker_separate"] = True
    if timing:
        provenance["feed_observed_at"] = timing[1]
        provenance["latency_source"] = "PUBLIC_FEED_TO_LOCAL_RECEIPT_P90_LOWER_BOUND"
        provenance["independent_order_latency"] = False
    if provenance:
        provenance["slippage_status"] = "NOT_INDEPENDENTLY_MEASURED"
    market_fees = None if not fees else {
        market: {"maker": str(maker_value) if maker_fee is not None else rates["maker"],
                 "taker": str(fee_value) if fee is not None else rates["taker"]}
        for market, rates in fees[3].items()}
    return CostModel(fee_rate=fee_value, maker_fee_rate=maker_value,
                     latency=timedelta(milliseconds=latency),
                     order_type=order_type, calibration=provenance or None,
                     market_fees=market_fees, **options)
