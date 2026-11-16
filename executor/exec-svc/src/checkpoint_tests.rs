use super::*;
use std::time::Instant;

fn credential(id: u128) -> CredentialMetadata {
    CredentialMetadata {
        generation: id.to_be_bytes(),
        ciphertext_digest: [4; 32],
        permission: CredentialPermission::Unverified,
    }
}

fn checkpoint_bytes(state: &Checkpoint) -> Vec<u8> {
    let state = serde_json::to_vec(state).unwrap();
    let mut raw = CHECKPOINT_MAGIC.to_vec();
    raw.extend_from_slice(&exec_store::hash_event(&[0; 32], &state));
    raw.extend_from_slice(&state);
    raw
}

#[test]
fn independent_replay_rejects_a_self_consistent_but_unearned_checkpoint() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("forged-checkpoint.sqlite");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("one", "main", "USDT", 1).unwrap();
    journal.checkpoint().unwrap();
    drop(journal);
    let mut ledger = Ledger::open(&path).unwrap();
    let entries = ledger.replay_from(0).unwrap();
    let mut state = decode_checkpoint(entries.last().unwrap()).unwrap();
    state.tip = ledger.tip();
    state.bounded_history(state.tip.0);
    state.intents.get_mut("one").unwrap().account = "forged".into();
    ledger.append(&checkpoint_bytes(&state)).unwrap();
    drop(ledger);
    let mut restored = DurableOrderJournal::open(&path).unwrap();
    assert!(restored.wait_for_audit().is_err());
    assert_eq!(restored.audit_status(), AuditStatus::Failed);
    assert!(restored.audit_failed());
    let count = restored.record_count();
    assert!(restored.create_intent("two", "main", "USDT", 1).is_err());
    assert_eq!(restored.record_count(), count);
}

#[test]
fn the_independent_decoder_checks_prefix_bytes_hidden_by_a_later_checkpoint() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("hidden-prefix.sqlite");
    let mut ledger = Ledger::open(&path).unwrap();
    ledger
        .append(b"unknown but hash-valid journal record")
        .unwrap();
    let mut state = Checkpoint {
        tip: ledger.tip(),
        ..Default::default()
    };
    state.bounded_history(state.tip.0);
    ledger.append(&checkpoint_bytes(&state)).unwrap();
    drop(ledger);
    let mut journal = DurableOrderJournal::open(path).unwrap();
    assert!(journal.wait_for_audit().is_err());
    assert!(journal.audit_failed());
}

#[test]
fn bounded_checkpoint_ids_use_the_index_for_old_duplicates_even_after_restart() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("request-history.sqlite");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.commit_credential(credential(1)).unwrap();
    let body = br#"{"success":true,"result":{"balances":{"USDT":{"value":"100","locked":"0"}}}}"#;
    for id in 1u128..=2048 {
        let start = 1000 + id as u64 * 20;
        let value = AccountObservation::from_response(
            AccountKind::Balances,
            body,
            1u128.to_be_bytes(),
            10,
            id.to_be_bytes(),
            start,
            start + 10,
        )
        .unwrap();
        journal.record_account_observation(value).unwrap();
        assert!(journal.account_requests.len() <= 1024);
    }
    journal.checkpoint().unwrap();
    assert!(journal.account_requests.is_empty());
    assert!(journal.generations.is_empty());
    drop(journal);
    let mut restored = DurableOrderJournal::open(&path).unwrap();
    restored.wait_for_audit().unwrap();
    assert_eq!(restored.audit_status(), AuditStatus::Verified);
    assert!(restored
        .ledger
        .identity_seen("account_request", &1u128.to_be_bytes())
        .unwrap());
    let duplicate = AccountObservation::from_response(
        AccountKind::Balances,
        body,
        1u128.to_be_bytes(),
        10,
        1u128.to_be_bytes(),
        100000,
        100010,
    )
    .unwrap();
    let count = restored.record_count();
    assert!(restored.record_account_observation(duplicate).is_err());
    assert!(restored.commit_credential(credential(1)).is_err());
    assert_eq!(restored.record_count(), count);
}

