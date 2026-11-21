"""Safe exact-decimal CSV export preventing spreadsheet formula injection and misleading currencies (O020)."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def sanitize_cell(value) -> str:
    """Preserve exact numeric Decimals while neutralizing spreadsheet formula triggers on strings."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return ""
    # Allow signed finite numeric strings (e.g. "-12.50") without quoting; neutralize all other formula prefixes.
    if text[0] in ("+", "-"):
        try:
            parsed = Decimal(text)
            if parsed.is_finite():
                return text
        except InvalidOperation:
            pass
    if text[0] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def safe_export_filename(name: str) -> str:
    """Reject directory traversal or unsafe characters in CSV export filenames."""
    if not isinstance(name, str) or not _SAFE_FILENAME.fullmatch(name) or ".." in name or not name.endswith(".csv"):
        raise ValueError("unsafe CSV export filename")
    return name


def export_csv(rows: list[dict], fieldnames: list[str], *, currency: str) -> str:
    """Serialize rows to UTF-8 CSV with explicit currency metadata and formula-injection protection."""
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z0-9]{2,12}", currency):
        raise ValueError("CSV export requires an explicit uppercase currency code")
    if not fieldnames:
        raise ValueError("CSV export requires non-empty fieldnames")
    buf = io.StringIO()
    cols = list(fieldnames) if "currency" in fieldnames else [*fieldnames, "currency"]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        out = {col: sanitize_cell(row.get(col, currency if col == "currency" else "")) for col in cols}
        writer.writerow(out)
    return buf.getvalue()
