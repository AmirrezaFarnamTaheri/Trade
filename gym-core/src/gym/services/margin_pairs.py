"""Item 27: retrospective paired long/short margin paper replay, no venue effects.

Two separately retained public margin PREVIEW receipts provide distinct long
and short terms. Both legs replay inside one immutable local market snapshot.
This is NOT executable pairs trading, margin eligibility or profit evidence.
"""
from datetime import timedelta
from decimal import Decimal, localcontext

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.cross_market_models import ar1_half_life
from ..domain.margin import replay_margin
from ..domain.market_models import decimal, fields
from ..domain.model import iso, parse_ts
from ..domain.rules import is_closed
from ..domain.strategy import digest
from .collector import now_utc
from .data_portal import DataPortal
from .margin import _save, load_receipt
from .rules import RuleService


def _spread_statistics(long_points, short_points, skew_seconds):
    """Align earlier known public books with bounded skew; never interpolate."""
    left = [(top, closed) for top, closed in long_points]
    right = [(top, closed) for top, closed in short_points]
    series, j, last = [], 0, None
    with localcontext() as context:
        context.prec = 90
        for top, closed in left:
            while j < len(right) and right[j][0].ts_avail <= top.ts_avail:
                last = right[j]
                j += 1
            if last is None or closed or last[1] or not qualified(top) or not qualified(last[0]):
                continue
            if (top.ts_avail - last[0].ts_avail).total_seconds() > skew_seconds:
                continue
            mid_long = (top.bid + top.ask) / 2
            mid_short = (last[0].bid + last[0].ask) / 2
            series.append((top.ts_avail, (mid_long / mid_short).ln()))
        n = len(series)
        result = {"status": "INSUFFICIENT_SAMPLES", "aligned_samples": n,
                  "half_life_bars": None, "phi": None,
                  "training_std": None, "holdout_std": None,
                  "holdout_to_training_std": None, "independent_oos": False}
        if n < 12:
            return result
        values = [value for _, value in series]
        fit = ar1_half_life(values)
        split = n * 7 // 10
        train, hold = values[:split], values[split:]
        def std(values):
            """Population dispersion of recorded spreads, not an executable quote."""
            mean = sum(values, Decimal(0)) / len(values)
            return (sum(((x - mean)**2 for x in values), Decimal(0)) /
                    len(values)).sqrt()
        a, b = std(train), std(hold)
        result.update(half_life_bars=fit["half_life_bars"],
                      phi=fit["phi"], training_std=str(+a),
                      holdout_std=str(+b),
                      holdout_to_training_std=str(+(b / a)) if a > 0 else None,
                      status=("DESCRIPTIVE_ONLY" if a > 0 else "UNIDENTIFIABLE"),
                      internal_split="CHRONOLOGICAL_70_30",
                      caveat="Log-price spread is non-tradable; this is not a cointegration or stationarity proof.")
        return result