#[test]
fn a_legacy_checkpoint_retains_its_canonical_encoding_and_replay_rules() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("legacy-checkpoint.sqlite");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("legacy", "main", "BTC", 1).unwrap();
    journal.wait_for_audit().unwrap();
    let state = Checkpoint {
        tip: journal.ledger.tip(),
        intents: journal.intents.clone(),
        ..Default::default()
    };
    let raw = checkpoint_bytes(&state);
    assert!(!String::from_utf8_lossy(&raw[40..]).contains("history_through"));
    journal.ledger.append(&raw).unwrap();
    drop(journal);
    let mut restored = DurableOrderJournal::open(&path).unwrap();
    restored.wait_for_audit().unwrap();
    assert!(restored.get("legacy").is_some());
    assert!(restored.create_intent("legacy", "main", "BTC", 1).is_err());
}

#[test]
fn local_backup_anchors_remain_verifiable_before_on_and_after_a_checkpoint() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("anchored-checkpoint.sqlite");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("before", "main", "BTC", 1).unwrap();
    let before = journal.ledger.tip();
    journal.checkpoint().unwrap();
    let checkpoint = journal.ledger.tip();
    journal.create_intent("after", "main", "BTC", 1).unwrap();
    let after = journal.ledger.tip();
    drop(journal);
    let ledger = Ledger::open(&path).unwrap();
    for anchor in [before, checkpoint, after] {
        ledger.verify_anchor(anchor).unwrap();
    }
    assert!(ledger.verify_anchor((before.0, after.1)).is_err());
    assert!(ledger.verify_anchor((after.0 + 1, after.1)).is_err());
}

#[test]
fn checkpoint_pages_bind_order_content_length_and_commit_and_orphans_have_no_authority() {
    let mut state = Checkpoint::default();
    let name = "a".repeat(90);
    for index in 0..2400 {
        apply_record(
            &mut state.intents,
            &mut state.reservations,
            &mut state.legacy_reservations,
            Record::Open {
                id: format!("{name}{index}"),
                account: name.clone(),
                asset: name.clone(),
                quantity: 1,
            },
        )
        .unwrap();
    }
    state.bounded_history(0);
    let raw = serde_json::to_vec(&state).unwrap();
    assert!(raw.len() > exec_store::MAX_EVENT_BYTES);
    let digest = exec_store::hash_event(&[0; 32], &raw);
    let mut pages = Vec::new();
    let mut previous = [0; 32];
    for (index, payload) in raw
        .chunks(exec_store::MAX_EVENT_BYTES - PAGE_HEADER)
        .enumerate()
    {
        let mut bytes = CHECKPOINT_PAGE_MAGIC.to_vec();
        bytes.extend_from_slice(&(index as u32).to_be_bytes());
        bytes.extend_from_slice(&digest);
        bytes.extend_from_slice(payload);
        let event_hash = exec_store::hash_event(&previous, &bytes);
        pages.push(exec_store::LedgerEntry {
            sequence: index as u64 + 1,
            previous_hash: previous,
            event_hash,
            event_bytes: bytes,
        });
        previous = event_hash;
    }
    let manifest = CheckpointManifest {
        tip: (0, [0; 32]),
        chunks: pages.len() as u32,
        state_bytes: raw.len(),
        digest,
    };
    let mut bytes = CHECKPOINT_MANIFEST_MAGIC.to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&manifest).unwrap());
    let commit = exec_store::LedgerEntry {
        sequence: pages.len() as u64 + 1,
        previous_hash: previous,
        event_hash: exec_store::hash_event(&previous, &bytes),
        event_bytes: bytes,
    };
    assert_eq!(
        restore_checkpoint_pages(&commit, &pages)
            .unwrap()
            .intents
            .len(),
        2400
    );
    for case in 0..5 {
        let mut bad = pages.clone();
        match case {
            0 => {
                bad[0].event_bytes[PAGE_HEADER] ^= 1;
            }
            1 => {
                bad.swap(0, 1);
            }
            2 => {
                bad[0].event_bytes[11] = 1;
            }
            3 => {
                bad[0].previous_hash[0] ^= 1;
            }
            4 => {
                bad.pop();
            }
            _ => unreachable!(),
        }
        assert!(
            restore_checkpoint_pages(&commit, &bad).is_err(),
            "case {case}"
        );
    }
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("incomplete-pages.sqlite");
    let mut ledger = Ledger::open(&path).unwrap();
    ledger.append(&pages[0].event_bytes).unwrap();
    drop(ledger);
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.wait_for_audit().unwrap();
    assert!(journal.pending_ids().is_empty());
    journal
        .create_intent("after-crash", "main", "USDT", 1)
        .unwrap();
    assert_eq!(journal.pending_ids(), ["after-crash"]);
}

