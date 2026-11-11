"""Executor-ledger head anchors kept beside the backups, away from the ledger's own host.

A hash chain shows an edit in the middle, but not a truncation or a wholesale replacement by someone who can
write the ledger file: a shorter or rebuilt chain is still internally consistent. Each verified backup appends
(sequence, head hash) to `ledger-anchors.jsonl` in the backup folder. Every later ledger must still contain each
anchored event at its sequence with that hash; a ledger that does not is refused before old bundles are rotated.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

ANCHORS = "ledger-anchors.jsonl"
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class AnchorViolation(ValueError):
    """The ledger no longer contains an event an earlier backup anchored: truncated or replaced."""


def read_anchors(folder: Path) -> list[dict]:
    path = folder / ANCHORS
    if not path.is_file():
        return []
    anchors = []
    for number, line in enumerate(path.read_text("ascii").splitlines(), 1):
        try:
            row = json.loads(line)
            if type(row.get("sequence")) is not int or row["sequence"] < 0 or not _HASH.fullmatch(row.get("head_hash", "")):
                raise ValueError
        except (ValueError, AttributeError):
            raise AnchorViolation(f"{ANCHORS} line {number} is malformed") from None
        anchors.append(row)
    return anchors


def _hashes(ledger: Path, sequences: set[int]) -> dict[int, str]:
    uri = "file:" + quote(str(ledger.resolve()), safe="/:") + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
        top = db.execute("SELECT coalesce(max(sequence), 0) FROM ledger_events").fetchone()[0]
        found = {seq: bytes(h).hex() for seq, h in db.execute(
            f"SELECT sequence, event_hash FROM ledger_events WHERE sequence IN ({','.join('?' * len(sequences))})",
            sorted(sequences))} if sequences else {}
    found[-1] = top  # the current length, under a key no real sequence uses
    return found


def verify(folder: Path, ledger: Path) -> dict:
    """Check `ledger` (a quiescent copy) against every anchor; raise AnchorViolation on the first mismatch."""
    anchors = read_anchors(folder)
    real = {a["sequence"] for a in anchors if a["sequence"] > 0}
    hashes = _hashes(ledger, real)
    for anchor in anchors:
        seq = anchor["sequence"]
        if seq == 0:
            continue
        if seq > hashes[-1]:
            raise AnchorViolation(f"ledger ends at sequence {hashes[-1]} but a backup anchored sequence {seq}: truncated")
        if hashes.get(seq) != anchor["head_hash"]:
            raise AnchorViolation(f"event {seq} differs from the anchored hash: the ledger was replaced or rewritten")
    return {"anchors": len(anchors), "ledger_sequence": hashes[-1]}


def append(folder: Path, sequence: int, head_hash: str, at: str) -> None:
    anchors = read_anchors(folder)
    if anchors and (anchors[-1]["sequence"], anchors[-1]["head_hash"]) == (sequence, head_hash):
        return  # unchanged ledger, nothing new to anchor
    with open(folder / ANCHORS, "a", encoding="ascii", newline="\n") as out:
        out.write(json.dumps({"sequence": sequence, "head_hash": head_hash, "at": at}, sort_keys=True) + "\n")
