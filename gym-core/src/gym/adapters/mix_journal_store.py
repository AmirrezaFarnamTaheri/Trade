"""JSONL persistence adapter for versioned Track B mix-journal-v2 entries."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..domain.signal_gatekeeper import MixJournalV2Entry


def append_mix_journal_v2(path: Path, entry: MixJournalV2Entry) -> None:
    """Append one MixJournalV2Entry as sorted JSONL while refusing to overwrite v1 control."""
    if path.name == "mix-journal.jsonl":
        raise ValueError("never overwrite v1 control mix-journal.jsonl; write to mix-journal-v2.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