/// Offline synthetic qualification, deliberately excluded from the ordinary fast test suite.
#[test]
#[ignore = "one-million-row release startup qualification"]
fn one_million_row_journal_starts_in_30_seconds_and_audits_in_120_seconds() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("million-row-checkpoint.sqlite");
    let mut conn = rusqlite::Connection::open(&path).unwrap();
    conn.execute_batch(include_str!("../../exec-store/schema.sql"))
        .unwrap();
    let tx = conn.transaction().unwrap();
    let mut previous = [0; 32];
    let key = credential(1);
    let mut state = Checkpoint {
        credential: Some(key.clone()),
        ..Default::default()
    };
    {
        let mut insert = tx
            .prepare("INSERT INTO ledger_events VALUES(?1,?2,?3,?4)")
            .unwrap();
        for sequence in 1i64..1_000_000 {
            let raw = if sequence == 1 {
                key.encode().unwrap()
            } else {
                let body = format!(
                    r#"{{"success":true,"result":{{"balances":{{"USDT":{{"value":"{}","locked":"0"}}}}}}}}"#,
                    sequence % 1000 + 1
                );
                let start = sequence as u64 * 20;
                let value = AccountObservation::from_response(
                    AccountKind::Balances,
                    body.as_bytes(),
                    key.generation,
                    10,
                    (sequence as u128 - 1).to_be_bytes(),
                    start,
                    start + 10,
                )
                .unwrap();
                let mut raw = MAGIC.to_vec();
                raw.push(ACCOUNT_OBSERVATION);
                add_name(&mut raw, "main").unwrap();
                raw.extend_from_slice(&value.encode().unwrap());
                state.account_observations.insert(value.key(), value);
                raw
            };
            let hash = exec_store::hash_event(&previous, &raw);
            insert
                .execute(rusqlite::params![
                    sequence,
                    raw,
                    previous.as_slice(),
                    hash.as_slice()
                ])
                .unwrap();
            previous = hash;
        }
        state.tip = (999_999, previous);
        state.bounded_history(999_999);
        let raw = checkpoint_bytes(&state);
        let hash = exec_store::hash_event(&previous, &raw);
        insert
            .execute(rusqlite::params![
                1_000_000i64,
                raw,
                previous.as_slice(),
                hash.as_slice()
            ])
            .unwrap();
    }
    tx.commit().unwrap();
    let (min, max, mean, payload_bytes): (i64, i64, f64, i64) = conn.query_row("SELECT min(length(event_bytes)),max(length(event_bytes)),avg(length(event_bytes)),sum(length(event_bytes)) FROM ledger_events", [], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).unwrap();
    drop(conn);
    let started = Instant::now();
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    let opened = started.elapsed();
    assert_eq!(journal.record_count(), 1_000_000);
    assert!(journal.generations.is_empty());
    journal.wait_for_audit().unwrap();
    let completed = started.elapsed();
    assert!(journal
        .ledger
        .identity_seen("account_request", &1u128.to_be_bytes())
        .unwrap());
    assert!(journal.commit_credential(credential(1)).is_err());
    assert_eq!(journal.account_observations.len(), 1);
    eprintln!("million-row checkpoint qualification: rows=1000000 unique_account_requests=999998 live_resources=1 event_bytes_min={min} event_bytes_max={max} event_bytes_mean={mean:.6} payload_bytes={payload_bytes} file_bytes={} open_hash_restore={opened:?} open_plus_full_decode_index={completed:?}", std::fs::metadata(&path).unwrap().len());
    assert!(
        opened.as_secs_f64() < 30.0,
        "startup exceeded 30 seconds: {opened:?}"
    );
    assert!(
        completed.as_secs_f64() < 120.0,
        "full audit exceeded 120 seconds: {completed:?}"
    );
}
