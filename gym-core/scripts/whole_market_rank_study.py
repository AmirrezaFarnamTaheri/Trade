"""Pair archived spot ranking with a seeded, currency-matched placebo after paper execution costs."""

import argparse
import json
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from random import Random

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.market_models import decimal, instant
from gym.domain.model import iso
from gym.domain.rules import is_closed
from gym.domain.sim import CashBook, CostModel, market_order, sellable_quantity
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.historical_universe import (
    spot_entry_intervals,
    whole_window_spot_selection,
)
from gym.services.rules import RuleService


def _verified_row(line, key):
    value = json.loads(line)
    claimed = value.pop(key)
    if digest(value) != claimed:
        raise ValueError(f"market panel {key} mismatch")
    return {**value, key: claimed}


def read_panel(source):
    with source.open(encoding="utf-8-sig") as stream:
        header = _verified_row(stream.readline(2 * 1024 * 1024), "config_digest")
        if header["schema"] not in ("market-panel/1", "market-panel/2"):
            raise ValueError("unsupported market panel")
        start, end = instant(header["from"]), instant(header["to_exclusive"])
        step = timedelta(seconds=header["step_seconds"])
        if not timedelta(minutes=1) <= step <= timedelta(days=1) or not start < end:
            raise ValueError("invalid market panel clock")
        expected = (end - start - timedelta(microseconds=1)) // step + 1
        slices = []
        for index in range(expected):
            if index >= 500:
                raise ValueError("study exceeds 500 cutoffs")
            item = _verified_row(stream.readline(2 * 1024 * 1024), "slice_digest")
            if instant(item["cutoff"]) != start + index * step:
                raise ValueError("noncontiguous market-panel cutoffs")
            slices.append(item)
        if stream.read(1):
            raise ValueError("market panel has unexpected trailing slices")
    return header, slices


def _order(portal, rules_for, inst, book, side, cutoff, indicative, cost, quotas, *, entry_through=None):
    after, until = cutoff + cost.latency, cutoff + cost.max_wait
    end = until + timedelta(microseconds=1)
    if entry_through is not None:
        end = min(end, entry_through)
    if after >= end:
        return {"status": "NONFILL", "reason": "SPOT_WINDOW_ENDED"}
    for top in portal.iter_tops(inst.symbol, after, end):
        if qualified(top) and "CLOSED" not in top.flags:
            rules = rules_for(top.ts_avail)
            if not is_closed(rules, inst, top.ts_avail):
                return market_order(book, inst, side, Decimal(1), cutoff, Decimal(indicative), [top], 0, cost,
                                    portal.spec_at(inst.symbol, top.ts_avail), rules, quotas, f"{inst.symbol}/{side}")
    return {"status": "NONFILL", "reason": "SPOT_WINDOW_ENDED" if end <= until else "NO_QUALIFIED_QUOTE"}


def _round_trip(portal, rules_for, inst, row, later, at, exit_at, clip, cost, *, entry_through=None):
    if (row["base"], row["quote"]) != (inst.base, inst.quote):
        raise ValueError(f"archive instrument differs from panel for {inst.symbol}")
    book, quotas = CashBook({inst.quote: clip}), {}
    entry = _order(portal, rules_for, inst, book, "BUY", at, row["features"]["ask"], cost, quotas, entry_through=entry_through)
    if entry["status"] != "FILLED":
        return {"pnl": Decimal(0), "state": "ENTRY_NONFILL", "reason": entry["reason"], "entry": entry}
    bid = later["features"]["bid"] if later and later.get("exit_quote_available", later["eligibility"] == "READY") else None
    if bid and instant(later["receipt"]) >= exit_at:
        raise ValueError("exit quote was not available before the cutoff")
    exit_order = (_order(portal, rules_for, inst, book, "SELL", exit_at, bid, cost, quotas)
                  if bid else {"status": "NONFILL", "reason": "NO_ELIGIBLE_EXIT_DECISION"})
    remaining = book.get(inst.base)
    pnl = book.get(inst.quote) - clip
    receipts = {"entry": entry, "exit": exit_order, "postings": book.postings}
    if not remaining:
        return {"pnl": pnl, "state": "SETTLED", **receipts}
    if exit_order["status"] == "FILLED":
        filled_at = instant(exit_order["fill_time"])
        tail = sellable_quantity(remaining, Decimal(exit_order["price"]), portal.spec_at(inst.symbol, filled_at))
        if tail == 0:
            return {"pnl": pnl, "state": "DUST_VALUED_AT_ZERO", "remaining": remaining, **receipts}
    return {"pnl": None, "state": "UNSCORED_RESIDUAL", "remaining": remaining,
            "reason": exit_order.get("reason", "INSUFFICIENT_EXIT_CAPACITY"), **receipts}


def _candidate_groups(slice_, clips, step):
    index = {row["symbol"]: row for row in slice_["rows"]}
    cutoff = instant(slice_["cutoff"])
    groups = {quote: [] for quote in clips}
    for symbol in slice_["ranked_spot_symbols"]:
        row = index[symbol]
        if row["quote"] in groups:
            if (row["eligibility"] != "READY" or instant(row["receipt"]) >= cutoff
                    or instant(row["momentum_reference_receipt"]) >= cutoff - step
                    or row["products"]["spot"] is not True):
                raise ValueError("rank contains an ineligible quote")
            groups[row["quote"]].append(symbol)
    return index, groups


def _select(members, k, rng):
    return {"rank": {quote: symbols[:k] for quote, symbols in members.items()},
            "placebo": {quote: rng.sample(sorted(symbols), min(k, len(symbols))) for quote, symbols in members.items()}}