def margin_pairs_research(root, request, *, store):
    """Replay two approved-*paper* preview terms; refuse unknown or mismatched legs.

    An actual account, loan, short availability or execution permission is never
    inferred from the local metadata; public quote observations are not fills.
    """
    fields(request, "long_preview_id short_preview_id from to exit_fee_rate holding_seconds max_skew_seconds")
    if store != "live":
        raise ValueError("pairs margin replay requires the live public-observation store")
    skew = request["max_skew_seconds"]
    if type(skew) is not int or not 0 <= skew <= 120:
        raise ValueError("invalid pair quote skew")
    if request["long_preview_id"] == request["short_preview_id"]:
        raise ValueError("paired margin requires two distinct preview receipts")
    start, end = parse_ts(request["from"]), parse_ts(request["to"])
    if not start < end <= now_utc() or end - start > timedelta(days=31):
        raise ValueError("paired margin requires a bounded historical window")
    long_preview = load_receipt(root, request["long_preview_id"], "PREVIEW")
    short_preview = load_receipt(root, request["short_preview_id"], "PREVIEW")
    if start < max(parse_ts(long_preview["received_at"]), parse_ts(short_preview["received_at"])):
        raise ValueError("margin terms must be known before the first paper quote")
    lrule, srule = long_preview["rule"], short_preview["rule"]
    if (long_preview["terms"]["side"] != "long" or short_preview["terms"]["side"] != "short"
            or lrule["symbol"] == srule["symbol"] or lrule["quote"] != srule["quote"]
            or lrule["quote"] not in ("TMN", "USDT")):
        raise ValueError("margin pair needs distinct long and short legs in the same quote unit")
    from pathlib import Path

    path = Path(root) / "market.db"
    if not path.is_file() or path.is_symlink():
        raise ValueError("pair replay needs a regular, existing market store")
    db = MarketDB(path, readonly=True)
    try:
        db.c.execute("BEGIN")
        portal, rules = DataPortal(db), RuleService(db)
        legs = []
        for rule, preview in ((lrule, long_preview), (srule, short_preview)):
            symbol = rule["symbol"]
            count = db.c.execute(
                "SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? "
                "AND ts_avail>=? AND ts_avail<? LIMIT 5001)",
                ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0]
            if count > 5000:
                raise ValueError("margin pair requires at most 5000 receipts per leg")
            instrument = portal.instrument(symbol)
            tops = portal.tops(symbol, start, end)
            points = [(top, is_closed(rules.load(top.ts_avail)[1], instrument, top.ts_avail))
                      for top in tops]
            outcome = replay_margin(preview["terms"], rule, points, end,
                                    request["exit_fee_rate"], request["holding_seconds"])
            legs.append((points, outcome))
        spreads = _spread_statistics(legs[0][0], legs[1][0], skew)
        data_digest = digest([[(iso(top.ts_avail), str(top.bid), str(top.ask),
                               str(top.bid_qty), str(top.ask_qty), closed)
                              for top, closed in leg[0]] for leg in legs])
    finally:
        db.c.rollback()
        db.c.close()
    with localcontext() as context:
        context.prec = 90
        both_closed = all(leg[1]["state"] == "CLOSED" for leg in legs)
        beginning = sum((decimal(preview["terms"]["collateral"]["value"], "collateral", positive=True)
                         for preview in (long_preview, short_preview)), Decimal(0))
        net = (sum((decimal(outcome["cash_quote"], "settled cash")
                    for _, outcome in legs), Decimal(0)) - beginning) if both_closed else None
        quote = lrule["quote"]
        result = {"kind": "PAIR_REPLAY", "pair_model_schema": "margin-pairs/1",
                  "long_preview_id": long_preview["run_id"],
                  "short_preview_id": short_preview["run_id"],
                  "long_symbol": lrule["symbol"], "short_symbol": srule["symbol"],
                  "quote": quote, "from": iso(start), "to_exclusive": iso(end),
                  "long": legs[0][1], "short": legs[1][1],
                  "status": "CLOSED_PAPER_PAIR" if both_closed else "NOT_COMPARABLE",
                  "net_quote": str(+net) if net is not None else None,
                  "net_usdt": str(+net) if net is not None and quote == "USDT" else None,
                  "spread_stability": spreads, "observations": [len(x[0]) for x in legs],
                  "data_digest": data_digest, "store": store,
                  "independent_evidence": False, "automatic_application": False,
                  "limitations": [
                      "Paper margin loans and fills are hypothetical; preview metadata does not prove live account eligibility.",
                      "Distinct long/short outcomes are modeled independently, not a live cross-margin reservation.",
                      "Spread log-ratio half-life requires recorded aligned quotes and is descriptive, not proof of cointegration.",
                      "No USDT-valued performance is inferred for TMN without a causal per-fill FX conversion.",
                      "Only closed, fully settled paper legs can produce a combined quote P/L.",
                  ]}
        return _save(root, result)
