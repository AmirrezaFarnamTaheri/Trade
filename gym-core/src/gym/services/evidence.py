"""The governing question's current answer: every registered trial and the forward paper record.

Read-only. The trial log is the single source; this parses its table so the workspace shows the same rows.
"""
import re
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from .allocation import journal

TRIAL_LOG = Path(__file__).resolve().parents[3] / "docs" / "trial-log.md"
# A registered trial: a lower-case hyphenated name, then the registration date.
REGISTERED_ROW = re.compile(r"\| [a-z0-9]+(?:-[a-z0-9]+)* \| \d{4}-\d{2}-\d{2} \|")


def _verdict(result: str) -> str:
    found = re.match(r"\*\*(PASS|FAIL|ABORTED|SUPERSEDED)([^*]*)\*\*", result)
    return "OPEN" if not found else "NARROW_PASS" if "narrowly" in found.group(2) else found.group(1)


def trials(path: Path = TRIAL_LOG) -> list[dict]:
    if not path.exists():
        return []
    rows = ([cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in path.read_text(encoding="utf-8").splitlines() if REGISTERED_ROW.match(line))
    return [{"id": row[0], "registered": row[1], "hypothesis": row[2], "verdict": _verdict(row[5]),
             "probability": _final_probability(row[5])} for row in rows if len(row) == 6]


def _final_probability(result: str) -> float | None:
    """The probability from the last stage a trial reached: a held-out probability outranks a ranking score."""
    held = re.findall(r"probability[^0-9]{0,40}?([01]\.\d{3})", result)
    ranking = re.findall(r"deflated[^0-9]{0,40}?([01]\.\d{3})", result)
    return float(held[-1]) if held else float(ranking[0]) if ranking else None


def programme(rows: list[dict]) -> dict | None:
    """Benjamini-Hochberg across every completed trial: how likely the best result is luck, given everything tried.

    A trial with no stated probability (an early screen that failed on counts or costs) enters as p = 1.
    """
    done = [row for row in rows if row["verdict"] != "OPEN"]
    if not done:
        return None
    from ..domain.multiple_testing import bh_q
    p = sorted((1 - row["probability"] if row["probability"] is not None else 1.0, row["id"]) for row in done)
    q = bh_q({name: value for value, name in p})
    best = p[0][1]
    return {"completed": len(p), "best": best, "best_probability": round(1 - p[0][0], 3), "best_q": round(q[best], 3)}


def forward(root: Path) -> dict | None:
    """The forward paper journal, one row per decided day; None before the first decision."""
    entries = journal(root)
    if not entries:
        return None
    last = entries[-1]
    start, equity, base = (Decimal(value) for value in
                           (entries[0]["equity"], last["equity"], last["holdings"]["base"]))
    if not all(value.is_finite() for value in (start, equity, base)):
        raise ValueError("invalid forward journal amount")
    with localcontext() as context:
        context.prec = max(28, max(start.adjusted(), equity.adjusted())
                           - min(start.as_tuple().exponent, equity.as_tuple().exponent) + 2)
        net = format(equity - start, "f")
        fees = format(sum((Decimal(row["fill"]["fee"]) for row in entries if row.get("fill")), Decimal(0)), "f")
        closes = [row["decision"].get("close") for row in entries if row["decision"].get("close")]
        # What 1,000 USDT put into the coin on the first decided day would be worth at the last close (no fees).
        hold_net = format(start * Decimal(str(closes[-1])) / Decimal(str(closes[0])) - start, ".2f") if len(closes) > 1 else None
    days = sorted({row["day"][:10] for row in entries if row.get("day")})
    span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1 if days else 0
    return {"symbol": last["symbol"], "started": entries[0]["at"], "latest": last["at"], "latest_day": days[-1] if days else None,
            "days": len(entries), "missing_days": span - len(days),
            "start_equity": entries[0]["equity"], "equity": last["equity"], "net": net, "hold_net": hold_net, "fees": fees,
            "in_market": base > 0, "trades": sum(1 for row in entries if row.get("fill")),
            "withheld": sum(1 for row in entries if row["status"] != "READY")}


def forward_mix(root: Path) -> dict | None:
    """The passive mix's forward paper record on Wallex prices; None before its first entry."""
    from .mix_journal import journal as mix_entries
    entries = [e for e in mix_entries(root) if e.get("status") == "READY"]
    if not entries:
        return None
    start, last = Decimal(1000), entries[-1]
    equity = Decimal(last["equity"])
    return {"started": entries[0]["day"][:10], "latest": last["at"], "days": len(entries), "equity": str(equity.quantize(Decimal("0.01"))),
            "net_pct": str(((equity / start - 1) * 100).quantize(Decimal("0.01"))),
            "invested_pct": str(((1 - Decimal(last["usdt"]) / equity) * 100).quantize(Decimal("0.1"))) if equity else None}


def forward_breadth(root: Path) -> dict | None:
    """The breadth-trend forward paper record on Wallex prices; None before its first entry."""
    from .breadth_journal import journal as breadth_entries
    entries = [e for e in breadth_entries(root) if e.get("status") == "READY"]
    if not entries:
        return None
    start, last = Decimal(1000), entries[-1]
    equity = Decimal(last["equity"])
    return {
        "started": entries[0]["day"][:10],
        "latest": last["at"],
        "latest_day": last["day"][:10],
        "days": len(entries),
        "equity": str(equity.quantize(Decimal("0.01"))),
        "net_pct": str(((equity / start - 1) * 100).quantize(Decimal("0.01"))),
        "breadth": last.get("breadth"),
        "gate_open": bool(last.get("gate_open")),
        "universe_size": len(last.get("universe") or []),
    }


def evidence(root: Path | None, path: Path = TRIAL_LOG) -> dict:
    from .trial_governance import (
        MAX_CONCURRENT_TRIALS,
        PACKAGED_OPEN_FORWARD,
        active_sqlite_trials,
        journal_continuity_report,
    )

    rows = trials(path)
    count = {name: sum(1 for row in rows if row["verdict"] == name) for name in ("FAIL", "NARROW_PASS", "PASS", "OPEN")}
    for terminal in ("ABORTED", "SUPERSEDED"):
        if value := sum(row["verdict"] == terminal for row in rows):
            count[terminal] = value
    forward_open = count["OPEN"] if path.is_file() or path != TRIAL_LOG else len(PACKAGED_OPEN_FORWARD)
    sqlite_open = len(active_sqlite_trials(root, "live")) if root is not None else 0
    active = forward_open + sqlite_open
    return {
        "state": "READY" if rows else "NO_TRIAL_LOG",
        "trials": rows,
        "tally": {"registered": len(rows), **count},
        "trial_budget": {"active": active, "forward_open": forward_open, "local_live_open": sqlite_open,
                         "limit": MAX_CONCURRENT_TRIALS, "remaining": max(0, MAX_CONCURRENT_TRIALS - active)},
        "checkpoint": {
            "date": "2027-02-08",
            "breadth_score_after": "2027-05-19",
            "evidence_stage": "MODELED_PAPER_ONLY",
            "independent_final_evidence": False,
            "host_status": "DISARMED_NOT_CERTIFIED",
            "backup_policy_exception": "OFF_MACHINE_CANCELED_2026_11_16",
        },
        "forward": forward(root) if root is not None else None,
        "forward_mix": forward_mix(root) if root is not None else None,
        "forward_breadth": forward_breadth(root) if root is not None else None,
        "journal_continuity": journal_continuity_report(root) if root is not None else None,
        "programme": programme(rows),
        "funded_authority": False,
    }
