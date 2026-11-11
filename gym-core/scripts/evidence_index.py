"""Index the acceptance evidence the docs cite under .pi/, without committing the receipts themselves.

The receipts stay out of the repository (they can hold host details), but each citation resolves to a digest
in the tracked evidence/INDEX.json: a file's SHA-256, or for a folder the SHA-256 of its sorted
"path <tab> sha256 <tab> bytes" manifest. Anyone holding the receipts can check them; a docs test fails when a
citation has no entry.

    uv run --no-sync python scripts/evidence_index.py            write evidence/INDEX.json from .pi/
    uv run --no-sync python scripts/evidence_index.py --verify   recompute and compare
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "gym-core" / "docs"
INDEX = REPO / "evidence" / "INDEX.json"
CITATION = re.compile(r"\.pi/([A-Za-z0-9_./-]+)")


def citations() -> list[str]:
    found = set()
    for doc in DOCS.glob("*.md"):
        for raw in CITATION.findall(doc.read_text("utf-8")):
            found.add(raw.rstrip("./"))
    return sorted(found)


def file_digest(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def entry(path: Path) -> dict:
    if path.is_file():
        return {"kind": "file", "sha256": file_digest(path), "files": 1, "bytes": path.stat().st_size}
    files = sorted(p for p in path.rglob("*") if p.is_file())
    lines = [f"{p.relative_to(path).as_posix()}\t{file_digest(p)}\t{p.stat().st_size}" for p in files]
    return {"kind": "folder", "sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
            "files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def build(root: Path) -> dict:
    out = {}
    for cited in citations():
        path = root / cited
        out[cited] = entry(path) if path.exists() else {"kind": "missing"}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO / ".pi")
    args = parser.parse_args(argv)
    current = build(args.root)
    if args.verify:
        stored = json.loads(INDEX.read_text("utf-8"))["entries"]
        bad = [k for k in sorted(set(stored) | set(current)) if stored.get(k) != current.get(k)]
        print("OK" if not bad else "MISMATCH: " + ", ".join(bad))
        return 1 if bad else 0
    INDEX.parent.mkdir(exist_ok=True)
    with open(INDEX, "w", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps({"schema": "evidence-index/1", "entries": current}, indent=2, sort_keys=True) + "\n")
    missing = [k for k, v in current.items() if v["kind"] == "missing"]
    print(f"{len(current)} citations indexed" + (f"; missing: {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
