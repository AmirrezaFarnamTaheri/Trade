"""Decision-time inspection and supplied-fill comparisons against verified saved runs."""
from decimal import Decimal, localcontext

from ..adapters.run_store import load_verified_run
from ..domain.market_models import decimal, fields, instant
from ..domain.model import parse_ts


def replay_decisions(root, request, *, store):
    fields(request, "run_id offset limit")
    offset, limit = request["offset"], request["limit"]
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("replay requires offset >= 0 and limit 1..200")
    out = load_verified_run(root, request["run_id"], store=store)
    result = out["result"]
    orders = {order["ref"]: order for order in result["orders"]}
    rows = []
    for index, decision in enumerate(result["decisions"][offset:offset + limit], offset):
        known = {key: decision.get(key) for key in ("t", "snapshot", "close", "bid", "ask", "quote_time",
                 "action", "reasons", "skipped", "features", "feature_values", "bar_known", "rules_known", "context_known", "reference_known")}
        if "rules_ref" in decision:
            known["rules_known"] = result["session"]["rule_snapshots"].get(decision["rules_ref"])
            if known["rules_known"] is None:
                raise ValueError("decision rule snapshot is missing")
        balances = decision.get("balances_before")
        if balances is None:
            # Older artifacts did not record equal-timestamp scan/settlement ordering.
            balances = {result["quote"]: Decimal(result["start_cash"])}
            for posting in result["postings"]:
                if parse_ts(posting["t"]) < parse_ts(decision["t"]):
                    ccy = posting["ccy"]
                    balances[ccy] = balances.get(ccy, Decimal(0)) + Decimal(posting["amount"])
            balances = {key: str(value) for key, value in balances.items()}
            balance_status = "RECONSTRUCTED_BEFORE_TIMESTAMP_EQUAL_TIME_UNKNOWN"
        else:
            balance_status = "RECORDED_BEFORE_DECISION"
        rows.append({"index": index, "known_at_decision": known, "balances_before": balances,
                     "balance_status": balance_status,
                     "subsequent_modeled_order": orders.get(decision.get("order"))})
    return {"schema": "decision-replay/1", "run_id": out["run_id"], "store": store,
            "outputs_digest": out["outputs_digest"], "symbol": result["symbol"], "quote_currency": result["quote"],
            "total": len(result["decisions"]), "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < len(result["decisions"]) else None,
            "decisions": rows, "future_outcomes_are_decision_evidence": False, "funded_authority": False}


def execution_quality(root, request, *, store):
    fields(request, "run_id observations")
    observations = request["observations"]
    if type(observations) is not list or len(observations) > 500:
        raise ValueError("supply at most 500 fill observations")
    out = load_verified_run(root, request["run_id"], store=store)
    result = out["result"]
    orders = {order["ref"]: order for order in result["orders"]}
    fills, unmatched, seen = {}, [], set()
    with localcontext() as ctx:
        ctx.prec = 160
        for row in observations:
            fields(row, "fill_id order_ref side quantity price fee fee_currency filled_at observed_at")
            if any(type(row[k]) is not str or not 1 <= len(row[k]) <= 128 for k in ("fill_id", "order_ref")):
                raise ValueError("fill identities must be bounded strings")
            if row["fill_id"] in seen or row["side"] not in ("BUY", "SELL"):
                raise ValueError("duplicate fill identity or invalid side")
            seen.add(row["fill_id"])
            qty, price, fee = decimal(row["quantity"], "quantity", positive=True), decimal(row["price"], "price", positive=True), decimal(row["fee"], "fee")
            filled, observed = instant(row["filled_at"]), instant(row["observed_at"])
            if filled > observed or row["fee_currency"] not in (result["base"], result["quote"]):
                raise ValueError("invalid fill clocks or fee currency")
            order = orders.get(row["order_ref"])
            if order is None:
                unmatched.append({"fill_id": row["fill_id"], "order_ref": row["order_ref"], "status": "UNMATCHED_ORDER"})
                continue
            if row["side"] != order["side"] or filled < instant(order["decision_time"]):
                raise ValueError("observed side/time disagrees with modeled order")
            fills.setdefault(row["order_ref"], []).append((qty, price, fee, row["fee_currency"], filled, row["fill_id"]))
        comparisons = []
        for ref, order in orders.items():
            actual = fills.get(ref, [])
            entry = {"order_ref": ref, "side": order["side"], "modeled_status": order["status"],
                     "status": "NO_OBSERVATION" if not actual else "OBSERVED", "fill_ids": [x[5] for x in actual]}
            if actual:
                qty = sum(x[0] for x in actual)
                vwap = sum(x[0] * x[1] for x in actual) / qty
                fee_quote = sum(x[2] * x[1] if x[3] == result["base"] else x[2] for x in actual)
                latency = (min(x[4] for x in actual) - instant(order["decision_time"])).total_seconds() * 1000
                entry.update(observed_quantity=str(qty), observed_vwap=str(vwap), observed_fee_quote_equivalent=str(fee_quote),
                             first_fill_latency_ms=latency, fee_conversion_basis="EACH_FILL_PRICE_FOR_BASE_FEES")
                if order["status"] == "FILLED":
                    modeled_price = Decimal(order["price"])
                    modeled_fee = Decimal(order["fee"]) * (modeled_price if order["fee_ccy"] == result["base"] else 1)
                    entry.update(quantity_difference=str(qty - Decimal(order["qty"])),
                                 adverse_price_bps=str((vwap / modeled_price - 1) * (10000 if order["side"] == "BUY" else -10000)),
                                 fee_quote_difference=str(fee_quote - modeled_fee),
                                 modeled_latency_ms=(instant(order["fill_time"]) - instant(order["decision_time"])).total_seconds() * 1000)
                else:
                    entry["status"] = "OBSERVED_AGAINST_MODELED_NONFILL"
            comparisons.append(entry)
    return {"schema": "execution-quality/1", "run_id": out["run_id"], "store": store, "quote_currency": result["quote"],
            "comparisons": comparisons, "unmatched": unmatched, "observations_authenticated": False,
            "settlement_verified": False, "funded_authority": False}
