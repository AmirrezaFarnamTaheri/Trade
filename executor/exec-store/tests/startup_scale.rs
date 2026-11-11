//! Startup cost at scale: how long open + verify + full replay take for a long ledger.
//! The executor's privileged thread must open its journal within the service's startup wait.
use exec_store::{hash_event, Ledger};
use std::time::Instant;

fn build(path: &std::path::Path, rows: u64, size: usize) {
    // One transaction straight into the schema: appending through Ledger costs one FULL fsync per row.
    let conn = rusqlite::Connection::open(path).unwrap();
    conn.execute_batch(include_str!("../schema.sql")).unwrap();
    conn.execute_batch("BEGIN").unwrap();
    let mut previous = [0u8; 32];
    {
        let mut insert = conn
            .prepare("INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)")
            .unwrap();
        for sequence in 1..=rows {
            let mut event = vec![b'e'; size];
            event[..8].copy_from_slice(&sequence.to_be_bytes());
            let hash = hash_event(&previous, &event);
            insert
                .execute(rusqlite::params![
                    sequence as i64,
                    event,
                    previous.to_vec(),
                    hash.to_vec()
                ])
                .unwrap();
            previous = hash;
        }
    }
    conn.execute_batch("COMMIT").unwrap();
}

/// Records the measured cost; the bound is generous so the test only fails on a large regression.
#[test]
fn open_and_full_replay_of_200k_rows_fits_well_inside_the_startup_wait() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("ledger.db");
    build(&path, 200_000, 300);
    let started = Instant::now();
    let (_ledger, replayed) = Ledger::open_and_replay(&path).unwrap();
    let total = started.elapsed();
    assert_eq!(replayed.len(), 200_000);
    eprintln!("A-5 measurement: 200k rows of 300 B: open+verify+replay {total:?}");
    assert!(
        total.as_secs_f64() < 20.0,
        "startup cost regressed: {total:?}"
    );
}
