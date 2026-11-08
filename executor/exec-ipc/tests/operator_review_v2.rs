//! Contract-only v2 review frames. No listener, credentials or venue effects.
use exec_ipc::{
    review::{Command, Reply, Request, ReviewState, Ticket},
    review_v2::{valid_submit_client_id, ReplyV2, RequestV2},
    StopMode,
};

fn ticket(id: &str) -> Ticket {
    Ticket {
        client_id: id.into(),
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
        expires_at_ms: 20_000,
        quantity_quanta: 10_000,
        worst_price_quanta: 8_000_000,
        max_quote_debit: 8_010_000,
        min_quote_credit: 0,
        preview_hash: [1; 32],
        rules_hash: [2; 32],
        credential_generation: [3; 16],
    }
}

fn request(command: Command) -> RequestV2 {
    RequestV2(Request {
        command,
        correlation: [4; 16],
    })
}

#[test]
fn proposed_ids_require_ascii_letters_digits_or_underscore_in_v2_only() {
    for good in ["A", "_", "BUY_01", "x".repeat(64).as_str()] {
        assert!(valid_submit_client_id(good).is_ok());
        assert!(request(Command::Approve(Box::new(ticket(good))))
            .encode().is_ok());
    }
    for bad in ["", "legacy-id", "legacy.id", "two words", "/escape", "é"] {
        assert!(valid_submit_client_id(bad).is_err());
        assert!(request(Command::Approve(Box::new(ticket(bad))))
            .encode().is_err());
    }
    assert!(valid_submit_client_id(&"x".repeat(65)).is_err());
    // Historic v1 review IDs remain valid on their existing wire.
    assert!(ticket("legacy-id").validate().is_ok());
    assert!(Request {
        command: Command::Approve(Box::new(ticket("legacy-id"))),
        correlation: [4; 16],
    }.encode().is_ok());
}

#[test]
fn v2_approve_is_canonical_and_never_accepted_as_legacy_v1() {
    let proposed = request(Command::Approve(Box::new(ticket("New_01"))));
    let bytes = proposed.encode().unwrap();
    assert_eq!(&bytes[..8], b"TGREVW02");
    assert_eq!(RequestV2::decode(&bytes).unwrap(), proposed);
    assert!(Request::decode(&bytes).is_err());
    let old_bytes = proposed.0.encode().unwrap();
    assert!(RequestV2::decode(&old_bytes).is_err());
    let mut corrupted = bytes;
    corrupted[15] = 1;
    assert!(RequestV2::decode(&corrupted).is_err());
    assert!(RequestV2::decode(&bytes[..399]).is_err());
    assert!(RequestV2::decode(&[0; 401]).is_err());
}

#[test]
fn old_read_side_id_can_still_be_inspected_or_revoked_but_not_prepared() {
    for command in [
        Command::Inspect("venue-generated-1".into()),
        Command::Revoke {
            client_id: "venue-generated-1".into(),
            expected_sequence: 5,
        },
    ] {
        let value = request(command);
        assert_eq!(RequestV2::decode(&value.encode().unwrap()).unwrap(), value);
    }
    let old = request(Command::Prepare {
        client_id: "venue-generated-1".into(),
        expected_sequence: 5,
    });
    assert!(old.encode().is_err());
    let new = request(Command::Prepare {
        client_id: "New_01".into(),
        expected_sequence: 5,
    });
    assert_eq!(RequestV2::decode(&new.encode().unwrap()).unwrap(), new);
}

#[test]
fn v2_receipt_is_version_bound_correlated_and_never_funded_authority() {
    let req = request(Command::Approve(Box::new(ticket("New_01"))));
    let reply = ReplyV2(Reply {
        state: ReviewState::Recorded,
        mode: StopMode::Disarmed,
        correlation: [4; 16],
        current_epoch: 10,
        sequence: 2,
        recorded_at_ms: 1000,
        ceiling_sequence: 1,
        credential_generation: [3; 16],
        ticket: Some(ticket("New_01")),
    });
    let bytes = reply.encode_for(&req).unwrap();
    assert_eq!(&bytes[..8], b"TGREPLY2");
    assert_eq!(ReplyV2::decode_for(&bytes, &req).unwrap(), reply);
    assert!(Reply::decode(&bytes, [4; 16]).is_err());
    assert!(ReplyV2::decode_for(&reply.0.encode().unwrap(), &req).is_err());
    let different = RequestV2(Request {
        correlation: [5; 16],
        ..req.0.clone()
    });
    assert!(ReplyV2::decode_for(&bytes, &different).is_err());
    let mutated = RequestV2(Request {
        command: Command::Approve(Box::new(ticket("Different_02"))),
        correlation: [4; 16],
    });
    assert!(ReplyV2::decode_for(&bytes, &mutated).is_err());
}
