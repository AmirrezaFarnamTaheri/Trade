"""Rule service: the only writer of the regulation ledger. Shared by API and gymctl."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ..adapters.store import MarketDB
from ..domain.model import InstrumentId, iso
from ..domain.rules import PRESETS, effective_status, evaluate, next_change, parse_rule

CHECKS = (("entry", "BUY", "ENTRY"), ("exit", "SELL", "EXIT"))


class RuleService:
    def __init__(self, db: MarketDB):
        self.db = db

    def load(self, at: datetime | None = None):
        version, docs = self.db.rules_as_of(at)
        rules, quarantined = [], []
        for d in docs.values():
            try:
                rules.append(parse_rule(d))
            except ValueError as e:
                quarantined.append({"id": d.get("id"), "error": str(e), "body": d})
        return version, rules, quarantined

    def put(self, d: dict, now: datetime, op: str = "edit", actor: str = "operator") -> int:
        parse_rule(d)  # reject invalid edits outright; only imports may land in quarantine
        exists = d["id"] in self.db.rules_as_of()[1]
        return self.db.put_rule(d, op if exists or op != "edit" else "add", actor, now)

    def _current(self, rule_id: str) -> dict:
        docs = self.db.rules_as_of()[1]
        if rule_id not in docs:
            raise ValueError(f"unknown rule {rule_id!r}")
        return docs[rule_id]

    def disable(self, rule_id: str, now: datetime, actor: str = "operator") -> int:
        return self.db.put_rule({**self._current(rule_id), "disabled": True}, "disable", actor, now)

    def rollback(self, rule_id: str, seq: int, now: datetime, actor: str = "operator") -> int:
        self._current(rule_id)
        old = next((e for e in self.db.rule_events(rule_id) if e["seq"] == seq), None)
        if old is None:
            raise ValueError(f"rule {rule_id!r} has no event #{seq}")
        return self.db.put_rule(old["body"], "rollback", actor, now)

    def import_(self, docs: list, now: datetime, op: str = "import", actor: str = "operator") -> dict:
        if not isinstance(docs, list) or not all(isinstance(d, dict) and d.get("id") for d in docs):
            raise ValueError("import expects a JSON list of rule objects, each with an id")
        bad = []
        for d in docs:
            try:
                parse_rule(d)
            except ValueError as e:
                bad.append({"id": d["id"], "error": str(e)})
            self.db.put_rule(d, op, actor, now)
        return {"imported": len(docs), "quarantined": bad}

    def preset(self, name: str, now: datetime, actor: str = "operator") -> dict:
        if name not in PRESETS:
            raise ValueError(f"unknown preset {name!r}; have {sorted(PRESETS)}")
        return self.import_(PRESETS[name], now, "preset:" + name, actor)

    def export(self) -> list[dict]:
        return list(self.db.rules_as_of()[1].values())

    def check(self, inst: InstrumentId, side: str, intent: str, now: datetime, *, at_rules: datetime | None = None,
              used: Decimal = Decimal(0)) -> dict:
        version, rules, _ = self.load(at_rules)
        v = evaluate(rules, inst, side, intent, now, used=used, version=version)
        return {"allowed": v.allowed, "blockers": list(v.blockers), "warnings": list(v.warnings),
                "quota_remaining": None if v.quota_remaining is None else str(v.quota_remaining),
                "ruleset_version": version, "at": iso(now),
                "next_change": iso(next_change(rules, inst, side, intent, now, used=used, version=version))}

    def act(self, inst: InstrumentId, now: datetime) -> dict:
        """Pair-scoped 'When can I act?': entry (buy) and exit (sell) right now, and when that flips."""
        return {name: self.check(inst, side, intent, now) for name, side, intent in CHECKS}

    def listing(self, now: datetime, insts: list[InstrumentId]) -> dict:
        version, rules, quarantined = self.load()
        out = {"version": version, "rules": [], "quarantined": quarantined}
        for r in rules:
            if r.disabled:
                state = "disabled"
            elif now < r.effective_from:
                state = "scheduled"
            elif r.effective_until and now >= r.effective_until:
                state = "expired"
            else:
                state = "stale" if effective_status(r, now) == "STALE" else "active"
            blocks = sorted({f"{i.symbol} {n}" for i in insts for n, side, intent in CHECKS
                             if evaluate([r], i, side, intent, now).blockers})
            out["rules"].append({"state": state, "blocks_now": blocks, "body": self._current(r.id),
                                 "history": [{k: e[k] for k in ("seq", "ts", "op", "actor")} for e in self.db.rule_events(r.id)]})
        return out
