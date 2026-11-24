"""JSONL persistence adapter for versioned Track B mix-journal-v2 entries."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from ..domain.signal_gatekeeper import MixJournalV2Entry


def _existing_day_symbol_keys(path: Path) -> set[tuple[str, str]]:
    if not path.is_file():
        return set()
    keys: set[tuple[str, str]] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        as_of = str(item.get("as_of") or "")[:10]
        sym = str(item.get("symbol") or "")
        if as_of and sym:
            keys.add((as_of, sym))
    return keys


def append_mix_journal_v2(path: Path, entry: MixJournalV2Entry) -> bool:
    """Append one MixJournalV2Entry durably (fsynced), skipping same-day duplicate (date, symbol)."""
    if path.name == "mix-journal.jsonl":
        raise ValueError("never overwrite v1 control mix-journal.jsonl; write to mix-journal-v2.jsonl")
    payload = asdict(entry)
    day_key = (str(payload.get("as_of") or "")[:10], str(payload.get("symbol") or ""))
    if day_key[0] and day_key[1] and day_key in _existing_day_symbol_keys(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return True
