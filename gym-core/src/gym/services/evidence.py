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
    found = re.match(r"\*\*(PASS|FAIL)([^*]*)\*\*", result)
    return "OPEN" if not found else "NARROW_PASS" if "narrowly" in found.group(2) else found.group(1)


def trials(path: Path = TRIAL_LOG) -> list[dict]:
    if not path.exists():
        return []
    rows = ([cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in path.read_text(encoding="utf-8").splitlines() if REGISTERED_ROW.match(line))
    return [{"id": row[0], "registered": row[1], "hypothesis": row[2], "verdict": _verdict(row[5])}
            for row in rows if len(row) == 6]


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


def evidence(root: Path | None, path: Path = TRIAL_LOG) -> dict:
    rows = trials(path)
    count = {name: sum(1 for row in rows if row["verdict"] == name) for name in ("FAIL", "NARROW_PASS", "PASS", "OPEN")}
    return {"state": "READY" if rows else "NO_TRIAL_LOG", "trials": rows, "tally": {"registered": len(rows), **count},
            "forward": forward(root) if root is not None else None, "funded_authority": False}
