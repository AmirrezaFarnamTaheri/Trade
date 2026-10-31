"""B3 offline ledger restore verification never overwrites an active ledger."""
from pathlib import Path
import hashlib
import sqlite3

import pytest

from gym.services.restore_gate import RestoreUnsafe, inspect_ledger, check_restore_target


def make_candidate(path: Path, values=(b"first",)):
    schema = (Path(__file__).resolve().parents[2] / "executor/exec-store/schema.sql").read_text()
    db = sqlite3.connect(path)
    db.executescript(schema)
    previous = bytes(32)
    for n, value in enumerate(values, 1):
        h = hashlib.sha256(previous + len(value).to_bytes(8, "big") + value).digest()
        db.execute("INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)",
                   (n, value, previous, h))
        previous = h
    db.commit()
    db.close()
    return previous.hex()


def test_verified_staged_restore_has_exact_stored_byte_chain(tmp_path):
    path = tmp_path / "snapshot.db"
    expected = make_candidate(path, (b'{"a":1}', b'{"a":2}'))
    evidence = inspect_ledger(path)
    assert evidence["sequence"] == 2
    assert evidence["head_hash"] == expected
    assert evidence["schema_version"] == 1
    assert evidence["encrypted"] is False


def test_altered_bytes_and_missing_sequence_fail_closed(tmp_path):
    path = tmp_path / "snapshot.db"
    make_candidate(path, (b"one", b"two"))
    db = sqlite3.connect(path)
    db.execute("DROP TRIGGER ledger_events_no_update")
    db.execute("UPDATE ledger_events SET event_bytes=? WHERE sequence=1", (b"evil",))
    db.executescript("CREATE TRIGGER ledger_events_no_update BEFORE UPDATE ON ledger_events "
                     "BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END;")
    db.commit(); db.close()
    with pytest.raises(RestoreUnsafe, match="hash"):
        inspect_ledger(path)


def test_gap_and_missing_guard_fail_closed(tmp_path):
    path = tmp_path / "snapshot.db"
    make_candidate(path, (b"one", b"two"))
    db = sqlite3.connect(path)
    db.execute("DROP TRIGGER ledger_events_no_delete")
    db.execute("DELETE FROM ledger_events WHERE sequence=1")
    db.executescript("CREATE TRIGGER ledger_events_no_delete BEFORE DELETE ON ledger_events "
                     "BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END;")
    db.commit(); db.close()
    with pytest.raises(RestoreUnsafe, match="sequence"):
        inspect_ledger(path)
    db = sqlite3.connect(path)
    db.execute("DROP TRIGGER ledger_events_no_delete")
    db.commit(); db.close()
    with pytest.raises(RestoreUnsafe, match="guard"):
        inspect_ledger(path)


def test_future_schema_and_sidecars_are_rejected(tmp_path):
    path = tmp_path / "snapshot.db"
    make_candidate(path)
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=99")
    db.commit(); db.close()
    with pytest.raises(RestoreUnsafe, match="schema"):
        inspect_ledger(path)
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=1")
    db.commit(); db.close()
    (tmp_path / "snapshot.db-wal").write_bytes(b"uncommitted")
    with pytest.raises(RestoreUnsafe, match="sidecar"):
        inspect_ledger(path)


def test_restore_refuses_preexisting_destination_and_backup_secrets(tmp_path):
    src, dst = tmp_path / "snapshot.db", tmp_path / "exec_ledger.db"
    make_candidate(src)
    dst.write_bytes(b"do not touch me")
    with pytest.raises(RestoreUnsafe, match="exists"):
        check_restore_target(src, dst)
    assert dst.read_bytes() == b"do not touch me"
    dst.unlink()
    (tmp_path / "secrets.dat").write_bytes(b"no")
    with pytest.raises(RestoreUnsafe, match="secrets.dat"):
        check_restore_target(src, dst)


def test_no_restore_from_symlink_or_nonexistent_file(tmp_path):
    src = tmp_path / "snapshot.db"
    make_candidate(src)
    link = tmp_path / "link.db"
    link.symlink_to(src)
    with pytest.raises(RestoreUnsafe):
        inspect_ledger(link)
    with pytest.raises(RestoreUnsafe):
        inspect_ledger(tmp_path / "missing.db")


def test_staged_restore_can_be_pinned_to_independently_verified_manifest(tmp_path):
    path = tmp_path / "snapshot.db"
    head = make_candidate(path, (b"first", b"second"))
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    from gym.services.restore_gate import inspect_pinned_ledger
    report = inspect_pinned_ledger(
        path, expected_head_hash=head, expected_file_sha256=digest
    )
    assert report["head_hash"] == head
    assert report["file_sha256"] == digest
    assert report["trusted_origin"] is False  # comparison is not authentication


def test_staged_restore_rejects_manifest_mismatches_and_bad_digests(tmp_path):
    path = tmp_path / "snapshot.db"
    head = make_candidate(path)
    from gym.services.restore_gate import inspect_pinned_ledger, RestoreUnsafe
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RestoreUnsafe, match="head"):
        inspect_pinned_ledger(path, expected_head_hash="1" * 64,
                              expected_file_sha256=digest)
    with pytest.raises(RestoreUnsafe, match="file"):
        inspect_pinned_ledger(path, expected_head_hash=head,
                              expected_file_sha256="f" * 64)
    with pytest.raises(RestoreUnsafe, match="digest"):
        inspect_pinned_ledger(path, expected_head_hash="not-hex",
                              expected_file_sha256=digest)


def test_staged_restore_preserves_existing_destination_under_manifest_checks(tmp_path):
    from gym.services.restore_gate import check_pinned_restore_target, RestoreUnsafe
    path, dest = tmp_path / "snapshot.db", tmp_path / "exec_ledger.db"
    head = make_candidate(path)
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    dest.write_bytes(b"active money ledger must not be overwritten")
    with pytest.raises(RestoreUnsafe, match="exists"):
        check_pinned_restore_target(
            path, dest, expected_head_hash=head, expected_file_sha256=digest
        )
    assert dest.read_bytes() == b"active money ledger must not be overwritten"
