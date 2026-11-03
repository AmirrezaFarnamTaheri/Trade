use exec_store::Ledger;
use exec_svc::offline_recovery::{CredentialMetadata, CredentialPermission, DurableOrderJournal};
use std::{
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};
fn root() -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "gym-provision-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&path).unwrap();
    path
}
fn metadata(n: u8) -> CredentialMetadata {
    CredentialMetadata {
        generation: [n; 16],
        ciphertext_digest: [n; 32],
        permission: CredentialPermission::Unverified,
    }
}
#[test]
fn typed_metadata_replays_and_failed_commit_keeps_previous_generation() {
    let root = root();
    let path = root.join("journal.sqlite");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal
        .create_intent("old-order", "account", "BTC", 12)
        .unwrap();
    journal.commit_credential(metadata(1)).unwrap();
    let count = journal.record_count();
    assert!(journal.commit_credential(metadata(1)).is_err());
    assert!(journal.commit_credential(metadata(0)).is_err());
    assert_eq!(journal.credential_metadata(), Some(&metadata(1)));
    assert_eq!(journal.record_count(), count);
    journal.commit_credential(metadata(2)).unwrap();
    assert!(journal.commit_credential(metadata(1)).is_err());
    assert_eq!(journal.credential_metadata(), Some(&metadata(2)));
    drop(journal);
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    assert!(journal.commit_credential(metadata(1)).is_err());
    assert_eq!(journal.credential_metadata(), Some(&metadata(2)));
    assert!(journal.get("old-order").is_some());
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn replay_rejects_a_previously_superseded_generation() {
    let root = root();
    let path = root.join("journal.sqlite");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.commit_credential(metadata(1)).unwrap();
    journal.commit_credential(metadata(2)).unwrap();
    drop(journal);
    let mut ledger = Ledger::open(&path).unwrap();
    let stale = ledger.replay_from(0).unwrap()[0].event_bytes.clone();
    ledger.append(&stale).unwrap();
    drop(ledger);
    assert!(DurableOrderJournal::open(&path).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn metadata_grammar_rejects_truncation_unknown_permissions_and_trailing_bytes() {
    let mut valid = b"TGOR1\x08\x05venue".to_vec();
    valid.extend_from_slice(&[1; 16]);
    valid.extend_from_slice(&[2; 32]);
    valid.push(0);
    let mut bad = Vec::new();
    for n in 0..valid.len() {
        bad.push(valid[..n].to_vec());
    }
    let mut permission = valid.clone();
    *permission.last_mut().unwrap() = 1;
    bad.push(permission);
    let mut trailing = valid.clone();
    trailing.push(0);
    bad.push(trailing);
    let mut wrong_slot = valid.clone();
    wrong_slot[7] = b'x';
    bad.push(wrong_slot);
    for bytes in bad.into_iter().filter(|b| !b.is_empty()) {
        let root = root();
        let path = root.join("journal.sqlite");
        let mut ledger = Ledger::open(&path).unwrap();
        ledger.append(&bytes).unwrap();
        drop(ledger);
        assert!(DurableOrderJournal::open(&path).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
    let root = root();
    let path = root.join("journal.sqlite");
    let mut ledger = Ledger::open(&path).unwrap();
    ledger.append(&valid).unwrap();
    drop(ledger);
    let journal = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(
        journal.credential_metadata().unwrap().permission,
        CredentialPermission::Unverified
    );
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}
