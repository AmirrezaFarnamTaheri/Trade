"""Cheapest way to convert between Toman and USDT on Wallex right now: directly, or through a coin traded in both.

Toman to USDT: buy USDT on USDTTMN, or buy coin X on XTMN and sell it on XUSDT. USDT to Toman is the reverse.
Each leg fills at the best displayed price and pays the account fee in the asset received. A route's capacity is the
largest amount both legs can fill at those prices; larger amounts need depth that is not recorded, so they are flagged,
never priced. Paper only: this proposes a route and never places an order.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from ..domain.model import iso, parse_ts

DIRECTIONS = ("TMN_TO_USDT", "USDT_TO_TMN")
MAX_QUOTE_AGE_SECONDS = 120


@dataclass(frozen=True)
class Touch:
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    at: str


def routes(touches: dict[str, Touch], amount: Decimal, direction: str, fee: Decimal) -> list[dict]:
    """Every available route for `amount` (TMN or USDT, by direction), best first by amount received."""
    if direction not in DIRECTIONS or amount <= 0 or not 0 <= fee < 1:
        raise ValueError("direction must be TMN_TO_USDT or USDT_TO_TMN, with a positive amount and a fee in [0, 1)")
    keep = 1 - fee
    found = []
    direct = touches.get("USDTTMN")
    if direct:
        if direction == "TMN_TO_USDT":
            received, capacity = amount / direct.ask * keep, direct.ask_qty * direct.ask
        else:
            received, capacity = amount * direct.bid * keep, direct.bid_qty
        found.append({"route": "USDTTMN", "legs": 1, "received": received, "capacity": capacity, "quotes_at": [direct.at]})
    coins = {symbol[:-3] for symbol in touches if symbol.endswith("TMN") and symbol != "USDTTMN"}
    for coin in sorted(coins):
        in_tmn, in_usdt = touches.get(coin + "TMN"), touches.get(coin + "USDT")
        if not in_tmn or not in_usdt:
            continue
        if direction == "TMN_TO_USDT":
            units = amount / in_tmn.ask * keep
            received = units * in_usdt.bid * keep
            capacity = min(in_tmn.ask_qty, in_usdt.bid_qty) * in_tmn.ask  # in TMN spent
        else:
            units = amount / in_usdt.ask * keep
            received = units * in_tmn.bid * keep
            capacity = min(in_usdt.ask_qty, in_tmn.bid_qty) * in_usdt.ask  # in USDT spent
        found.append({"route": f"{coin}TMN > {coin}USDT" if direction == "TMN_TO_USDT" else f"{coin}USDT > {coin}TMN",
                      "legs": 2, "received": received, "capacity": capacity, "quotes_at": [in_tmn.at, in_usdt.at]})
    for row in found:
        row["fits_displayed_size"] = amount <= row["capacity"]
    return sorted(found, key=lambda row: (not row["fits_displayed_size"], -row["received"]))


def latest_touches(db, at, symbols=None) -> dict[str, Touch]:
    """The most recent qualified top of book per market, at most two minutes old at `at`."""
    cutoff = iso(parse_ts(at) if isinstance(at, str) else at)
    oldest = iso(parse_ts(cutoff) - timedelta(seconds=MAX_QUOTE_AGE_SECONDS))
    if symbols is None:
        symbols = [row[0][7:] for row in db.c.execute(
            "SELECT DISTINCT instrument_id FROM instrument_specs WHERE valid_to IS NULL AND (instrument_id LIKE '%TMN' OR instrument_id LIKE '%USDT')")]
    out = {}
    for symbol in symbols:
        row = db.c.execute("SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags FROM book_top WHERE instrument_id=? AND ts_avail<=? "
                           "ORDER BY ts_avail DESC LIMIT 1", (f"wallex:{symbol}", cutoff)).fetchone()
        if not row or row[0] < oldest or None in row[1:5] or any(flag in (row[5] or "") for flag in ("STALE", "CROSSED")):
            continue
        bid, ask, bid_qty, ask_qty = (Decimal(value) for value in row[1:5])
        if 0 < bid < ask and bid_qty > 0 and ask_qty > 0:
            out[symbol] = Touch(bid, ask, bid_qty, ask_qty, row[0])
    return out


def recommend(db, amount: Decimal, direction: str, at, fee: Decimal = Decimal("0.001"), top: int = 5) -> dict:
    """The best routes now and the saving of the best against converting directly, in basis points."""
    found = routes(latest_touches(db, at), amount, direction, fee)
    direct = next((row for row in found if row["route"] == "USDTTMN"), None)
    best = found[0] if found else None
    saving = (None if not (best and direct) or not best["fits_displayed_size"]
              else float((best["received"] / direct["received"] - 1) * 10000))
    as_text = lambda row: {**row, "received": str(row["received"].quantize(Decimal("0.000001"))),  # noqa: E731
                           "capacity": str(row["capacity"].quantize(Decimal("0.01")))}
    return {"direction": direction, "amount": str(amount), "at": iso(parse_ts(at) if isinstance(at, str) else at),
            "fee_per_leg": str(fee), "direct_available": direct is not None,
            "saving_vs_direct_bps": None if saving is None else round(saving, 2),
            "routes": [as_text(row) for row in found[:top]], "order_submitted": False}

