use exec_svc::account_observation::{AccountKind, AccountObservation};
use exec_svc::offline_recovery::{CredentialMetadata, CredentialPermission, DurableOrderJournal};
use std::sync::atomic::{AtomicU64, Ordering};

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
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    let root = std::env::temp_dir().join(format!(
        "gym-account-{}-{}-{}",
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&root).unwrap();
    root
}

fn order(id: &str, status: &str, executed: &str) -> Vec<u8> {
    serde_json::to_vec(
        &serde_json::json!({"success":true,"private":"OMIT","result":{
            "clientOrderId":id,"symbol":"BTCUSDT","side":"BUY","status":status,
            "origQty":"1.000000000000000001","executedQty":executed,
            "fills":[],"private":"OMIT"
        }}),
    )
    .unwrap()
}

#[test]
fn page_receipts_keep_service_request_identity_and_sanitized_orders_across_restart() {
    use exec_ipc::provision::AccountResource;
    let root = root();
    let path = root.join("orders.sqlite");
    let mut ledger = journal(&path);
    for (resource, id, start) in [
        (
            AccountResource::OpenOrders {
                page: 1,
                per_page: 10,
            },
            1,
            1000,
        ),
        (
            AccountResource::OpenOrders {
                page: 2,
                per_page: 10,
            },
            2,
            1020,
        ),
        (
            AccountResource::OrderHistory {
                page: 1,
                per_page: 10,
            },
            3,
            1040,
        ),
    ] {
        let row: serde_json::Value =
            serde_json::from_slice(&order("manual-1", "UNKNOWN_STATUS", "0.1")).unwrap();
        let raw = serde_json::to_vec(&serde_json::json!({"success":true,"private":"OMIT",
            "result":{"BTCUSDT":[row["result"].clone()]},"request":{"page":999}}))
        .unwrap();
        let observation = AccountObservation::from_page_response(
            &resource,
            &raw,
            [3; 16],
            10,
            [id; 16],
            start,
            start + 10,
        )
        .unwrap();
        assert!(!observation.data().to_string().contains("OMIT"));
        assert!(observation.data().get("result_info").is_none());
        let receipt = ledger.record_account_observation(observation).unwrap();
        assert_eq!(
            receipt.response_digest,
            exec_store::hash_event(&[0; 32], &raw)
        );
    }
    drop(ledger);
    let ledger = DurableOrderJournal::open(&path).unwrap();
    for resource in [
        AccountResource::OpenOrders {
            page: 1,
            per_page: 10,
        },
        AccountResource::OpenOrders {
            page: 2,
            per_page: 10,
        },
        AccountResource::OrderHistory {
            page: 1,
            per_page: 10,
        },
    ] {
        let observed = ledger
            .order_page_observation(&resource, [3; 16], 10, 1060, 100)
            .unwrap();
        assert_eq!(
            observed.data()["result"]["orders"][0]["status"],
            "UNKNOWN_STATUS"
        );
        assert!(ledger
            .order_page_observation(&resource, [3; 16], 11, 1060, 100)
            .is_none());
        assert!(ledger
            .order_page_observation(&resource, [4; 16], 10, 1060, 100)
            .is_none());
        assert!(ledger
            .order_page_observation(&resource, [3; 16], 10, 1200, 100)
            .is_none());
    }
    assert!(ledger
        .order_page_observation(
            &AccountResource::OpenOrders {
                page: 3,
                per_page: 10
            },
            [3; 16],
            10,
            1060,
            100
        )
        .is_none());
    assert!(ledger
        .order_page_observation(
            &AccountResource::OpenOrders {
                page: 1,
                per_page: 20
            },
            [3; 16],
            10,
            1060,
            100
        )
        .is_none());
    drop(ledger);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn pages_refuse_wrong_echo_duplicate_orders_and_unbounded_or_inexact_rows() {
    use exec_ipc::provision::AccountResource;
    let resource = AccountResource::OpenOrders {
        page: 2,
        per_page: 1,
    };
    let parse = |raw: &[u8]| {
        AccountObservation::from_page_response(&resource, raw, [3; 16], 10, [1; 16], 1000, 1010)
    };
    let row: serde_json::Value = serde_json::from_slice(&order("manual-1", "NEW", "0")).unwrap();
    let body = serde_json::json!({"success":true,"result":{"BTCUSDT":[row["result"].clone()]},
        "result_info":{"page":2,"per_page":1,"total":900}});
    let observed = parse(&serde_json::to_vec(&body).unwrap()).unwrap();
    assert_eq!(
        observed.data()["result_info"],
        serde_json::json!({"page":2,"per_page":1})
    );
    for field in ["page", "per_page"] {
        for wrong in [
            serde_json::json!(3),
            serde_json::json!("2"),
            serde_json::json!(true),
            serde_json::Value::Null,
        ] {
            let mut bad = body.clone();
            bad["result_info"][field] = wrong;
            assert!(parse(&serde_json::to_vec(&bad).unwrap()).is_err());
        }
    }
    let mut partial = body.clone();
    partial["result_info"]
        .as_object_mut()
        .unwrap()
        .remove("per_page");
    assert!(parse(&serde_json::to_vec(&partial).unwrap())
        .unwrap()
        .data()
        .get("result_info")
        .is_none());
    let mut duplicated = body.clone();
    duplicated["result"]["ETHUSDT"] = serde_json::json!([row["result"].clone()]);
    assert!(parse(&serde_json::to_vec(&duplicated).unwrap()).is_err());
    let resource = AccountResource::OrderHistory {
        page: 2,
        per_page: 100,
    };
    duplicated.as_object_mut().unwrap().remove("result_info");
    assert!(AccountObservation::from_page_response(
        &resource,
        &serde_json::to_vec(&duplicated).unwrap(),
        [3; 16],
        10,
        [1; 16],
        1000,
        1010
    )
    .is_err());
    assert!(AccountObservation::from_response(
        AccountKind::OpenOrders,
        &serde_json::to_vec(&body).unwrap(),
        [3; 16],
        10,
        [1; 16],
        1000,
        1010
    )
    .is_err());
    assert!(AccountObservation::from_page_response(
        &AccountResource::Balances,
        b"{}",
        [3; 16],
        10,
        [1; 16],
        1000,
        1010
    )
    .is_err());
}

#[test]
fn known_order_receipts_bind_identity_and_retain_each_order_across_restart() {
    let root = root();
    let path = root.join("orders.sqlite");
    let mut ledger = journal(&path);
    for (id, request, start) in [("manual-1", 1, 1000), ("manual-2", 2, 1020)] {
        let observation = AccountObservation::from_order_response(
            id,
            &order(id, "VENUE_NEW_STATUS", "0.1"),
            [3; 16],
            10,
            [request; 16],
            start,
            start + 10,
        )
        .unwrap();
        let receipt = ledger.record_account_observation(observation).unwrap();
        assert_eq!(receipt.kind, AccountKind::KnownClientOrder);
    }
    let later = AccountObservation::from_order_response(
        "manual-1",
        &order("manual-1", "CANCELED", "0.2"),
        [3; 16],
        10,
        [3; 16],
        1040,
        1050,
    )
    .unwrap();
    ledger.record_account_observation(later).unwrap();
    drop(ledger);
    let ledger = DurableOrderJournal::open(&path).unwrap();
    let first = ledger
        .known_order_observation("manual-1", [3; 16], 10, 1060, 100)
        .unwrap();
    let second = ledger
        .known_order_observation("manual-2", [3; 16], 10, 1060, 100)
        .unwrap();
    assert_eq!(first.data()["result"]["status"], "CANCELED");
    assert_eq!(first.data()["result"]["executedQty"], "0.2");
    assert_eq!(second.data()["result"]["status"], "VENUE_NEW_STATUS");
    assert!(!first.data().to_string().contains("OMIT"));
    assert!(ledger
        .known_order_observation("absent", [3; 16], 10, 1060, 100)
        .is_none());
    assert!(ledger
        .known_order_observation("manual-1", [3; 16], 11, 1060, 100)
        .is_none());
    assert!(ledger
        .known_order_observation("manual-1", [3; 16], 10, 1200, 100)
        .is_none());
    drop(ledger);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn known_orders_refuse_substitution_and_inexact_or_inconsistent_fills() {
    let parse = |body: &[u8]| {
        AccountObservation::from_order_response("manual-1", body, [3; 16], 10, [1; 16], 1000, 1010)
    };
    assert!(parse(&order("manual-2", "NEW", "0")).is_err());
    assert!(parse(&order("manual-1", "FILLED", "1.000000000000000002")).is_err());
    let mut body: serde_json::Value =
        serde_json::from_slice(&order("manual-1", "FILLED", "1.000000000000000001")).unwrap();
    body["result"]["fills"] = serde_json::json!([
        {"quantity":"1","price":"100","fee":"0.001","feeAsset":"BTC","timestamp":1762390000000_u64},
        {"quantity":"0.000000000000000001","price":"100","fee":"0","feeAsset":"BTC","timestamp":1762390000001_u64}
    ]);
    assert!(parse(&serde_json::to_vec(&body).unwrap()).is_ok());
    let mut iso = body.clone();
    iso["result"]["fills"][0]["timestamp"] = serde_json::json!("2026-11-06T00:00:00+03:30");
    assert!(parse(&serde_json::to_vec(&iso).unwrap()).is_ok());
    for (field, bad) in [
        ("quantity", serde_json::json!("0.000000000000000002")),
        ("price", serde_json::json!(0.1)),
        ("fee", serde_json::json!("-1")),
        ("feeAsset", serde_json::json!("BTC\nSECRET")),
        ("timestamp", serde_json::json!(true)),
    ] {
        let mut changed = body.clone();
        changed["result"]["fills"][1][field] = bad;
        assert!(
            parse(&serde_json::to_vec(&changed).unwrap()).is_err(),
            "{field}"
        );
    }
    let mut changed = body.clone();
    changed["result"]["fills"] = serde_json::json!(vec![body["result"]["fills"][0].clone(); 257]);
    assert!(parse(&serde_json::to_vec(&changed).unwrap()).is_err());
    let duplicated =
        br#"{"success":true,"result":{"clientOrderId":"manual-2","clientOrderId":"manual-1"}}"#;
    assert!(parse(duplicated).is_err());
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

#[test]
fn fill_timestamps_follow_the_shared_contract_fixture() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../contracts/v1/fixtures/fill-timestamps.json"
    ))
    .unwrap();
    for (key, expected) in [("accept", true), ("reject", false)] {
        for value in fixture[key].as_array().unwrap() {
            assert_eq!(
                exec_svc::account_observation::fill_timestamp(value),
                expected,
                "{key}: {value}"
            );
        }
    }
}
