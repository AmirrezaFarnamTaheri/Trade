"""Capped empirical log-growth sizing from a consumed preregistered paper evaluation."""
import json
from decimal import Decimal, localcontext
from itertools import pairwise
from pathlib import Path
from random import Random

from ..adapters.run_store import load_verified_run, run_path
from ..domain.market_models import fields, rate
from ..domain.model import parse_ts
from ..domain.performance import trade_ledger
from ..domain.registry import create_strategy
from ..domain.strategy import digest
from .reports import economic_report


def growth_fraction(returns):
    """Maximize mean log(1+f*r) on 0<=f<1 via its decreasing derivative."""
    if not returns or any(not r.is_finite() or r < -1 for r in returns):
        raise ValueError("need finite returns no lower than minus one")
    low, high = Decimal(0), Decimal("0.999999")
    if sum(returns, Decimal(0)) <= 0:
        return low
    for _ in range(32):
        middle = (low + high) / 2
        if sum((r / (1 + middle * r) for r in returns), Decimal(0)) > 0:
            low = middle
        else:
            high = middle
    return low


def simple_roundtrips(orders, trades):
    filled = [o for o in orders if o["status"] == "FILLED"]
    return (len(filled) == 2 * len(trades) and all(o["side"] == ("BUY" if i % 2 == 0 else "SELL") for i, o in enumerate(filled))
            and all(parse_ts(b["opened_at"]) >= parse_ts(a["closed_at"]) for a, b in pairwise(trades)))


