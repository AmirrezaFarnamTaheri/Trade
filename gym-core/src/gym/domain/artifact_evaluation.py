"""Artifact evaluation dispatcher separated from market_models primitives (breaks domain cycle)."""
from __future__ import annotations

import inspect
from decimal import localcontext

from .forecast_evaluation import forecast_calibration
from .market_models import (
    fields,
    financing,
    implied_fx,
    liquidity,
    position_sizing,
    roundtrip_spacing,
    trade_economics,
)
from .portfolio import cashflow_returns, portfolio_sizing


def evaluate_artifact(artifact):
    fields(artifact, "model parameters")
    models = {
        "liquidity": liquidity,
        "spacing": roundtrip_spacing,
        "fx": implied_fx,
        "financing": financing,
        "position-sizing": position_sizing,
        "trade-economics": trade_economics,
        "portfolio-sizing": portfolio_sizing,
        "cashflow-returns": cashflow_returns,
        "forecast-calibration": forecast_calibration,
    }
    name = artifact["model"]
    if not isinstance(name, str) or name not in models:
        raise ValueError("unknown paper market model")
    function = models[name]
    fields(artifact["parameters"], " ".join(inspect.signature(function).parameters))
    with localcontext() as context:
        context.prec = 160
        result = function(**artifact["parameters"])
    return {
        "mode": "PAPER_ONLY",
        "funded_authority": False,
        "order_submitted": False,
        "model": name,
        "result": result,
    }
