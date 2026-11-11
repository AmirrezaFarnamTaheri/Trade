use exec_store::{Ledger, LedgerError, MAX_EVENT_BYTES};
use rusqlite::Connection;
use tempfile::tempdir;

#[test]
fn opening_with_replay_preserves_bytes_head_and_writer_lock() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let (mut ledger, entries) = Ledger::open_and_replay(&path).unwrap();
    assert!(entries.is_empty());
    let first = ledger.append(b"\0exact bytes\xff").unwrap();
    let second = ledger.append(b"second").unwrap();
    drop(ledger);
    let (mut ledger, entries) = Ledger::open_and_replay(&path).unwrap();
    assert_eq!(entries, vec![first, second.clone()]);
    assert_eq!(ledger.pragmas().unwrap(), ("wal".into(), 2));
    assert_eq!(ledger.verify().unwrap(), second.event_hash);
    assert!(matches!(
        Ledger::open_and_replay(&path),
        Err(LedgerError::WriterLocked)
    ));
    let third = ledger.append(b"third").unwrap();
    assert_eq!(third.sequence, 3);
    assert_eq!(third.previous_hash, second.event_hash);
    assert_eq!(ledger.replay_from(2).unwrap(), vec![third]);
}

#[test]
fn opening_with_replay_does_not_cache_later_verification() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let (mut ledger, _) = Ledger::open_and_replay(&path).unwrap();
    let first = ledger.append(b"first").unwrap();
    let other = Connection::open(&path).unwrap();
    let bytes = b"external append";
    let hash = exec_store::hash_event(&first.event_hash, bytes);
    other
        .execute(
            "INSERT INTO ledger_events VALUES(2,?1,?2,?3)",
            rusqlite::params![
                bytes.as_slice(),
                first.event_hash.as_slice(),
                hash.as_slice()
            ],
        )
        .unwrap();
    assert!(matches!(
        ledger.replay_from(0),
        Err(LedgerError::Integrity {
            sequence: 2,
            reason: "head changed outside writer"
        })
    ));
    assert!(matches!(
        ledger.verify(),
        Err(LedgerError::Integrity { sequence: 2, .. })
    ));
    assert!(matches!(
        ledger.append(b"refused"),
        Err(LedgerError::Integrity { sequence: 2, .. })
    ));
    other
        .execute_batch("DROP TRIGGER ledger_events_no_update;")
        .unwrap();
    other
        .execute(
            "UPDATE ledger_events SET event_bytes=?1 WHERE sequence=1",
            [b"changed".as_slice()],
        )
        .unwrap();
    assert!(matches!(
        ledger.replay_from(2),
        Err(LedgerError::Integrity {
            sequence: 1,
            reason: "stored-byte hash mismatch"
        })
    ));
}

#[test]
fn committed_events_survive_reopen_with_exact_bytes_and_order() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let event = include_bytes!("../../../contracts/v1/fixtures/genesis-event.json");
    let first_hash;
    {
        let mut ledger = Ledger::open(&path).unwrap();
        let (journal, sync): (String, i64) = ledger.pragmas().unwrap();
        assert_eq!(journal.to_lowercase(), "wal");
        assert_eq!(sync, 2, "money ledger commits require synchronous=FULL");

        let first = ledger.append(event).unwrap();
        assert_eq!(first.sequence, 1);
        assert_eq!(first.previous_hash, [0; 32]);
        assert_eq!(first.event_bytes.as_slice(), event.as_slice());
        first_hash = first.event_hash;

        let second = ledger.append(br#"{"event_type":"MARK"}"#).unwrap();
        assert_eq!(second.sequence, 2);
        assert_eq!(second.previous_hash, first_hash);
    }
    let ledger = Ledger::open(&path).unwrap();
    let entries = ledger.replay_from(0).unwrap();
    assert_eq!(entries.len(), 2);
    assert_eq!(entries[0].event_bytes.as_slice(), event.as_slice());
    assert_eq!(entries[1].previous_hash, first_hash);
    assert_eq!(ledger.replay_from(1).unwrap().len(), 1);
    assert_eq!(ledger.verify().unwrap(), entries[1].event_hash);
}

#[test]
fn second_writer_is_refused_until_first_closes() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let first = Ledger::open(&path).unwrap();
    assert!(matches!(
        Ledger::open(&path),
        Err(LedgerError::WriterLocked)
    ));
    drop(first);
    let _second = Ledger::open(&path).unwrap();
}

#[test]
fn reopening_or_contending_for_writer_lock_preserves_its_bytes() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let lock_path = dir.path().join("exec_ledger.db.writer.lock");
    std::fs::write(&lock_path, b"existing lock bytes").unwrap();
    let first = Ledger::open(&path).unwrap();
    assert!(matches!(
        Ledger::open(&path),
        Err(LedgerError::WriterLocked)
    ));
    drop(first);
    drop(Ledger::open(&path).unwrap());
    assert_eq!(std::fs::read(&lock_path).unwrap(), b"existing lock bytes");
}