def fractional_sizing(protocol, request):
    fields(request, "evaluation_id fraction cap seed simulations block_length")
    fraction, cap = rate(request["fraction"], "fraction"), rate(request["cap"], "cap")
    if not 0 < fraction <= Decimal("0.5") or not 0 < cap <= Decimal("0.25"):
        raise ValueError("fraction must be positive up to one half and cap up to one quarter")
    for key, low, high in (("seed", 0, 2**32 - 1), ("simulations", 100, 500), ("block_length", 1, 50)):
        if type(request[key]) is not int or not low <= request[key] <= high:
            raise ValueError("invalid fractional sizing resampling controls")
    evaluation = protocol.evaluation(request["evaluation_id"])
    if evaluation["state"] != "EVALUATED":
        raise ValueError("fractional sizing requires a completed preregistered evaluation")
    source = evaluation["result"]
    out = load_verified_run(protocol.root / "runs", source["run_id"], store=protocol.store)
    configuration = evaluation["configuration"]
    if (out["outputs_digest"] != source["outputs_digest"] or out["inputs"]["config_hash"] != configuration["config_hash"]
            or any(out["inputs"][key] != configuration[key] for key in ("symbol", "strategy", "resolution", "params"))
            or Decimal(out["inputs"]["cash"]) != Decimal(configuration["cash"])
            or Decimal(out["inputs"]["cost"]["fee_rate"]) != Decimal(configuration["fee_rate"])
            or out["inputs"]["from"] != configuration["test_from"] or out["inputs"]["to"] != configuration["test_to"]):
        raise ValueError("evaluation and native paper artifact differ")
    result = {"schema": "fractional-sizing/2", "store": protocol.store, "synthetic": protocol.store == "demo",
        "source_test_to": configuration["test_to"], "source_config_hash": configuration["config_hash"],
        "request": request, "run_id": out["run_id"], "source_outputs_digest": out["outputs_digest"],
        "status": "INSUFFICIENT_OOS_EVIDENCE", "inferred_full_fraction": None, "capped_fraction": None,
        "supplied_fraction_multiplier": str(fraction), "supplied_cap": str(cap), "funded_authority": False,
        "independent_final_evidence": False,
        "limits": ["Empirical log-growth model of closed non-overlapping paper positions; modeled received-asset fees are included.",
            "Thirty positions is a minimum diagnostic requirement, not proof of sufficient future evidence.",
            "Circular moving-block resampling assumes local stationarity; block length is supplied, not fitted.",
            "Sizing uses the fifth percentile of resampled fractions before the supplied multiplier and hard cap.",
            "No correction for searched strategies, unobserved tail loss, feed gaps, execution failure or distribution shift.",
            "Local preregistration is not independent custody. No replay or funded allocation is changed automatically."]}
    ledger = trade_ledger(out["result"]["orders"], out["result"]["base"])
    trades = ledger["trades"]
    simple = simple_roundtrips(out["result"]["orders"], trades)
    if not simple:
        result["status"] = "UNSUPPORTED_CASHFLOW_STRUCTURE"
    # Recycled partial proceeds require a cashflow-capital model, not a turnover denominator.
    result.update(closed_fills=len(trades), nonoverlapping_positions=len(trades) if simple else None,
                  open_quantity=str(ledger["open"]["quantity"]), valuation=economic_report(out)["valuation"]["status"])
    if (simple and 30 <= len(trades) <= 500 and not Decimal(ledger["open"]["quantity"]) and
            all(Decimal(t["cost"]) > 0 for t in trades) and result["valuation"] == "CURRENT"):
        with localcontext() as context:
            context.prec = 60
            returns = [Decimal(t["pnl"]) / Decimal(t["cost"]) for t in trades]
            if not any(r < 0 for r in returns):
                result["status"] = "INSUFFICIENT_LOSS_EXPERIENCE"
            else:
                length, rng, estimates = request["block_length"], Random(request["seed"]), []
                if length > len(returns):
                    raise ValueError("block length exceeds closed positions")
                for _ in range(request["simulations"]):
                    sample = []
                    while len(sample) < len(returns):
                        start = rng.randrange(len(returns))
                        sample.extend(returns[(start + i) % len(returns)] for i in range(min(length, len(returns) - len(sample))))
                    estimates.append(growth_fraction(sample))
                estimates.sort()
                quantiles = {str(p): str(estimates[(len(estimates) - 1) * p // 100]) for p in (5, 50, 95)}
                result.update(status="DESCRIPTIVE_ONLY", inferred_full_fraction=str(growth_fraction(returns)),
                    resampled_fraction_quantiles=quantiles, capped_fraction=str(min(cap, fraction * Decimal(quantiles["5"]))))
    result["report_id"] = digest(result)[:16]
    return result


def load_fractional_report(root, report_id, *, store, as_of, strategy, params, resolution, symbols, fee_rate):
    """Verify an immutable prior research receipt and its native OOS source.

    Local checks provide provenance only, not independent calibration or funded
    authority. A zero or unavailable fraction fails closed instead of silently
    reverting to a manually typed sizing assumption.
    """
    path = run_path(Path(root) / "runs" / "fractional_sizing", report_id)
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 128 * 1024:
        raise ValueError("fractional sizing requires a bounded saved report")
    try:
        with path.open("rb") as source:
            raw = source.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("fractional sizing report too large")
        saved = json.loads(raw)
        if type(saved) is not dict or set(saved) != {"run_id", "report"}:
            raise ValueError("invalid fractional report wrapper")
        report = saved["report"]
        if (type(report) is not dict or saved["run_id"] != report_id
                or report.get("report_id") != report_id
                or digest({k: v for k, v in report.items() if k != "report_id"})[:16] != report_id
                or report.get("schema") != "fractional-sizing/2"
                or report.get("store") != store
                or report.get("status") != "DESCRIPTIVE_ONLY"
                or report.get("funded_authority") is not False):
            raise ValueError("fractional report identity or eligibility mismatch")
        fraction = Decimal(report["capped_fraction"])
        if not fraction.is_finite() or not 0 < fraction <= Decimal("0.25"):
            raise ValueError("fractional report has no positive bounded fraction")
        native = load_verified_run(Path(root) / "runs", report["run_id"], store=store)
        inputs = native["inputs"]
        if (native["outputs_digest"] != report["source_outputs_digest"]
                or inputs["to"] != report["source_test_to"]
                or inputs["config_hash"] != report["source_config_hash"]
                or inputs.get("symbol") not in symbols or inputs["strategy"] != strategy
                or inputs["resolution"] != resolution
                or inputs["config_hash"] != create_strategy(strategy, params).config_hash
                or Decimal(inputs["cost"]["fee_rate"]) != Decimal(fee_rate)
                or parse_ts(inputs["to"]) > as_of):
            raise ValueError("fractional report source is not a prior matching paper study")
        return {"fraction": str(fraction), "report_id": report_id,
                "source_run_id": native["run_id"],
                "source_outputs_digest": native["outputs_digest"],
                "source_test_to": inputs["to"],
                "authority": "PAPER_ONLY", "independent_final_evidence": False}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, KeyError, TypeError, ArithmeticError):
        raise ValueError("invalid or unavailable fractional sizing receipt") from None
