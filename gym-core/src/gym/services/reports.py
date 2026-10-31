"""Human-readable paper results and conservative economic-evidence summaries."""
import json
import math
from decimal import Decimal
from statistics import mean, stdev


def economic_report(out, diag=None):
    result = out["result"]
    inputs = out["inputs"]
    # One observation per completed round trip, not per tick or fill; still serially dependent.
    returns = []
    entry_value = None
    for order in result["orders"]:
        if order["status"] != "FILLED":
            continue
        if order["side"] == "BUY":
            entry_value = Decimal(order["qty"]) * Decimal(order["price"])
        elif entry_value:
            proceeds = Decimal(order["qty"]) * Decimal(order["price"]) - Decimal(order["fee"])
            returns.append(float((proceeds - entry_value) / entry_value))
            entry_value = None

    mean_return = mean(returns) if returns else None
    sample_sigma = stdev(returns) if len(returns) >= 2 else None
    sample_estimate = None
    if mean_return and mean_return > 0 and sample_sigma and sample_sigma > 0:
        sample_estimate = math.ceil((2.8 * sample_sigma / mean_return) ** 2)
    baselines = [(name, Decimal(record["end"]["net"]))
                 for name, record in out["baselines"].items() if record.get("end")]
    strongest = max(baselines, key=lambda baseline: baseline[1]) if baselines else None
    is_demo = inputs["store"] == "demo"
    return {
        "run_id": out["run_id"],
        "outputs_digest": out["outputs_digest"],
        "period": {name: inputs[name] for name in ("from", "to")},
        "currency": result["quote"],
        "completed_round_trips": len(returns),
        "mean_return": mean_return,
        "sample_sigma": sample_sigma,
        "iid_sample_estimate": sample_estimate,
        "strongest_baseline": {"name": strongest[0], "net": str(strongest[1])} if strongest else None,
        "claim_ceiling": "NONE" if is_demo else "EXPERIMENTAL",
        "gate_eligible": False,
        "primary_limitation": (
            "Synthetic DEMO data is never capital evidence." if is_demo else
            "No independent out-of-sample evidence; dependent trades and assumed fees prevent validated claims."
        ),
        "assumptions": inputs["cost"],
        "warnings": out["warnings"],
        "diagnostics": diag,
        "decision": "No capital authorized. Operator decisions are recorded separately; this report cannot arm trading.",
    }


def markdown(report):
    return "# TradingGYM economic evidence\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n"


def text_report(out: dict) -> str:
    result = out["result"]
    end = result["end"] or {}
    currency = result["quote"]

    def money(value):
        return f"{Decimal(value):>16,.2f}"

    lines = [
        f"PAPER run {out['run_id']}  {result['strategy']} {result['params']} "
        f"on {result['symbol']} {out['inputs']['resolution']}",
        f"window {out['inputs']['from']} .. {out['inputs']['to']}   rules: {out['inputs']['rules_mode']}   "
        f"outputs {out['outputs_digest']}",
        f"bars {result['bars']}  fills {result['fills']}  nonfills {result['nonfills'] or 0}  "
        f"observations {result['observations']} (qualified {result['qualified']})", "",
    ]
    if end:
        lines.append(f"Gross-to-net waterfall ({currency}, mark-to-bid at {end['mark_time']}):")
        for name, value in end["waterfall"].items():
            lines.append(f"  {name:<16}{money(value)}")
        lines.append(f"  {'equity':<16}{money(end['equity'])}   net liquidation estimate (modeled) "
                     f"{money(end['net_liquidation_estimate']).strip()}")
    active = out["ranking"]["active"]
    lines += ["", "active ranking (USDT-equivalent; abstainers excluded):"]
    if active:
        for row in active:
            lines.append(f"  {row['rank']:>2}. {row['name']:<12}{money(row['net_usdt_eq'])} USDT-eq   "
                         f"{money(row['net_quote'])} {row['quote']}")
    else:
        lines.append("  unavailable (no active result with a USDT-equivalent valuation)")
    if out["ranking"]["abstainers"]:
        lines.append("  abstainers: " + ", ".join(row["name"] for row in out["ranking"]["abstainers"]))
    units = ", and USDT-equivalent)" if out["fx"] or currency == "USDT" else ")"
    lines += ["", f"vs baselines (same window, cash, costs; net in {currency}" + units]
    for name, baseline in {"strategy": result, **out["baselines"]}.items():
        if "unavailable" in baseline:
            lines.append(f"  {name:<12} unavailable: {baseline['unavailable']}")
        else:
            baseline_end = baseline["end"]
            line = f"  {name:<12}{money(baseline_end['net'])} {currency}"
            if "net_usdt_eq" in baseline_end:
                line += f"   {money(baseline_end['net_usdt_eq'])} USDT-eq"
            lines.append(line)
    if out["fx"]:
        lines.append(f"  USDT-eq via {out['fx']['pair']} {out['fx']['start']} -> "
                     f"{out['fx']['end']} ({out['fx']['basis']}; start {out['fx'].get('start_status', 'LIVE')}, "
                     f"end {out['fx'].get('end_status', 'LIVE')})")
    lines += ["", *("! " + warning for warning in out["warnings"])]
    return "\n".join(lines)