#[test]
fn immutable_triggers_prevent_accidental_rewrites() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let mut ledger = Ledger::open(&path).unwrap();
    ledger.append(b"original").unwrap();
    let other = Connection::open(&path).unwrap();
    assert!(other
        .execute(
            "UPDATE ledger_events SET event_bytes=?1 WHERE sequence=1",
            [b"changed".as_slice()]
        )
        .is_err());
    assert!(other
        .execute("DELETE FROM ledger_events WHERE sequence=1", [])
        .is_err());
    assert_eq!(
        ledger.replay_from(0).unwrap()[0].event_bytes.as_slice(),
        b"original".as_slice()
    );
}

#[test]
fn corrupt_existing_events_fail_closed_on_restart() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    {
        let mut ledger = Ledger::open(&path).unwrap();
        ledger.append(b"original").unwrap();
    }
    let db = Connection::open(&path).unwrap();
    db.execute_batch("DROP TRIGGER ledger_events_no_update;")
        .unwrap();
    db.execute(
        "UPDATE ledger_events SET event_bytes=?1 WHERE sequence=1",
        [b"altered".as_slice()],
    )
    .unwrap();
    // Restore the immutable guard after synthetic tampering, so the next
    // startup failure proves the stored-byte hash mismatch, not absent DDL.
    db.execute_batch("CREATE TRIGGER ledger_events_no_update BEFORE UPDATE ON ledger_events BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END;").unwrap();
    drop(db);
    assert!(matches!(
        Ledger::open_and_replay(&path),
        Err(LedgerError::Integrity {
            sequence: 1,
            reason: "stored-byte hash mismatch"
        })
    ));
    assert!(matches!(
        Ledger::open(&path),
        Err(LedgerError::Integrity { sequence: 1, .. })
    ));
}

#[test]
fn missing_sequence_fails_closed_even_when_later_hashes_still_match() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    {
        let mut ledger = Ledger::open(&path).unwrap();
        ledger.append(b"first").unwrap();
        ledger.append(b"second").unwrap();
    }
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        "DROP TRIGGER ledger_events_no_delete; DELETE FROM ledger_events WHERE sequence=1;",
    )
    .unwrap();
    // Recreate the DDL protection to test chain sequencing independently.
    db.execute_batch("CREATE TRIGGER ledger_events_no_delete BEFORE DELETE ON ledger_events BEGIN SELECT RAISE(ABORT, 'ledger events are immutable'); END;").unwrap();
    drop(db);
    assert!(matches!(
        Ledger::open_and_replay(&path),
        Err(LedgerError::Integrity {
            sequence: 1,
            reason: "missing or out-of-order sequence"
        })
    ));
    assert!(matches!(
        Ledger::open(&path),
        Err(LedgerError::Integrity { sequence: 1, .. })
    ));
}

#[test]
fn oversized_or_empty_events_do_not_mutate_authoritative_state() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let mut ledger = Ledger::open(&path).unwrap();
    assert!(matches!(
        ledger.append(&[]),
        Err(LedgerError::InvalidSize(0))
    ));
    assert!(matches!(
        ledger.append(&vec![7; MAX_EVENT_BYTES + 1]),
        Err(LedgerError::InvalidSize(_))
    ));
    assert!(ledger.replay_from(0).unwrap().is_empty());
    assert_eq!(ledger.append(b"valid").unwrap().sequence, 1);
}

#[test]
fn incompatible_future_schema_is_not_rewritten() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch("PRAGMA user_version=99;").unwrap();
    drop(db);
    assert!(matches!(
        Ledger::open_and_replay(&path),
        Err(LedgerError::UnsupportedSchema(99))
    ));
    assert!(matches!(
        Ledger::open(&path),
        Err(LedgerError::UnsupportedSchema(99))
    ));
    let db = Connection::open(&path).unwrap();
    let version: i64 = db
        .query_row("PRAGMA user_version", [], |row| row.get(0))
        .unwrap();
    assert_eq!(version, 99);
}

#[test]
fn a_rolled_back_insert_is_not_recovered_as_a_committed_event() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    let mut ledger = Ledger::open(&path).unwrap();
    let first = ledger.append(b"committed").unwrap();
    drop(ledger);
    let db = Connection::open(&path).unwrap();
    db.execute_batch("BEGIN IMMEDIATE;").unwrap();
    db.execute("INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(2,?1,?2,?3)",
        rusqlite::params![b"not committed".as_slice(), first.event_hash.as_slice(), [3u8; 32].as_slice()]).unwrap();
    db.execute_batch("ROLLBACK;").unwrap();
    drop(db);
    let ledger = Ledger::open(&path).unwrap();
    assert_eq!(ledger.replay_from(0).unwrap().len(), 1);
    assert_eq!(ledger.verify().unwrap(), first.event_hash);
}

#[test]
fn missing_immutability_trigger_blocks_startup() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("exec_ledger.db");
    drop(Ledger::open(&path).unwrap());
    let db = Connection::open(&path).unwrap();
    db.execute_batch("DROP TRIGGER ledger_events_no_update;")
        .unwrap();
    drop(db);
    assert!(matches!(
        Ledger::open_and_replay(&path),
        Err(LedgerError::Configuration("append-only guards missing"))
    ));
    assert!(matches!(
        Ledger::open(&path),
        Err(LedgerError::Configuration(_))
    ));
}
