use exec_ipc::ceiling::Ceiling;
use exec_store::Ledger;
use exec_svc::offline_recovery::{
    CeilingChange, CredentialMetadata, CredentialPermission, DurableOrderJournal,
};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

fn root() -> std::path::PathBuf {
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    let path = std::env::temp_dir().join(format!(
        "gym-ceiling-{}-{}-{}",
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&path).unwrap();
    path
}
fn change(id: u8, sequence: u64, amount: &str) -> CeilingChange {
    CeilingChange {
        ceiling: Ceiling::from_amount("USDT", 1, 6, amount).unwrap(),
        principal: "S-1-5-21-100-200-300-1001".into(),
        logon: "S-1-5-5-100-200".into(),
        operator_user: "S-1-5-21-100-200-300-1000".into(),
        recorded_at_ms: 1000 + u64::from(id),
        request_id: [id; 16],
        expected_sequence: sequence,
    }
}

#[test]
fn limits_replay_with_exact_scale_and_history_without_resetting_custody_or_orders() {
    let root = root();
    let path = root.join("exec_ledger.db");
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        assert!(journal.installation_ceiling().is_none());
        journal.create_intent("pending", "main", "BTC", 1).unwrap();
        journal
            .commit_credential(CredentialMetadata {
                generation: [1; 16],
                ciphertext_digest: [2; 32],
                permission: CredentialPermission::Unverified,
            })
            .unwrap();
        journal.commit_ceiling(change(1, 0, "12.345678")).unwrap();
        let sequence = journal.installation_ceiling().unwrap().0;
        assert_eq!(sequence, 3);
        journal.commit_ceiling(change(2, sequence, "0")).unwrap();
    }
    let journal = DurableOrderJournal::open(&path).unwrap();
    let (sequence, value) = journal.installation_ceiling().unwrap();
    assert_eq!(*sequence, 4);
    assert_eq!(value.ceiling.capital_quanta, 0);
    assert_eq!(value.ceiling.decimals, 6);
    assert!(journal.credential_metadata().is_some() && journal.get("pending").is_some());
    drop(journal);
    assert_eq!(
        Ledger::open(&path).unwrap().replay_from(0).unwrap().len(),
        4
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn stale_duplicate_reinterpreted_units_and_regressing_clock_never_append() {
    let root = root();
    let path = root.join("exec_ledger.db");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.commit_ceiling(change(1, 0, "10")).unwrap();
    for case in 0..9 {
        let mut bad = change(2, 1, "20");
        match case {
            0 => bad.expected_sequence = 0,
            1 => bad.request_id = [1; 16],
            2 => bad.ceiling.currency = "TMN".into(),
            3 => bad.ceiling.decimals = 0,
            4 => bad.recorded_at_ms = 999,
            5 => bad.principal = "CALLER-CLAIM".into(),
            6 => bad.principal = bad.operator_user.clone(),
            7 => bad.operator_user = "S-1-5-21-100-200-300-1002".into(),
            8 => bad.ceiling.unit_epoch = 2,
            _ => {}
        }
        assert!(journal.commit_ceiling(bad).is_err());
        assert_eq!(journal.record_count(), 1);
    }
    drop(journal);
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    assert!(journal.commit_ceiling(change(1, 1, "10")).is_err());
    assert_eq!(journal.record_count(), 1);
    let mut lower = change(3, 1, "0");
    lower.principal = lower.operator_user.clone();
    journal.commit_ceiling(lower).unwrap();
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn operator_can_record_zero_but_never_raise_the_initial_limit() {
    let root = root();
    let path = root.join("exec_ledger.db");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    let mut initial = change(1, 0, "10");
    initial.principal = initial.operator_user.clone();
    assert!(journal.commit_ceiling(initial.clone()).is_err());
    assert_eq!(journal.record_count(), 0);
    initial.ceiling.capital_quanta = 0;
    journal.commit_ceiling(initial).unwrap();
    let mut increase = change(2, 1, "1");
    increase.principal = increase.operator_user.clone();
    assert!(journal.commit_ceiling(increase).is_err());
    assert_eq!(journal.record_count(), 1);
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn replay_rejects_hash_valid_reused_ceiling_request() {
    let root = root();
    let path = root.join("exec_ledger.db");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.commit_ceiling(change(1, 0, "10")).unwrap();
    drop(journal);
    let mut ledger = Ledger::open(&path).unwrap();
    let raw = ledger.replay_from(0).unwrap()[0].event_bytes.clone();
    ledger.append(&raw).unwrap();
    drop(ledger);
    assert!(DurableOrderJournal::open(&path).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
