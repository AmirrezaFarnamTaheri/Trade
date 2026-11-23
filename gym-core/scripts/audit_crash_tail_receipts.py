"""Audit legacy book pointers into specified crash-tail segments without changing the archive."""
import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

import zstandard


def scan(path, wanted):
    decoder = zstandard.ZstdDecompressor().decompressobj()
    buffer = b""
    matched = set()
    invalid = set()
    last = None
    with path.open("rb") as stream:
        while not decoder.eof and (chunk := stream.read(1 << 20)):
            buffer += decoder.decompress(chunk)
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                frame = json.loads(line)
                last = frame["seq"]
                if last in wanted:
                    digest = hashlib.sha256(frame["raw"].encode()).hexdigest()
                    (matched if digest == frame["sha256"] else invalid).add(last)
    return matched - invalid, invalid, last, decoder.eof and not buffer.strip()


def audit(database, raw_root, inputs, segments):
    raw_root = raw_root.resolve()
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("CREATE TEMP TABLE audit_symbols (id TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO audit_symbols VALUES (?)",
                       [(f"wallex:{symbol}",) for symbol in inputs["symbols"]])
        for segment in segments:
            path = (raw_root / segment).resolve()
            if not path.is_relative_to(raw_root):
                raise ValueError(f"segment escapes archive root: {segment}")
            refs = defaultdict(list)
            for ref, symbol, at in db.execute(
                """SELECT depth_ref, instrument_id, ts_avail
                   FROM book_top JOIN audit_symbols ON id=instrument_id
                   WHERE ts_avail>=? AND ts_avail<? AND substr(depth_ref,1,?)=?""",
                (inputs["from"], inputs["to"], len(segment) + 1, segment + "#"),
            ):
                refs[int(ref.rsplit("#", 1)[1])].append({"symbol": symbol, "received": at})
            matched, invalid, last, complete = scan(path, refs)
            yield {
                "segment": segment,
                "referenced": sum(map(len, refs.values())),
                "frame_hash_matched": sum(len(refs[key]) for key in matched),
                "invalid_sequences": sorted(invalid),
                "last_complete_sequence": last,
                "compressed_frame_complete": complete,
                "unresolved": [{"sequence": key, "receipts": sorted(
                    refs[key], key=lambda receipt: (receipt["received"], receipt["symbol"]))}
                               for key in sorted(refs.keys() - matched)],
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("raw_root", type=Path)
    parser.add_argument("intent_tape", type=Path)
    parser.add_argument("segments", nargs="+")
    args = parser.parse_args()
    if len(set(args.segments)) != len(args.segments):
        parser.error("segment paths must be distinct")
    inputs = json.loads(args.intent_tape.read_text(encoding="utf-8"))["source_inputs"]
    report = list(audit(args.database, args.raw_root, inputs, args.segments))
    print(json.dumps({"scope": "RAW_FRAME_PAYLOAD_HASH_ONLY", "segments": report}, indent=2))


if __name__ == "__main__":
    main()