def _outcome(selections, clips, fills):
    cohort = [(fills[symbol], clips[quote]) for quote, symbols in selections.items() for symbol in symbols]
    states = Counter(result["state"] for result, _ in cohort)
    returns = [result["pnl"] / clip for result, clip in cohort if result["pnl"] is not None]
    net = sum(returns, Decimal(0)) / len(returns) if len(returns) == len(cohort) and returns else None
    return {"net": net, "states": dict(states), "unsettled": len(cohort) - len(returns)}


def _verified_windows(portal, header):
    if header["schema"] == "market-panel/1":
        return None
    begin, end = instant(header["from"]), instant(header["to_exclusive"])
    recorded = header["universe_selection"]
    watchlist = recorded.get("watchlist")
    symbols = header["requested_symbols"] if watchlist is None and header["mode"] == "CURATED" else None
    found = whole_window_spot_selection(portal.db, begin, end, venue=portal.venue, store=header["store"],
                                       symbols=symbols, watchlist=watchlist)
    if recorded != found:
        raise ValueError("archive catalogue differs from the saved panel")
    return spot_entry_intervals(found, begin, end)


def rank_study(db, header, slices, *, top_n, clips, seed, cost):
    """Compare matched fixed-clip decisions with one paired observation per cutoff."""
    if not 1 <= top_n <= 10 or not clips or len(clips) > 4 or len(slices) > 500:
        raise ValueError("study supports 1..10 selections, 1..4 quote currencies and at most 500 cutoffs")
    portal, rules = DataPortal(db, venue=header.get("venue", "wallex")), RuleService(db)
    cached_rules = {}

    def known(at):
        if at not in cached_rules:
            cached_rules[at] = rules.load(at)[1]
        return cached_rules[at]

    config = {"panel": header["config_digest"], "top_n_per_quote": top_n, "seed": seed,
              "clips": {key: str(value) for key, value in clips.items()}, "cost": cost.describe()}
    step = timedelta(seconds=header["step_seconds"])
    if not timedelta(0) < cost.latency <= cost.max_wait < step:
        raise ValueError("order latency and maximum wait must fit inside a panel step")
    blocks = []
    db.c.execute("BEGIN")
    try:
        windows = _verified_windows(portal, header)
        for current, following in pairwise(slices):
            at, exit_at = instant(current["cutoff"]), instant(following["cutoff"])
            entries, groups = _candidate_groups(current, clips, step)
            later = {item["symbol"]: item for item in following["rows"]}
            chosen = _select(groups, top_n, Random(digest([seed, iso(at)])))
            selected = {symbol for selection in chosen.values() for symbols in selection.values() for symbol in symbols}
            fills = {}
            for symbol in sorted(selected):
                row = entries[symbol]
                through = None if windows is None else next(
                    (end for begin, end in windows.get(symbol, ()) if begin <= at < end), None)
                if windows is not None and through is None:
                    raise ValueError("rank contains a market outside its spot window")
                fills[symbol] = _round_trip(portal, known, portal.instrument(symbol), row, later.get(symbol),
                                           at, exit_at, clips[row["quote"]], cost, entry_through=through)
            outcomes = {model: _outcome(selection, clips, fills) for model, selection in chosen.items()}
            a, b = (outcomes[key]["net"] for key in ("rank", "placebo"))
            blocks.append({"at": iso(at), "exit_decision": iso(exit_at),
                           "input_slices": [current["slice_digest"], following["slice_digest"]],
                           "eligible_by_quote": {key: len(value) for key, value in groups.items()},
                           "selections": chosen, "outcomes": outcomes, "outcomes_by_symbol": fills,
                           "rank_minus_cash": a, "rank_minus_placebo": a - b if a is not None and b is not None else None})
    finally:
        db.c.rollback()
    paired = [block for block in blocks if block["rank_minus_placebo"] is not None]
    with_fills = sum(any(model["states"].get("SETTLED") or model["states"].get("DUST_VALUED_AT_ZERO")
                         for model in block["outcomes"].values()) for block in paired)
    return {"schema": "whole-market-rank-study/1", "authority": "PAPER_ONLY", "evidence_stage": "DEVELOPMENT",
            "config": config, "config_digest": digest(config), "blocks": blocks, "paired_blocks": len(paired),
            "paired_blocks_with_fills": with_fills,
            "paired_mean_return_difference": (sum((b["rank_minus_placebo"] for b in paired), Decimal(0)) / len(paired)
                                              if paired else None),
            "basis": "Equal-weight returns on separate fixed-size clips, with identical quote-currency counts.",
            "missing_policy": "Entry nonfills hold cash. Unclosed tradable inventory makes the pair unscored.",
            "verdict": "DEVELOPMENT_ONLY"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("panel", type=Path)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261122)
    parser.add_argument("--usdt-clip", default="10")
    parser.add_argument("--tmn-clip", default="2700000")
    parser.add_argument("--participation", default="0.25")
    parser.add_argument("--fee-rate", default="0.001")
    parser.add_argument("--latency-ms", type=int, default=500)
    args = parser.parse_args()
    header, slices = read_panel(args.panel)
    clips = {"TMN": decimal(args.tmn_clip, positive=True), "USDT": decimal(args.usdt_clip, positive=True)}
    cost = CostModel(fee_rate=decimal(args.fee_rate), latency=timedelta(milliseconds=args.latency_ms),
                     max_participation=decimal(args.participation, positive=True))
    db = MarketDB(args.market_db, readonly=True)
    try:
        result = rank_study(db, header, slices, top_n=args.top, clips=clips, seed=args.seed, cost=cost)
        print(json.dumps(result, sort_keys=True, default=str, indent=2))
    finally:
        db.c.close()


if __name__ == "__main__":
    main()
