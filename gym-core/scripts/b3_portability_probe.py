"""CI-only portable restore probe. The passphrase below is PUBLIC, never live."""
import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

from gym.services.encrypted_backup import create_backup, restore_backup
from gym.services.restore_gate import inspect_ledger

# Synthetic data ONLY. Do not reuse this public phrase on any real account.
TEST_PHRASE = "PUBLIC-CI-TEST-ONLY-PORTABLE-LEDGER-2026"
EVENTS = (b'{"ci":"event1"}', b'{"ci":"event2"}')
SCHEMA = Path(__file__).resolve().parents[2] / "executor/exec-store/schema.sql"


def fixture(path: Path):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA.read_text(encoding="utf-8"))
        previous = bytes(32)
        for n, raw in enumerate(EVENTS, 1):
            digest = hashlib.sha256(previous + len(raw).to_bytes(8, "big") + raw).digest()
            db.execute(
                "INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) "
                "VALUES(?,?,?,?)", (n, raw, previous, digest),
            )
            previous = digest
        db.commit()


def main(args):
    if len(args) == 2 and args[0] == "produce":
        with tempfile.TemporaryDirectory(prefix="b3-ci-only-") as tmp:
            ledger = Path(tmp) / "ledger.db"
            fixture(ledger)
            receipt = create_backup(ledger, Path(args[1]), passphrase=TEST_PHRASE)
        if receipt["encrypted"] is not True or receipt["sequence"] != 2:
            raise RuntimeError("fixture backup verification failed")
        print("PASS: B3 synthetic encrypted bundle created")
        return 0
    if len(args) == 3 and args[0] == "restore":
        destination = Path(args[2])
        receipt = restore_backup(Path(args[1]), destination, passphrase=TEST_PHRASE)
        evidence = inspect_ledger(destination)
        with sqlite3.connect(destination) as db:
            rows = db.execute(
                "SELECT event_bytes FROM ledger_events ORDER BY sequence"
            ).fetchall()
        if receipt["sequence"] != 2 or receipt["head_hash"] != evidence["head_hash"] \
                or tuple(row[0] for row in rows) != EVENTS:
            raise RuntimeError("fixture restore mismatch")
        print("PASS: B3 synthetic restored and verified on fresh runner")
        return 0
    raise ValueError("expected produce BUNDLE or restore BUNDLE DEST")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print("B3 CI fixture failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
