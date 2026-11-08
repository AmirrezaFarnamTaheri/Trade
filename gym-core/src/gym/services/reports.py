"""Human-readable paper results and conservative economic-evidence summaries."""
import json
import math
from decimal import Decimal
from statistics import mean, stdev

from ..domain.model import QualityLimits, parse_ts
from ..domain.performance import performance, sampled_drawdown
from ..domain.strategy import digest


def paper_summary(out):
    """Portable allowlisted run card; private notes and arbitrary evidence stay local."""
    inputs, result = out["inputs"], out["result"]
    evidence = economic_report(out)
    # v2: adds risk/return performance; drops the constant funded_authority/order_submitted flags.
    card = {"schema": "paper-summary/2", "run_id": out["run_id"], "outputs_digest": out["outputs_digest"],
            "authority": "PAPER_ONLY",
            "inputs": {k: inputs[k] for k in ("engine", "symbol", "from", "to", "resolution", "strategy",
                                              "strategy_version", "config_hash", "rules_mode", "store", "data", "snapshots")},
            "currency": result["quote"], "starting_cash": result["start_cash"],
            "end": {k: result["end"][k] for k in ("mark_time", "equity", "net")} if result.get("end") else None,
            "counts": {k: result[k] for k in ("observations", "qualified", "bars", "fills")},
            "valuation": evidence["valuation"], "sampled_drawdown": evidence["sampled_drawdown"],
            "performance": {k: v for k, v in evidence["performance"].items() if k != "ledger"},
            "cost_assumptions": {k: inputs["cost"][k] for k in (
                "fee_rate", "latency_ms", "max_wait_s", "fee_assumption", "max_participation", "walk_depth",
                "carry_remainder", "max_fraction", "vol_target", "vol_lookback", "order_type", "maker_fee_rate", "limit_fill_model")
                if k in inputs["cost"]},
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
    # One observation per closed trade (FIFO lots), not per tick or fill; still serially dependent.
    drawdown = sampled_drawdown(out)
    perf = performance(out, drawdown, enhanced=True)
    returns = [float(trade["return"]) for trade in perf["ledger"] if trade["return"] is not None]

    mean_return = mean(returns) if returns else None
    sample_sigma = stdev(returns) if len(returns) >= 2 else None
    sample_estimate = None
    if mean_return and mean_return > 0 and sample_sigma and sample_sigma > 0:
        sample_estimate = math.ceil((2.8 * sample_sigma / mean_return) ** 2)
    baselines = [(name, Decimal(record["end"]["net"]))
                 for name, record in out["baselines"].items() if record.get("end")]
    strongest = max(baselines, key=lambda baseline: baseline[1]) if baselines else None
    is_demo = inputs["store"] == "demo"
    valuation = run_valuation(out)
    limitation = ("Synthetic DEMO data is never capital evidence." if is_demo else
                  "No independent out-of-sample evidence; dependent trades and assumed fees prevent validated claims.")
    if valuation["status"] == "STALE":
        limitation = "Stale end valuation: the last qualified price is older than the run cutoff. " + limitation
    elif valuation["status"] in ("UNAVAILABLE", "INVALID"):
        limitation = "No valid end-of-window price is available. " + limitation
    from .attribution import toman_attribution
    from .data_quality_gate import recorded_bar_coverage
    from .random_entry import random_entry_report

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
        "sampled_drawdown": drawdown,
        "performance": perf,
        "claim_ceiling": "NONE" if is_demo else "EXPERIMENTAL",
        "gate_eligible": False,
        "primary_limitation": limitation,
        "assumptions": inputs["cost"],
        "warnings": out["warnings"],
        "diagnostics": diag,
        "observed_bar_coverage": recorded_bar_coverage(out),
        "random_entry_baseline": random_entry_report(out),
        "return_attribution": toman_attribution(out),
        "decision": "No capital authorized. Operator decisions are recorded separately; this report cannot arm trading.",
    }


def run_valuation(out):
    end = out["result"].get("end")
    if not end or not end.get("mark_time"):
        return {"status": "UNAVAILABLE", "as_of": None, "age_seconds": None}
    age = (parse_ts(out["inputs"]["to"]) - parse_ts(end["mark_time"])).total_seconds()
    return {"status": "STALE" if age > QualityLimits().stale_s else "CURRENT" if age >= 0 else "INVALID",
            "as_of": end["mark_time"], "age_seconds": age}


def markdown(report):
    return "# TradingGYM economic evidence\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n"


