"""Human-readable paper results and conservative economic-evidence summaries."""
import json
import math
from decimal import Decimal
from statistics import mean, stdev

from ..domain.model import QualityLimits, iso, parse_ts
from ..domain.strategy import digest


def sampled_drawdown(out):
    """Exact peak-to-trough diagnostic on recorded marks, including initial cash."""
    result = out["result"]
    initial = result.get("start_cash")
    curve = result.get("curve", [])
    if initial is None or not curve:
        return {"status": "UNAVAILABLE", "basis": "RECORDED_MARK_TO_BID"}
    initial = Decimal(initial)
    if not initial.is_finite() or initial <= 0:
        raise ValueError("invalid starting equity")
    start, cutoff = parse_ts(out["inputs"]["from"]), parse_ts(out["inputs"]["to"])
    peak, peak_at, previous = initial, start, start
    worst, peak_time, trough_time = Decimal(0), start, start
    samples = list(curve)
    if result.get("end"):
        samples.append((iso(cutoff), result["end"]["equity"]))
    for timestamp, raw in samples:
        at, equity = parse_ts(timestamp), Decimal(raw)
        if not previous <= at <= cutoff or not equity.is_finite() or equity < 0:
            raise ValueError("invalid recorded equity path")
        previous = at
        if equity > peak:
            peak, peak_at = equity, at
        loss = (peak - equity) / peak
        if loss > worst:
            worst, peak_time, trough_time = loss, peak_at, at
    return {"status": "AVAILABLE", "basis": "RECORDED_MARK_TO_BID", "samples": len(samples),
            "maximum_percent": str((worst * 100).quantize(Decimal("0.00000001"))),
            "peak_at": iso(peak_time), "trough_at": iso(trough_time),
            "peak_to_trough_seconds": (trough_time - peak_time).total_seconds(),
            "continuous_path_verified": False}


def paper_summary(out):
    """Portable allowlisted run card; private notes and arbitrary evidence stay local."""
    inputs, result = out["inputs"], out["result"]
    evidence = economic_report(out)
    card = {"schema": "paper-summary/1", "run_id": out["run_id"], "outputs_digest": out["outputs_digest"],
            "authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
            "inputs": {k: inputs[k] for k in ("engine", "symbol", "from", "to", "resolution", "strategy",
                                              "strategy_version", "config_hash", "rules_mode", "store", "data", "snapshots")},
            "currency": result["quote"], "starting_cash": result["start_cash"],
            "end": {k: result["end"][k] for k in ("mark_time", "equity", "net")} if result.get("end") else None,
            "counts": {k: result[k] for k in ("observations", "qualified", "bars", "fills")},
            "valuation": evidence["valuation"], "sampled_drawdown": sampled_drawdown(out),
            "cost_assumptions": {k: inputs["cost"][k] for k in ("fee_rate", "latency_ms", "max_wait_s", "fee_assumption")},
            "limitations": ["Paper fills and costs are modeled. No capital is authorized.",
                            "Summary omits decisions, private notes and account data; retain the original run for replay.",
                            "Recorded equity marks can miss losses between samples and during observation gaps.",
                            "Public metadata does not certify account fees, minimums or executable capacity; inspect full-run warnings."]}
    # Decimal durations must survive browser JSON's conversion of 60.0 to 60.
    card = json.loads(json.dumps(card), parse_float=str)
    card["summary_digest"] = digest(card)
    return card


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
    end = result.get("end")
    valuation = {"status": "UNAVAILABLE", "as_of": None, "age_seconds": None}
    if end and end.get("mark_time"):
        age = (parse_ts(inputs["to"]) - parse_ts(end["mark_time"])).total_seconds()
        valuation = {"status": "STALE" if age > QualityLimits().stale_s else "CURRENT" if age >= 0 else "INVALID",
                     "as_of": end["mark_time"], "age_seconds": age}
    limitation = ("Synthetic DEMO data is never capital evidence." if is_demo else
                  "No independent out-of-sample evidence; dependent trades and assumed fees prevent validated claims.")
    if valuation["status"] == "STALE":
        limitation = "Stale end valuation: the last qualified price is older than the run cutoff. " + limitation
    elif valuation["status"] in ("UNAVAILABLE", "INVALID"):
        limitation = "No valid end-of-window price is available. " + limitation
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
        "valuation": valuation,
        "sampled_drawdown": sampled_drawdown(out),
        "claim_ceiling": "NONE" if is_demo else "EXPERIMENTAL",
        "gate_eligible": False,
        "primary_limitation": limitation,
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
        valuation = economic_report(out)["valuation"]
        lines.append(f"Valuation at run cutoff: {valuation['status']}; last qualified price {valuation['age_seconds']:g}s earlier.")
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
