//! Contract-only v2 review frames. No listener, credentials or venue effects.
use exec_ipc::{
    review::{Command, Reply, Request, ReviewState, Ticket},
    review_v2::{valid_submit_client_id, ReplyV2, RequestV2},
    StopMode,
};

/// Build one exact canonical synthetic v1 ticket for cross-version codec tests.
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

/// Bind a proposed v2 command to a stable nonzero synthetic correlation.
fn request(command: Command) -> RequestV2 {
    RequestV2(Request {
        command,
        correlation: [4; 16],
    })
}

/// Verify v2 proposal IDs are stricter without retroactively changing v1.
#[test]
fn proposed_ids_require_ascii_letters_digits_or_underscore_in_v2_only() {
    for good in ["A", "_", "BUY_01", "x".repeat(64).as_str()] {
        assert!(valid_submit_client_id(good).is_ok());
        assert!(request(Command::Approve(Box::new(ticket(good))))
            .encode()
            .is_ok());
    }
    for bad in ["", "legacy-id", "legacy.id", "two words", "/escape", "é"] {
        assert!(valid_submit_client_id(bad).is_err());
        assert!(request(Command::Approve(Box::new(ticket(bad))))
            .encode()
            .is_err());
    }
    assert!(valid_submit_client_id(&"x".repeat(65)).is_err());
    // Historic v1 review IDs remain valid on their existing wire.
    assert!(ticket("legacy-id").validate().is_ok());
    assert!(Request {
        command: Command::Approve(Box::new(ticket("legacy-id"))),
        correlation: [4; 16],
    }
    .encode()
    .is_ok());
}

/// Enforce separate version magic and strict lengths, padding and canonicality.
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

/// Permit historical order lookups while refusing old IDs for new preparation.
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

/// Bind the receipt to exact v2 intent and reject old or forged correlations.
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

/// Golden v2 frames shared with Python: same layout as v1 apart from the magic.
/// Regenerate with `GYM_WRITE_FIXTURES=1 cargo test -p exec-ipc --test operator_review_v2`.
#[test]
fn v2_golden_frames_match_the_shared_contract_fixture() {
    let hex = |bytes: &[u8]| bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    let unhex = |line: &str| {
        line.as_bytes()
            .as_chunks::<2>()
            .0
            .iter()
            .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
            .collect::<Vec<_>>()
    };
    let v1 = include_str!("../../../contracts/v1/fixtures/operator-review-v1.hex");
    let mut reply = Reply::decode(&unhex(v1.lines().nth(1).unwrap()), [4; 16]).unwrap();
    reply.ticket = Some(ticket("New_01"));
    let request = request(Command::Approve(Box::new(ticket("New_01"))));
    let request_bytes = request.encode().unwrap();
    let reply_bytes = ReplyV2(reply).encode_for(&request).unwrap();
    let expected = format!("{}\n{}\n", hex(&request_bytes), hex(&reply_bytes));
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../contracts/v2/fixtures/operator-review-v2.hex"
    );
    if std::env::var_os("GYM_WRITE_FIXTURES").is_some() {
        std::fs::create_dir_all(std::path::Path::new(path).parent().unwrap()).unwrap();
        std::fs::write(path, &expected).unwrap();
    }
    let stored = std::fs::read_to_string(path).expect("missing v2 golden fixture");
    assert_eq!(stored, expected);
    let lines: Vec<_> = stored.lines().collect();
    assert_eq!(RequestV2::decode(&unhex(lines[0])).unwrap(), request);
    assert!(Request::decode(&unhex(lines[0])).is_err());
    assert_eq!(
        ReplyV2::decode_for(&unhex(lines[1]), &request)
            .unwrap()
            .0
            .ticket,
        Some(ticket("New_01"))
    );
}
