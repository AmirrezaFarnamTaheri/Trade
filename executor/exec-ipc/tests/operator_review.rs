use exec_ipc::{review::*, StopMode};
pub fn ticket() -> Ticket {
    Ticket {
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
    }
}
#[test]
fn exact_envelopes_are_bounded_and_never_round_spend_down() {
    let mut value = ticket();
    assert_eq!(Ticket::decode(&value.encode().unwrap()).unwrap(), value);
    value.max_quote_debit = 7999999;
    assert!(value.validate().is_err());
    value = ticket();
    value.quantity_quanta = 1;
    value.worst_price_quanta = 1;
    value.max_quote_debit = 0;
    assert!(value.validate().is_err());
    value.max_quote_debit = 1;
    assert!(value.validate().is_ok());
    value = ticket();
    value.buy = false;
    value.max_quote_debit = 0;
    value.min_quote_credit = 7990000;
    assert!(value.validate().is_ok());
    value.min_quote_credit = 8000001;
    assert!(value.validate().is_err());
    value = ticket();
    value.quantity_quanta = u64::MAX;
    value.worst_price_quanta = u64::MAX;
    value.base_decimals = 0;
    value.price_decimals = 0;
    assert!(value.validate().is_err());
    value = ticket();
    value.base_epoch = 0;
    assert!(value.validate().is_err());
}
#[test]
fn all_commands_round_trip_and_reject_padding_lengths_and_identity_claims() {
    for command in [
        Command::Status,
        Command::Inspect("intent-1".into()),
        Command::Approve(Box::new(ticket())),
        Command::Revoke {
            client_id: "intent-1".into(),
            expected_sequence: 5,
        },
    ] {
        let request = Request {
            command,
            correlation: [4; 16],
        };
        let raw = request.encode().unwrap();
        assert_eq!(Request::decode(&raw).unwrap(), request);
        for length in 0..REQUEST_SIZE {
            assert!(Request::decode(&raw[..length]).is_err());
        }
        for offset in [10, 15, 40, 399] {
            let mut bad = raw;
            bad[offset] = 1;
            assert!(Request::decode(&bad).is_err());
        }
    }
}
#[test]
fn recorded_reply_is_exact_current_context_but_never_a_money_capability() {
    let reply = Reply {
        state: ReviewState::Recorded,
        mode: StopMode::Disarmed,
        correlation: [4; 16],
        current_epoch: 10,
        sequence: 2,
        recorded_at_ms: 1000,
        ceiling_sequence: 1,
        credential_generation: [3; 16],
        ticket: Some(ticket()),
    };
    let raw = reply.encode().unwrap();
    let request = Request {
        command: Command::Approve(Box::new(ticket())),
        correlation: [4; 16],
    };
    assert!(reply.validate_for(&request).is_ok());
    assert!(reply
        .validate_for(&Request {
            command: Command::Status,
            ..request.clone()
        })
        .is_err());
    assert!(Reply {
        state: ReviewState::Revoked,
        ..reply.clone()
    }
    .validate_for(&request)
    .is_err());
    assert!(Reply {
        state: ReviewState::Revoked,
        ..reply.clone()
    }
    .validate_for(&Request {
        command: Command::Revoke {
            client_id: "intent-1".into(),
            expected_sequence: 2
        },
        ..request
    })
    .is_err());
    assert_eq!(Reply::decode(&raw, [4; 16]).unwrap(), reply);
    assert!(Reply::decode(&raw, [5; 16]).is_err());
    let mut bad = raw;
    bad[15] = 1;
    assert!(Reply::decode(&bad, [4; 16]).is_err());
    assert!(Reply {
        state: ReviewState::Status,
        ..reply
    }
    .encode()
    .is_err());
}

#[test]
fn python_and_rust_share_the_same_synthetic_golden_frames() {
    let decode = |line: &str| {
        line.as_bytes()
            .chunks_exact(2)
            .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
            .collect::<Vec<_>>()
    };
    let lines: Vec<_> = include_str!("../../../contracts/v1/fixtures/operator-review-v1.hex")
        .lines()
        .collect();
    assert_eq!(
        Request::decode(&decode(lines[0])).unwrap(),
        Request {
            command: Command::Approve(Box::new(ticket())),
            correlation: [4; 16]
        }
    );
    let reply = Reply::decode(&decode(lines[1]), [4; 16]).unwrap();
    assert_eq!(reply.ticket, Some(ticket()));
    assert_eq!(reply.sequence, 2);
    assert_eq!(reply.credential_generation, [3; 16]);
}
