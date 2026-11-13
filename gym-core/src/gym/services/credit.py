"""Public Wallex trading-credit packages and a paper replay of one package on recorded quotes."""
from datetime import timedelta
from pathlib import Path

from ..adapters.store import MarketDB
from ..adapters.wallex_margin import ORIGIN, PACKAGES, public_margin
from ..domain.credit import package_terms, replay_credit
from ..domain.market_models import decimal, fields
from ..domain.model import iso, now_utc, parse_ts
from ..domain.rules import is_closed
from ..domain.strategy import digest
from .data_portal import DataPortal
from .margin import _save, load_receipt
from .rules import RuleService

LIMITATIONS = [
    "Paper simulation only; no package is activated and no order, transfer or wallet change is submitted.",
    "ASSUMED, not confirmed by the venue: the warning and liquidation limits apply to the whole sub-account value marked at the bid.",
    "ASSUMED: the daily fee is charged per completed day; the venue's final fee equals the daily fee times the lifetime.",
    "One asset is bought once at the first usable ask and held; a liquidation or expiry sells all of it at the bid.",
    "Account eligibility, renewal, connect-to-wallet top-ups and the venue's own liquidation execution are not modeled.",
    "Unobserved price moves between recorded quotes are unknown.",
]


def credit_action(root, action, value, *, store):
    if store != "live":
        raise ValueError("trading-credit terms and replay use the live observation store only")
    if action == "credit-packages":
        if value is not None:
            raise ValueError("credit-packages accepts no inputs")
        result, body_hash = public_margin(PACKAGES)
        if type(result) is not list or not 1 <= len(result) <= 500:
            raise ValueError("invalid trading-credit package list")
        packages = [package_terms(row) for row in result]
        if len({row["id"] for row in packages}) != len(packages):
            raise ValueError("duplicate trading-credit package identity")
        return _save(root, {"kind": "CREDIT_PACKAGES", "received_at": iso(now_utc()), "source_url": ORIGIN + PACKAGES,
                            "body_sha256": body_hash, "packages": sorted(packages, key=lambda row: row["id"])})
    fields(value, "packages_id package_id symbol from to exposure fee_rate")
    receipt = load_receipt(root, value["packages_id"], "CREDIT_PACKAGES")
    terms = next((row for row in receipt["packages"] if row["id"] == value["package_id"]), None)
    if terms is None:
        raise ValueError("package absent from this receipt")
    start, end = parse_ts(value["from"]), parse_ts(value["to"])
    if not start < end <= now_utc() or end - start > timedelta(days=terms["expire_days"] + 1):
        raise ValueError("credit replay requires a past window no longer than the package lifetime plus one day")
    path = Path(root) / "market.db"
    if not path.is_file():
        raise ValueError("credit replay requires recorded public quotes")
    db = MarketDB(path, readonly=True)
    try:
        symbol = value["symbol"]
        db.c.execute("BEGIN")
        portal, rules = DataPortal(db), RuleService(db)
        instrument = portal.instrument(symbol)
        if instrument.quote != terms["currency"]:
            raise ValueError("the market must be quoted in the package currency")
        if db.c.execute("SELECT count(*) FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?",
                        ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0] > 100000:
            raise ValueError("too many credit observations; narrow the window")
        tops = portal.tops(symbol, start, end)
        points = [(top, is_closed(rules.load(top.ts_avail)[1], instrument, top.ts_avail)) for top in tops]
        result = replay_credit(terms, instrument.base, points, start, end,
                               exposure=decimal(value["exposure"], "exposure", positive=True), fee_rate=value["fee_rate"])
        data_hash = digest([(iso(top.ts_avail), top.bid, top.ask, top.bid_qty, top.ask_qty, sorted(top.flags), closed)
                            for top, closed in points])
    finally:
        db.c.close()
    return _save(root, {"kind": "CREDIT_REPLAY", "inputs": value, "package": terms, "data_digest": data_hash,
                        "observations": len(tops), "result": result, "limitations": LIMITATIONS,
                        # Terms received after the window make the replay a what-if, not what was offered then.
                        "terms_known_at_window_start": parse_ts(receipt["received_at"]) <= start})
