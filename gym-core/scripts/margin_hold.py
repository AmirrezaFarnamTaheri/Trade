"""Buy and sell-short holds at each credit ratio on every margin market over a window of recorded quotes.

Research layer (floats). Fees are the venue's margin previews: entry 0.25% of the position, 0.015% of the loan
when opened and again every 4 hours, 0.10% to close, liquidation when equity falls to 15% of collateral.
Entry is the first usable quote; liquidation is checked on every one-minute low and high.
Checked against the exact engine (`domain/margin.replay_margin`) on 55 stored previews: the two agree once the
closing fee is counted, which the engine leaves out of an open position's value.
Its liquidation prices sit within 0.28% of the venue's quoted liquidation prices on all 67 stored previews.
With `--terms` (files saved by `venue_recorder.py margin`), each market, side and ratio uses its own quoted
fees and liquidation price instead.

    uv run --no-sync python scripts/margin_hold.py --data ../data/live --from 2026-10-31T00:00:00Z --to 2026-11-16T18:00:00Z --out holds.json
"""
import argparse
import glob
import json
import sqlite3
import sys

ENTRY_FEE, EXIT_FEE, LOAN_FEE, PERIOD, FLOOR = 0.0025, 0.001, 0.00015, 14400, 0.15
BAD = ("STALE", "CROSSED", "ZERO_SPREAD", "NON_FINITE", "NON_POSITIVE")


def venue_terms(paths):
    """(symbol, side, ratio) -> fees as shares, and the liquidation price as a multiple of entry; newest preview wins."""
    terms = {}
    for path in paths:
        for line in open(path, encoding="utf-8"):
            record = json.loads(line)
            answer = record["answer"].get("result") if record["answer"].get("success") else None
            if not answer:
                continue
            price, loan = float(answer["open_price"]), float(answer["loan"]["value"])
            notional = loan if record["request"]["side"] == "long" else loan * price
            trade_fee = float(answer["trade_fee"]["value"]) * (price if answer["trade_fee"]["currency"] == record["rule"]["base"] else 1)
            key = (record["rule"]["symbol"], record["request"]["side"], float(record["request"]["risk_coef"]))
            terms[key] = {"entry_fee": trade_fee / notional, "loan_fee": float(answer["extend_fee"]["value"]) / loan,
                          "period": int(answer["extend_time"]), "liquidation": float(answer["liquidity_price"]) / price}
    return terms


def hold(side, ratio, entry, path, exit_price, terms=None):
    """Return on collateral (1.0 = all of it). `path` is (seconds since entry, low, high) per minute."""
    long = side == "long"
    fee, loan_fee, period = (terms["entry_fee"], terms["loan_fee"], terms["period"]) if terms else (ENTRY_FEE, LOAN_FEE, PERIOD)
    units = ratio / entry * (1 - fee) if long else ratio / entry
    cash = 1 - ratio * loan_fee if long else 1 + ratio * (1 - fee) - ratio * loan_fee
    debt = ratio if long else 0.0

    def equity(price, age):
        carry = ratio * loan_fee * (age // period)
        return cash - carry + units * price - debt if long else cash - carry - units * price

    for age, low, high in path:
        worst = low if long else high
        if terms and (worst <= entry * terms["liquidation"] if long else worst >= entry * terms["liquidation"]):
            return {"ret": max(equity(entry * terms["liquidation"], age), 0.0) - 1, "liquidated_h": round(age / 3600, 1)}
        if not terms and equity(worst, age) <= FLOOR:
            return {"ret": FLOOR - 1, "liquidated_h": round(age / 3600, 1)}
    age = path[-1][0] if path else 0
    worth = units * exit_price * (1 - EXIT_FEE) if long else -units * exit_price * (1 + EXIT_FEE)
    return {"ret": cash - ratio * loan_fee * (age // period) + worth - debt - 1, "liquidated_h": None}


def holds(root, t0, t1, terms=None):
    rules = max((json.load(open(f, encoding="utf-8")) for f in glob.glob(f"{root}/margin/*.json")),
                key=lambda d: d.get("received_at", "") if d.get("kind") == "MARKETS" else "")["markets"]
    db = sqlite3.connect(f"file:{root}/market.db?mode=ro", uri=True)
    rows = []
    for rule in rules:
        inst = "wallex:" + rule["symbol"]
        quotes = "select ts_avail, bid, ask, flags from book_top where instrument_id=? and ts_avail>=? and ts_avail<? order by ts_avail {} limit 50"
        ends = []
        for order in ("asc", "desc"):
            good = [q for q in db.execute(quotes.format(order), (inst, t0, t1))
                    if q[1] and q[2] and 0 < float(q[1]) < float(q[2]) and not any(b in q[3] for b in BAD)]
            ends.append(good[0] if good else None)
        if None in ends:
            continue
        (t_in, bid_in, ask_in, _), (t_out, bid_out, ask_out, _) = ends
        candles = db.execute("select cast(strftime('%s', t) as integer) - cast(strftime('%s', ?) as integer), l, h "
                             "from venue_candles where instrument_id=? and resolution='1min' and t>? and t<? order by t",
                             (t_in, inst, t_in, t_out)).fetchall()
        path = [(age, float(low), float(high)) for age, low, high in candles]
        lo, hi, step = (float(rule[k]) for k in ("min_risk_coef", "max_risk_coef", "risk_coef_step"))
        for side in ("long", "short"):
            for ratio in (1, 2, 3, 5, 10):
                if not lo <= ratio <= hi or (ratio - lo) % step:
                    continue
                entry, exit_price = (float(ask_in), float(bid_out)) if side == "long" else (float(bid_in), float(ask_out))
                quoted = (terms or {}).get((rule["symbol"], side, float(ratio)))
                rows.append({"symbol": rule["symbol"], "quote": rule["quote"], "side": side, "ratio": ratio,
                             "entry": entry, "exit": exit_price, "minutes": len(path), "terms": "venue" if quoted else "model",
                             "move": float(bid_out) / float(ask_in) - 1, **hold(side, ratio, entry, path, exit_price, quoted)})
    return rows


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", required=True, help="the live store directory (holds market.db and margin/)")
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--terms", nargs="*", default=[], help="margin-terms.jsonl files from the recorder")
    args = parser.parse_args(argv)
    rows = holds(args.data, args.start, args.end, venue_terms(args.terms))
    with open(args.out, "w", encoding="utf-8") as file:
        json.dump({"from": args.start, "to": args.end, "rows": rows}, file)
    print(len(rows), "rows on", len({r["symbol"] for r in rows}), "markets")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
