-- Applied only to an empty v0 database under a BEGIN IMMEDIATE transaction.
-- All records are opaque, immutable stored bytes; API-level contract validation
-- belongs to the versioned ingestion boundary, not to SQLite JSON re-encoding.
CREATE TABLE ledger_events (
    sequence INTEGER PRIMARY KEY NOT NULL CHECK(sequence >= 1),
    event_bytes BLOB NOT NULL CHECK(typeof(event_bytes)='blob' AND length(event_bytes) BETWEEN 1 AND 1048576),
    previous_hash BLOB NOT NULL CHECK(typeof(previous_hash)='blob' AND length(previous_hash)=32),
    event_hash BLOB NOT NULL CHECK(typeof(event_hash)='blob' AND length(event_hash)=32)
);
CREATE TRIGGER ledger_events_no_update BEFORE UPDATE ON ledger_events
BEGIN
    SELECT RAISE(ABORT, 'ledger events are immutable');
END;
CREATE TRIGGER ledger_events_no_delete BEFORE DELETE ON ledger_events
BEGIN
    SELECT RAISE(ABORT, 'ledger events are immutable');
END;
PRAGMA user_version=1;
