"""Exact, measurement-aligned arithmetic over the native observation vintage store."""
from decimal import ROUND_HALF_EVEN, localcontext
import re

from ..domain.market_models import fields
from ..domain.model import iso, parse_ts
from ..domain.strategy import digest
from .research_grounding import _number


def derived_series(protocol, request):
    fields(request, "left right operation as_of max_age_seconds max_skew_seconds")
    if request["operation"] not in ("RATIO", "DIFFERENCE"):
        raise ValueError("derived series supports RATIO or DIFFERENCE")
    for key, lower in (("max_age_seconds", 1), ("max_skew_seconds", 0)):
        if type(request[key]) is not int or not lower <= request[key] <= 2678400:
            raise ValueError("alignment/freshness bounds must be integer seconds up to 31 days")
    if type(request["as_of"]) is not str:
        raise ValueError("derived series requires a zoned cutoff")
    cutoff = parse_ts(request["as_of"])
    if protocol.conn.in_transaction:
        raise ValueError("derived series requires its own read snapshot")
    protocol.conn.execute("BEGIN")
    try:
        inputs = [protocol.observation(request[side], cutoff) for side in ("left", "right")]
    finally:
        protocol.conn.rollback()
    result = {"authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
              "as_of": iso(cutoff), "operation": request["operation"], "status": "UNAVAILABLE", "reason": None,
              "value": None, "unit": None, "inputs": inputs, "source_authenticity_verified": False,
              "alignment_basis": "MEASUREMENT_TIME", "max_age_seconds": request["max_age_seconds"],
              "decimal_precision": 160,
              "max_skew_seconds": request["max_skew_seconds"],
              "limitation": "Arithmetic over supplied vintages only. Release, receipt, revision and measurement clocks are distinct; "
                            "no missing series, source authenticity, causal effect or trading confidence is inferred."}
    if any(row is None for row in inputs):
        result["reason"] = "MISSING_INPUT"
    elif any(row["kind"] == "NEWS" for row in inputs):
        raise ValueError("derived series requires numeric observations")
    elif any("measured_at" not in row for row in inputs):
        result["reason"] = "MEASUREMENT_TIME_UNKNOWN"
    else:
        times = [parse_ts(row["measured_at"]) for row in inputs]
        left, right = inputs
        if any(not 0 <= (cutoff - at).total_seconds() <= request["max_age_seconds"] for at in times):
            result["reason"] = "STALE_MEASUREMENT"
        elif abs((times[0] - times[1]).total_seconds()) > request["max_skew_seconds"]:
            result["reason"] = "MISALIGNED_MEASUREMENTS"
        elif left["unit"] == right["unit"] and left.get("unit_epoch") != right.get("unit_epoch"):
            result["reason"] = "UNIT_EPOCH_MISMATCH_REQUIRES_EXPLICIT_CONVERSION"
        elif request["operation"] == "DIFFERENCE" and left["unit"] != right["unit"]:
            raise ValueError("difference requires identical explicit units")
        elif request["operation"] == "RATIO" and _number(right["value"]) == 0:
            result["reason"] = "ZERO_DENOMINATOR"
        else:
            with localcontext() as context:
                context.prec = 160
                context.rounding = ROUND_HALF_EVEN
                a, b = (_number(row["value"]) for row in inputs)
                result["value"] = str(a / b if request["operation"] == "RATIO" else a - b)
            result["unit"] = ("dimensionless" if left["unit"] == right["unit"] else left["unit"] + "/" + right["unit"]) if request["operation"] == "RATIO" else left["unit"]
            result["status"] = "AVAILABLE"
    result["report_id"] = digest(result)[:16]
    return result


def convert_series(protocol, request):
    fields(request, "value factor from_epoch to_epoch target_unit as_of max_age_seconds max_skew_seconds")
    for key in ("from_epoch", "to_epoch", "target_unit"):
        pattern = r"[A-Za-z0-9][A-Za-z0-9_.:/%-]{0,63}" if key == "target_unit" else r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}"
        if type(request[key]) is not str or not re.fullmatch(pattern, request[key]):
            raise ValueError("conversion units/epochs must be explicit bounded identifiers")
    if request["from_epoch"] == request["to_epoch"]:
        raise ValueError("conversion requires two distinct unit epochs")
    result = derived_series(protocol, {"left": request["value"], "right": request["factor"], "operation": "RATIO",
        **{k: request[k] for k in ("as_of", "max_age_seconds", "max_skew_seconds")}})
    value, factor = result["inputs"]
    if value is not None and value.get("unit_epoch") != request["from_epoch"]:
        raise ValueError("value does not declare the requested source epoch")
    if value is not None and factor is not None:
        if factor["unit"] != request["target_unit"] + "/" + value["unit"]:
            raise ValueError("factor unit must be exactly target_unit/source_unit")
        if _number(factor["value"]) <= 0:
            raise ValueError("unit conversion factor must be positive")
    if result["status"] == "AVAILABLE":
        with localcontext() as context:
            context.prec = 160
            result["value"] = str(_number(value["value"]) * _number(factor["value"]))
        result["unit"] = request["target_unit"]
    result.update(operation="EXPLICIT_UNIT_CONVERSION", from_epoch=request["from_epoch"], unit_epoch=request["to_epoch"],
                  limitation="Supplied vintage factor, measurement/knowledge cutoffs and declared units only. No raw row is relabeled or source authenticity certified.")
    result.pop("report_id")
    result["report_id"] = digest(result)[:16]
    return result
