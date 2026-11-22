"""Freeze one causal market ranking before shared cash is allocated at each close."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext
from random import Random

from ..domain.bars import qualified
from ..domain.market_models import decimal, fields
from ..domain.model import iso
from ..domain.rules import is_closed
from ..domain.strategy import digest


class PortfolioRank:
    def __init__(self, value, step):
        fields(value, "method top_n_per_quote min_breadth seed")
        if value["method"] not in ("momentum", "placebo"):
            raise ValueError("rank method must be momentum or placebo")
        n, seed = value["top_n_per_quote"], value["seed"]
        if type(n) is not int or not 1 <= n <= 100 or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("rank selection needs 1..100 symbols per quote and an unsigned 32-bit seed")
        self.minimum = decimal(value["min_breadth"], "min_breadth")
        if self.minimum > 1:
            raise ValueError("min_breadth must be at most one")
        self.config, self.step = dict(sorted(value.items())), step
        self.tops, self.previous, self.events = {}, {}, []
        self.selected = set()
        self.last_cutoff = None

    def advance(self, cutoff, instruments, rules, active):
        """Use strictly prior book receipts on adjacent decision cutoffs."""
        groups = defaultdict(list)
        available, positive = {}, 0
        previous = self.previous if self.last_cutoff == cutoff - self.step else {}
        rows = []
        for symbol, top in sorted(self.tops.items()):
            inst = instruments[symbol]
            age = cutoff - top.ts_avail
            if not timedelta(0) < age <= timedelta(seconds=120) or not qualified(top):
                continue
            if "CLOSED" in top.flags or is_closed(rules, inst, cutoff):
                continue
            if top.ask_qty is None or not top.ask_qty.is_finite() or top.ask_qty <= 0:
                continue
            available[symbol] = top
            if symbol not in previous or symbol not in active:
                continue
            prior = previous[symbol]
            with localcontext() as ctx:
                ctx.prec = 34
                momentum = ((top.bid + top.ask) / (prior.bid + prior.ask) - 1) * 10_000
                score = momentum - top.spread_bps
            groups[inst.quote].append((score, symbol))
            rows.append([symbol, iso(top.ts_avail), iso(prior.ts_avail), str(score)])
            positive += momentum > 0
        self.previous, self.last_cutoff = available, cutoff
        with localcontext() as ctx:
            ctx.prec = 80
            breadth_passed = bool(rows) and Decimal(positive) >= self.minimum * len(rows)
            ctx.prec = 28
            breadth = Decimal(positive) / len(rows) if rows else None
        selected = {}
        if breadth_passed:
            for quote, group in sorted(groups.items()):
                limit = self.config["top_n_per_quote"]
                if self.config["method"] == "momentum":
                    selected[quote] = [symbol for _, symbol in sorted(group, key=lambda row: (row[0].copy_negate(), row[1]))[:limit]]
                else:
                    rng = Random(digest([self.config["seed"], iso(cutoff), quote]))
                    selected[quote] = rng.sample(sorted(symbol for _, symbol in group), min(limit, len(group)))
        self.selected = {symbol for symbols in selected.values() for symbol in symbols}
        self.events.append({"at": iso(cutoff), "eligible": rows, "selected": selected,
                            "breadth": str(breadth) if breadth is not None else None, "blocked_buys": []})

    def filter_entry(self, symbol, action, fraction, reasons):
        if action != "BUY_REQUEST" or symbol in self.selected:
            return action, fraction, reasons
        if self.events:
            self.events[-1]["blocked_buys"].append(symbol)
        return "ABSTAIN_PORTFOLIO_RANK", Decimal(0), ("RANK_GATE",)

    def checkpoint(self):
        def receipts(tops):
            return {s: (top.ts_avail, top.bid, top.ask, top.ask_qty, sorted(top.flags)) for s, top in tops.items()}

        return {"last_cutoff": self.last_cutoff, "previous": receipts(self.previous), "tops": receipts(self.tops),
                "selected": sorted(self.selected), "events": self.events}
