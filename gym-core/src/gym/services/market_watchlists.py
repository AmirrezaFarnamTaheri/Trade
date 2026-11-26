"""Immutable, effective-dated curated market selections for research."""
import re

from ..adapters.run_store import run_path, save_run
from ..domain.market_models import fields, instant
from ..domain.model import iso, strict_loads
from ..domain.strategy import digest


def _revision(value):
    fields(value, "name effective_from symbols")
    name, symbols = value["name"], value["symbols"]
    if type(name) is not str or not 1 <= len(name) <= 80 or name.strip() != name or not name.isprintable():
        raise ValueError("watchlist name must contain 1..80 printable characters")
    if (type(symbols) is not list or not 1 <= len(symbols) <= 500
            or any(type(s) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", s) for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("watchlist needs 1..500 distinct market symbols")
    body = {"schema": "market-watchlist/1", "name": name, "effective_from": iso(instant(value["effective_from"])),
            "symbols": sorted(symbols)}
    return {**body, "watchlist_id": digest(body)[:16]}


def watchlist_at(record, cutoff):
    fields(record, "schema name effective_from symbols watchlist_id")
    actual = _revision({key: record[key] for key in ("name", "effective_from", "symbols")})
    if actual != record:
        raise ValueError("watchlist revision evidence changed")
    if cutoff is not None and instant(record["effective_from"]) > cutoff:
        raise ValueError("watchlist revision is not effective at the selection cutoff")
    return record


def save_watchlist(root, value):
    record = _revision(value)
    save_run({"run_id": record["watchlist_id"], "watchlist": record}, root / "watchlists")
    return record


def load_watchlist(root, key, cutoff=None):
    if type(key) is not str:
        raise ValueError("watchlist_id must be a saved revision ID")
    path = run_path(root / "watchlists", key)
    try:
        with path.open("rb") as handle:
            data = handle.read(33_000)
    except FileNotFoundError:
        raise ValueError("unknown watchlist revision") from None
    if len(data) >= 33_000:
        raise ValueError("watchlist revision exceeds its size limit")
    doc = strict_loads(data.decode("utf-8"))
    fields(doc, "run_id watchlist")
    record = watchlist_at(doc["watchlist"], cutoff)
    if doc["run_id"] != key or record["watchlist_id"] != key:
        raise ValueError("watchlist revision ID mismatch")
    return record
