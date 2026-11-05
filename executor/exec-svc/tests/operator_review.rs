use exec_ipc::{ceiling::Ceiling, review::Ticket, StopMode};
use exec_svc::offline_recovery::*;
use std::time::{SystemTime, UNIX_EPOCH};
fn root() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "gym-review-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&path).unwrap();
    path
}
fn limit() -> CeilingChange {
    CeilingChange {
        ceiling: Ceiling::from_amount("USDT", 1, 6, "50").unwrap(),
        principal: "S-1-5-21-100-1001".into(),
        operator_user: "S-1-5-21-100-1000".into(),
        logon: "S-1-5-5-100-200".into(),
        recorded_at_ms: 1000,
        request_id: [1; 16],
        expected_sequence: 0,
    }
}
fn approval() -> OperatorApproval {
    OperatorApproval {
        ticket: Ticket {
            client_id: "intent-1".into(),
            account: "main".into(),
            base: "BTC".into(),
            quote: "USDT".into(),
            buy: true,
            base_decimals: 8,
            price_decimals: 2,
            quote_decimals: 6,
            base_epoch: 1,
            quote_epoch: 1,
            runtime_epoch: 10,
            ceiling_sequence: 1,
            expires_at_ms: 20000,
            quantity_quanta: 10000,
            worst_price_quanta: 8000000,
            max_quote_debit: 8010000,
            min_quote_credit: 0,
            preview_hash: [1; 32],
            rules_hash: [2; 32],
            credential_generation: [3; 16],
        },
        principal: limit().operator_user,
        logon: limit().logon,
        recorded_at_ms: 2000,
        request_id: [2; 16],
        mode: StopMode::Disarmed,
    }
}
#[test]
fn approval_is_exact_and_revocation_survives_limit_change_and_restart() {
    let root = root();
    let path = root.join("exec_ledger.db");
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        journal.commit_ceiling(limit()).unwrap();
        journal.record_approval(approval()).unwrap();
        let saved = journal.operator_approval("intent-1").unwrap();
        assert_eq!(saved.sequence, 2);
        assert_eq!(saved.approval, approval());
        let mut lower = limit();
        lower.expected_sequence = 1;
        lower.ceiling.capital_quanta = 0;
        lower.request_id = [3; 16];
        lower.recorded_at_ms = 3000;
        journal.commit_ceiling(lower).unwrap();
    }
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    assert!(journal
        .operator_approval("intent-1")
        .unwrap()
        .revoked_at_ms
        .is_none());
    journal
        .revoke_approval(ApprovalRevocation {
            client_id: "intent-1".into(),
            expected_sequence: 2,
            principal: approval().principal,
            logon: approval().logon,
            recorded_at_ms: 1500,
            request_id: [4; 16],
        })
        .unwrap();
    drop(journal);
    let journal = DurableOrderJournal::open(&path).unwrap();
    let saved = journal.operator_approval("intent-1").unwrap();
    assert_eq!(saved.sequence, 4);
    assert_eq!(saved.revoked_at_ms, Some(1500));
    assert_eq!(saved.approval.ticket, approval().ticket);
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn forged_actor_stale_limit_wrong_units_expiry_and_halt_never_append() {
    let root = root();
    let path = root.join("exec_ledger.db");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    assert!(journal.record_approval(approval()).is_err());
    journal.commit_ceiling(limit()).unwrap();
    for case in 0..9 {
        let mut value = approval();
        match case {
            0 => value.principal = "S-1-5-21-100-1001".into(),
            1 => value.ticket.ceiling_sequence = 2,
            2 => value.ticket.quote_epoch = 2,
            3 => value.ticket.quote_decimals = 5,
            4 => value.ticket.expires_at_ms = 40000,
            5 => value.ticket.expires_at_ms = 1000,
            6 => value.mode = StopMode::Halted,
            7 => value.mode = StopMode::Paused,
            8 => value.ticket.max_quote_debit = 51_000_000,
            _ => {}
        }
        assert!(journal.record_approval(value).is_err());
        assert_eq!(journal.record_count(), 1);
    }
    journal.record_approval(approval()).unwrap();
    assert!(journal.record_approval(approval()).is_err());
    assert_eq!(journal.record_count(), 2);
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}
#[test]
fn stale_or_different_operator_cannot_revoke_or_reapprove_a_ticket() {
    let root = root();
    let path = root.join("exec_ledger.db");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.commit_ceiling(limit()).unwrap();
    journal.record_approval(approval()).unwrap();
    let revoke = || ApprovalRevocation {
        client_id: "intent-1".into(),
        expected_sequence: 2,
        principal: approval().principal,
        logon: approval().logon,
        recorded_at_ms: 2001,
        request_id: [5; 16],
    };
    let mut bad = revoke();
    bad.expected_sequence = 1;
    assert!(journal.revoke_approval(bad).is_err());
    let mut bad = revoke();
    bad.principal = limit().principal;
    assert!(journal.revoke_approval(bad).is_err());
    assert_eq!(journal.record_count(), 2);
    journal.revoke_approval(revoke()).unwrap();
    assert!(journal.revoke_approval(revoke()).is_err());
    assert!(journal.record_approval(approval()).is_err());
    drop(journal);
    std::fs::remove_dir_all(root).unwrap();
}
