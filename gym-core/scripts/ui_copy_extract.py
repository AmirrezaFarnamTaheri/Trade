"""Collect every English/Persian UI string pair into one sheet for a native-speaker review.

The UI keeps copy in several shapes: the shared vocabulary (key: ["en", "fa"]), self-contained modules that call
text('en', 'fa'), inline `fa ? 'fa' : 'en'` choices, and models.js's own en/fa dictionaries. This finds each
shape, writes ui-copy-review.csv (file, line, key, English, Persian), and lists any Persian line it could not
pair so nothing escapes review.

    uv run --no-sync python scripts/ui_copy_extract.py [--out ui-copy-review.csv]
"""
import argparse
import csv
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src" / "gym" / "ui"
PERSIAN = re.compile("[\u0600-\u06ff]")
S = r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`((?:[^`\\$]|\\.)*)`)"""  # one JS string literal, any quote


def literal(match, start):
    return next(g for g in match.groups()[start:start + 3] if g is not None)


VOCAB = re.compile(r"(\w+): \[" + S + r", " + S + r"\]")
# Table rows such as research.js actions: 'shadow-open': ['English', 'Persian', 'fields'].
TABLE = re.compile(r"""(?:'([\w-]+)':|(\w+):|\w+\['([\w-]+)'\]\s*=)\s*\[""" + S + r",\s*" + S + r"\s*,")
TEXT_CALL = re.compile(r"text\(" + S + r",\s*" + S + r"\)")
FA_FIRST = re.compile(r"fa\s*\?\s*" + S + r"\s*:\s*" + S)
LANG_FA = re.compile(r"""lang\s*===\s*['"]fa['"]\s*\?\s*""" + S + r"\s*:\s*" + S)
DICT_ENTRY = re.compile(r"(\w+): " + S)


def extract(path: Path):
    rows, unpaired = [], []
    lines = path.read_text("utf-8").splitlines()
    english_dict = {}
    if path.name == "models.js":  # en: {...} then fa: {...} with the same keys
        text = path.read_text("utf-8")
        en_block = re.search(r"\ben:\s*\{(.*?)\},?\s*\n\s*fa:", text, re.DOTALL)
        if en_block:
            english_dict = {m.group(1): literal(m, 1) for m in DICT_ENTRY.finditer(en_block.group(1))}
    for number, line in enumerate(lines, 1):
        found = False
        for match in VOCAB.finditer(line):
            rows.append((path.name, number, match.group(1), literal(match, 1), literal(match, 4)))
            found = True
        for match in TABLE.finditer(line):
            rows.append((path.name, number, match.group(1) or match.group(2) or match.group(3),
                         literal(match, 3), literal(match, 6)))
            found = True
        for match in TEXT_CALL.finditer(line):
            rows.append((path.name, number, "", literal(match, 0), literal(match, 3)))
            found = True
        for pattern in (FA_FIRST, LANG_FA):
            for match in pattern.finditer(line):
                rows.append((path.name, number, "", literal(match, 3), literal(match, 0)))
                found = True
        if english_dict:
            for match in DICT_ENTRY.finditer(line):
                value = literal(match, 1)
                if PERSIAN.search(value) and match.group(1) in english_dict:
                    rows.append((path.name, number, match.group(1), english_dict[match.group(1)], value))
                    found = True
        if PERSIAN.search(line) and not found:
            unpaired.append((path.name, number, line.strip()[:120]))
    return rows, unpaired


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("ui-copy-review.csv"))
    args = parser.parse_args(argv)
    rows, unpaired = [], []
    for path in sorted([*UI.glob("*.js"), UI / "index.html"]):
        found, missed = extract(path)
        rows += [r for r in found if PERSIAN.search(r[4])]
        unpaired += missed
    with open(args.out, "w", encoding="utf-8-sig", newline="") as out:  # BOM so spreadsheet tools read Persian
        writer = csv.writer(out)
        writer.writerow(["file", "line", "key", "english", "persian", "reviewer_note"])
        writer.writerows(row + ("",) for row in rows)
    print(f"{len(rows)} pairs written to {args.out}; {len(unpaired)} Persian lines not paired")
    for name, number, text in unpaired:
        print(f"  {name}:{number}: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
