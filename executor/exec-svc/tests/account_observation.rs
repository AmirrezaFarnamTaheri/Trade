use exec_svc::account_observation::{AccountKind, AccountObservation};
use exec_svc::offline_recovery::{CredentialMetadata, CredentialPermission, DurableOrderJournal};

fn observed(kind: AccountKind, body: &[u8], id: u8, start: u64) -> AccountObservation {
    AccountObservation::from_response(kind, body, [3; 16], 10, [id; 16], start, start + 10).unwrap()
}
fn balances() -> &'static [u8] {
    br#"{"success":true,"private":"OMIT","result":{"balances":{"BTC":{"value":"0.000000000000000001","locked":"0","private":"OMIT"},"usdt":{"value":"100.00","locked":"2.00"}}}}"#
}
fn journal(path: &std::path::Path) -> DurableOrderJournal {
    let mut journal = DurableOrderJournal::open(path).unwrap();
    journal
        .commit_credential(CredentialMetadata {
            generation: [3; 16],
            ciphertext_digest: [4; 32],
            permission: CredentialPermission::Unverified,
        })
        .unwrap();
    journal
}
fn root() -> std::path::PathBuf {
    let root = std::env::temp_dir().join(format!(
        "gym-account-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&root).unwrap();
    root
}

#[test]
fn exact_sanitized_observations_survive_restart_but_not_a_new_runtime_or_key() {
    let root = root();
    let path = root.join("credentials.sqlite");
    let balance = observed(AccountKind::Balances, balances(), 1, 1000);
    let fees = observed(AccountKind::Fees,
        br#"{"success":true,"result":{"levels":[],"BTCUSDT":{"makerFeeRate":"0.0010","takerFeeRate":"0.002","private":"OMIT"}}}"#, 2, 1010);
    let mut ledger = journal(&path);
    let balance_receipt = ledger.record_account_observation(balance.clone()).unwrap();
    let fees_receipt = ledger.record_account_observation(fees.clone()).unwrap();
    assert_eq!(balance_receipt.sequence, 2);
    assert_eq!(fees_receipt.sequence, 3);
    assert_eq!(balance_receipt.runtime_epoch, 10);
    assert_eq!(balance_receipt.credential_generation, [3; 16]);
    assert_eq!(
        balance_receipt.response_digest,
        exec_store::hash_event(&[0; 32], balances())
    );
    assert_eq!(ledger.record_count(), 3);
    let data = balance.data();
    assert_eq!(
        data["result"]["balances"]["BTC"]["value"],
        "0.000000000000000001"
    );
    assert_eq!(data["result"]["balances"]["USDT"]["locked"], "2.00");
    assert!(!data.to_string().contains("OMIT"));
    assert!(!fees.data().to_string().contains("levels"));
    drop(ledger);
    let raw = exec_store::Ledger::open(&path).unwrap();
    let entries = raw.replay_from(0).unwrap();
    assert_eq!(balance_receipt.event_hash, entries[1].event_hash);
    assert_eq!(fees_receipt.event_hash, entries[2].event_hash);
    drop(raw);
    let mut ledger = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(
        ledger.account_observation(AccountKind::Balances, [3; 16], 10, 1020, 100),
        Some(&balance)
    );
    assert_eq!(
        ledger.account_observation(AccountKind::Fees, [3; 16], 10, 1020, 100),
        Some(&fees)
    );
    for (generation, epoch, now, age) in [
        ([3; 16], 11, 1020, 100),
        ([5; 16], 10, 1020, 100),
        ([3; 16], 10, 1009, 100),
        ([3; 16], 10, 1101, 100),
        ([3; 16], 10, 1020, 0),
    ] {
        assert!(ledger
            .account_observation(AccountKind::Balances, generation, epoch, now, age)
            .is_none());
    }
    ledger
        .commit_credential(CredentialMetadata {
            generation: [5; 16],
            ciphertext_digest: [6; 32],
            permission: CredentialPermission::Unverified,
        })
        .unwrap();
    // Even a caller asking for the old key cannot revive an old receipt.
    assert!(ledger
        .account_observation(AccountKind::Balances, [3; 16], 10, 1020, 100)
        .is_none());
    assert!(ledger
        .record_account_observation(observed(AccountKind::Balances, balances(), 3, 1020))
        .is_err());
    drop(ledger);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn replayed_request_wrong_key_and_regressed_clock_do_not_append() {
    let root = root();
    let path = root.join("credentials.sqlite");
    let mut ledger = journal(&path);
    let first = observed(AccountKind::Balances, balances(), 1, 1000);
    ledger.record_account_observation(first.clone()).unwrap();
    assert!(ledger.record_account_observation(first).is_err());
    assert!(ledger
        .record_account_observation(observed(AccountKind::Balances, balances(), 2, 1009))
        .is_err());
    let wrong = AccountObservation::from_response(
        AccountKind::Balances,
        balances(),
        [5; 16],
        10,
        [2; 16],
        1020,
        1030,
    )
    .unwrap();
    assert!(ledger.record_account_observation(wrong).is_err());
    assert_eq!(ledger.record_count(), 2);
    drop(ledger);
    let mut ledger = DurableOrderJournal::open(&path).unwrap();
    assert!(ledger
        .record_account_observation(observed(AccountKind::Balances, balances(), 1, 1020))
        .is_err());
    assert_eq!(ledger.record_count(), 2);
    drop(ledger);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn malformed_duplicate_inexact_and_unconfirmed_money_is_refused() {
    for body in [
        br#"{"success":false,"result":{"balances":{}}}"#.as_slice(),
        br#"{"success":false,"success":true,"result":{"balances":{}}}"#,
        br#"{"success":true,"result":{"balances":{"BTC":{"value":"1","value":"2","locked":"0"}}}}"#,
        br#"{"success":true,"result":{"balances":{"BTC":{"value":"1","locked":"0"},"btc":{"value":"2","locked":"0"}}}}"#,
        br#"{"success":true,"result":{"balances":{"BTC":{"value":0.1,"locked":"0"}}}}"#,
        br#"{"success":true,"result":{"balances":{"BTC":{"value":"-1","locked":"0"}}}}"#,
        br#"{"success":true,"result":{"balances":{"BTC":{"value":"1e9","locked":"0"}}}}"#,
        br#"{"success":true,"result":{"balances":{"BTC":{"value":"1"}}}}"#,
        br#"{"success":true,"result":{"balances":{}}} {}"#,
        b"\xff", b"[]", b"{}", b"",
    ] {
        assert!(AccountObservation::from_response(AccountKind::Balances, body, [3;16], 10, [1;16], 1000, 1010).is_err(), "{body:?}");
    }
    for rate in ["1", "1.001", "NaN", "-0.001", "0e-3", ".001", "0."] {
        let body = format!(
            r#"{{"success":true,"result":{{"BTCUSDT":{{"makerFeeRate":"{rate}","takerFeeRate":"0.001"}}}}}}"#
        );
        assert!(AccountObservation::from_response(
            AccountKind::Fees,
            body.as_bytes(),
            [3; 16],
            10,
            [1; 16],
            1000,
            1010
        )
        .is_err());
    }
    let oversized = vec![b' '; exec_ipc::provision::MAX_ACCOUNT_BODY + 1];
    assert!(AccountObservation::from_response(
        AccountKind::Balances,
        &oversized,
        [3; 16],
        10,
        [1; 16],
        1000,
        1010
    )
    .is_err());
}

#[test]
fn invalid_receipt_context_and_request_duration_are_refused() {
    for (generation, epoch, request, start, end) in [
        ([0; 16], 10, [1; 16], 1000, 1010),
        ([3; 16], 0, [1; 16], 1000, 1010),
        ([3; 16], 10, [0; 16], 1000, 1010),
        ([3; 16], 10, [1; 16], 0, 10),
        ([3; 16], 10, [1; 16], 1000, 999),
        ([3; 16], 10, [1; 16], 1000, 13000),
    ] {
        assert!(AccountObservation::from_response(
            AccountKind::Balances,
            balances(),
            generation,
            epoch,
            request,
            start,
            end
        )
        .is_err());
    }
}

#[test]
fn json_escapes_and_nested_names_cannot_export_the_credential() {
    use exec_svc::account_observation::reject_credential_echo;
    for raw in [
        br#"{"private":"prefix synthetic-not-a-key suffix"}"#.as_slice(),
        br#"{"private":[{"nested":"synthetic\u002dnot-a-key"}]}"#,
        br#"{"synthetic\u002dnot-a-key":"nested field name"}"#,
        br#"{"private":"synthetic-not-a-key","private":"overwritten"}"#,
        br#"{"private":NaN}"#,
        b"\xff",
    ] {
        assert!(reject_credential_echo(raw, b"synthetic-not-a-key").is_err());
    }
    assert!(reject_credential_echo(b"{}", b"").is_err());
    assert!(reject_credential_echo(b"{}", b"synthetic-not-a-key").is_ok());
}

#[test]
fn hash_valid_but_illegal_receipts_fail_replay() {
    let root = root();
    let source = root.join("source.sqlite");
    let mut original = journal(&source);
    original
        .record_account_observation(observed(AccountKind::Balances, balances(), 1, 1000))
        .unwrap();
    drop(original);
    let source = exec_store::Ledger::open(source).unwrap();
    let records = source.replay_from(0).unwrap();
    let valid = &records[1].event_bytes;
    let mut invalid = Vec::new();
    for length in [6, 10, 30, valid.len() - 1] {
        invalid.push(valid[..length].to_vec());
    }
    let mut wrong_account = valid.clone();
    wrong_account[7] = b'x';
    invalid.push(wrong_account);
    let mut wrong_generation = valid.clone();
    wrong_generation[12] ^= 1;
    invalid.push(wrong_generation);
    let mut trailing = valid.clone();
    trailing.push(b' ');
    invalid.push(trailing);
    let mut noncanonical = valid.clone();
    let extra = b",\"private\":\"OMIT\"}";
    noncanonical.pop();
    noncanonical.extend_from_slice(extra);
    invalid.push(noncanonical);
    // A perfectly valid duplicate is also illegal; chain integrity is insufficient.
    invalid.push(valid.clone());
    for (index, bad) in invalid.iter().enumerate() {
        let path = root.join(format!("bad-{index}.sqlite"));
        let mut ledger = exec_store::Ledger::open(&path).unwrap();
        ledger.append(&records[0].event_bytes).unwrap();
        if index == invalid.len() - 1 {
            ledger.append(valid).unwrap();
        }
        ledger.append(bad).unwrap();
        drop(ledger);
        assert!(DurableOrderJournal::open(&path).is_err(), "variant {index}");
    }
    drop(source);
    std::fs::remove_dir_all(root).unwrap();
}