def text_report(out: dict) -> str:
    """Render human-readable paper evidence without mutating saved artifact bytes."""
    result = out["result"]
    end = result["end"] or {}
    currency = result["quote"]

    def money(value):
        return f"{Decimal(value):>16,.2f}"

    lines = [
        (f"PAPER run {out['run_id']}  {result['strategy']} {result['params']} "
        f"on {result['symbol']} {out['inputs']['resolution']}"),
        (f"window {out['inputs']['from']} .. {out['inputs']['to']}   rules: {out['inputs']['rules_mode']}   "
        f"outputs {out['outputs_digest']}"),
        (f"bars {result['bars']}  fills {result['fills']}  nonfills {result['nonfills'] or 0}  "
        f"observations {result['observations']} (qualified {result['qualified']})"), "",
    ]
    from .data_quality_gate import recorded_bar_coverage

    coverage = recorded_bar_coverage(out)
    if coverage["status"] == "DESCRIPTIVE":
        lines.append(f"Observed closed-bar coverage: {coverage['coverage_share']} "
                     "(stale quote share NOT_ASSESSED without gate).")
    else:
        lines.append(f"Observed closed-bar coverage: {coverage['status']}.")
    if end:
        valuation = economic_report(out)["valuation"]
        lines.append(f"Valuation at run cutoff: {valuation['status']}; last qualified price {valuation['age_seconds']:g}s earlier.")
        lines.append(f"Gross-to-net waterfall ({currency}, mark-to-bid at {end['mark_time']}):")
        for name, value in end["waterfall"].items():
            lines.append(f"  {name:<16}{money(value)}")
        lines.append(f"  {'equity':<16}{money(end['equity'])}   net liquidation estimate (modeled) "
                     f"{money(end['net_liquidation_estimate']).strip()}")
        perf = economic_report(out)["performance"]
        if perf.get("status") == "AVAILABLE":
            trades, ret = perf["trades"], perf.get("returns") or {}
            def ratio(v):
                return "n/a" if v is None else f"{v:.2f}"
            lines += ["", (f"Performance: return {perf.get('total_return_pct', 'n/a')}%   max drawdown {perf.get('max_drawdown_pct', 'n/a')}%   "
                           f"Sharpe/period {ratio(ret.get('sharpe_per_period'))}   annualized {ratio(ret.get('sharpe_annualized'))}   "
                           f"P(Sharpe>0) {ratio(ret.get('probabilistic_sharpe'))}"),
                      (f"Track record: {ret.get('track_record_status', 'UNAVAILABLE')}; minimum observations "
                       f"{ratio(ret.get('minimum_track_record'))}; Lo-adjusted annual Sharpe "
                       f"{ratio(ret.get('sharpe_annualized_lo'))} (lags {ret.get('lo_lags_used', 0)})."),
                      (f"Trades: {trades['closed_trades']} closed   win rate {ratio(trades['win_rate'])}   "
                       f"profit factor {ratio(trades['profit_factor'])}   exposure {ratio(trades['exposure'])}   turnover {trades['turnover']}x")]
    attribution = economic_report(out)["return_attribution"]
    if attribution["status"] == "AVAILABLE":
        lines.append("TMN return attribution: "
                     f"USDT {attribution['usdt_return']} + TMN move {attribution['toman_move']} + "
                     f"interaction {attribution['interaction']} = {attribution['total_toman_return']}")
    elif currency == "TMN":
        lines.append("TMN return attribution: UNAVAILABLE (point-in-time FX evidence missing).")
    timing = economic_report(out)["random_entry_baseline"]
    if timing["status"] == "EXPLORATORY":
        lines.append(f"Random-entry timing percentile: {timing['percentile']} (200 seeded simulations, "
                     f"{timing['trades']} exact-duration trades; modelled execution friction).")
    else:
        lines.append("Random-entry timing percentile: NOT_ENOUGH_DATA.")
    if "limit_fill_diagnostics" in result:
        print_evidence = result["limit_fill_diagnostics"]
        lines.append("Limit fill print exposure: "
                     f'{print_evidence["suspected_identical_prints"]} suspected identical trade prints '
                     f'across {print_evidence["affected_fills"]} filled orders; '
                     f'{print_evidence["identical_print_capacity_qty"]} base units of modeled capacity '
                     "(not deduplicated; venue trade IDs unavailable).")
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
    # Display-only guidance: market-order warnings are part of frozen persisted IDs.
    notice = "Price-band reference ESTIMATED from the first observed Tehran-day midpoint; Wallex does not publish a daily reference price or band."
    if notice not in out["warnings"]:
        lines.append("! " + notice)
    return "\n".join(lines)
