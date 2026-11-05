use exec_ipc::ceiling::{Ceiling, CeilingCommand, CeilingReply, CeilingRequest, SIZE};

fn ceiling() -> Ceiling {
    Ceiling::from_amount("USDT", 1, 6, "12.345678").unwrap()
}

#[test]
fn amounts_are_exact_bounded_and_never_rounded_or_guessed() {
    assert_eq!(ceiling().capital_quanta, 12_345_678);
    assert_eq!(ceiling().amount().unwrap(), "12.345678");
    assert_eq!(
        Ceiling::from_amount("TMN", 1, 0, "0")
            .unwrap()
            .amount()
            .unwrap(),
        "0"
    );
    for amount in [
        "-1",
        "+1",
        "NaN",
        "1e3",
        " 1",
        "1.",
        ".1",
        "1.1234567",
        "18446744073709551616",
    ] {
        assert!(
            Ceiling::from_amount("USDT", 1, 6, amount).is_err(),
            "{amount}"
        );
    }
    for currency in ["", "usdt", "USDT/IRT", "USD\n", "ABCDEFGHIJKLMNOPQ"] {
        assert!(Ceiling::from_amount(currency, 1, 6, "1").is_err());
    }
    assert!(Ceiling::from_amount("USDT", 1, 19, "1").is_err());
    assert!(Ceiling::from_amount("TMN", 0, 0, "1").is_err());
    assert!(Ceiling {
        currency: "USDT".into(),
        unit_epoch: 1,
        decimals: 255,
        capital_quanta: 1
    }
    .amount()
    .is_err());
    assert_eq!(
        Ceiling::from_amount("X", 1, 0, "18446744073709551615")
            .unwrap()
            .capital_quanta,
        u64::MAX
    );
}

#[test]
fn requests_are_canonical_correlated_and_do_not_accept_identity_or_authority_claims() {
    for command in [
        CeilingCommand::Get,
        CeilingCommand::Set {
            expected_sequence: 7,
            ceiling: ceiling(),
        },
    ] {
        let request = CeilingRequest {
            command,
            correlation: [3; 16],
        };
        let bytes = request.encode().unwrap();
        assert_eq!(CeilingRequest::decode(&bytes).unwrap(), request);
        for n in 0..SIZE {
            assert!(CeilingRequest::decode(&bytes[..n]).is_err());
        }
        for offset in [11, 15, 68, 95] {
            let mut bad = bytes;
            bad[offset] = 1;
            assert!(CeilingRequest::decode(&bad).is_err());
        }
    }
    let mut get = CeilingRequest {
        command: CeilingCommand::Get,
        correlation: [3; 16],
    }
    .encode()
    .unwrap();
    get[32] = 1;
    assert!(CeilingRequest::decode(&get).is_err());
    assert!(CeilingRequest {
        command: CeilingCommand::Get,
        correlation: [0; 16]
    }
    .encode()
    .is_err());
}

#[test]
fn replies_bind_version_payload_and_correlation_without_funded_authority() {
    for (sequence, value) in [(0, None), (19, Some(ceiling()))] {
        let reply = CeilingReply {
            sequence,
            ceiling: value,
            correlation: [2; 16],
        };
        let bytes = reply.encode().unwrap();
        assert_eq!(CeilingReply::decode(&bytes, [2; 16]).unwrap(), reply);
        assert!(CeilingReply::decode(&bytes, [4; 16]).is_err());
        let mut authority_claim = bytes;
        authority_claim[95] = 1;
        assert!(CeilingReply::decode(&authority_claim, [2; 16]).is_err());
    }
    assert!(CeilingReply {
        sequence: 0,
        ceiling: Some(ceiling()),
        correlation: [2; 16]
    }
    .encode()
    .is_err());
}
