use exec_store::{Ledger, LedgerError};
use tempfile::tempdir;

#[test]
fn audit_prefix_releases_writer_lock_during_read_and_fails_closed_on_tip_change() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("ledger.sqlite3");
    let mut ledger = Ledger::open(&path).expect("open ledger");
    ledger.append(br#"{"step":1}"#).expect("append first event");
    let tip = ledger.tip();

    // During Phase 1 (visit callback), a concurrent writer must be able to append without blocking,
    // and Phase 2 must detect the tip change and fail closed instead of publishing a stale index.
    let mut concurrent_appended = false;
    let err = Ledger::audit_prefix(&path, tip, |_entry, _identities| {
        if !concurrent_appended {
            ledger
                .append(br#"{"step":2}"#)
                .expect("concurrent writer must not be blocked during snapshot read phase");
            concurrent_appended = true;
        }
        Ok(())
    })
    .expect_err("phase 2 must fail closed when tip changed during snapshot audit");

    assert!(concurrent_appended);
    match err {
        LedgerError::Integrity { reason, .. } => assert_eq!(reason, "audit prefix changed"),
        other => panic!("unexpected error variant: {other:?}"),
    }

    // Re-running against the new tip succeeds and publishes a current identity index.
    let new_tip = ledger.tip();
    Ledger::audit_prefix(&path, new_tip, |entry, identities| {
        identities.remember("ev", &entry.sequence.to_be_bytes(), entry.sequence)
    })
    .expect("audit on stable tip succeeds");
    assert!(ledger
        .identity_seen("ev", &new_tip.0.to_be_bytes())
        .expect("identity index is current"));
}
