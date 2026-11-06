use exec_ipc::{account::*, provision::AccountResource};

fn receipt() -> ObservationReceipt {
    ObservationReceipt {
        kind: ObservationKind::Balances,
        sequence: 2,
        runtime_epoch: 10,
        started_at_ms: 1000,
        received_at_ms: 1010,
        credential_generation: [3; 16],
        response_digest: [4; 32],
        event_hash: [5; 32],
    }
}

#[test]
fn v2_requests_keep_v1_bounds_and_canonical_fields() {
    for resource in [
        AccountResource::Balances,
        AccountResource::Fees,
        AccountResource::KnownClientOrder("manual-1".into()),
        AccountResource::OpenOrders {
            page: 1000,
            per_page: 100,
        },
    ] {
        let frame = encode_request(&resource, [1; 16]).unwrap();
        assert_eq!(
            decode_request(&frame),
            Ok((resource.clone(), [1; 16], true))
        );
        assert!(AccountResource::decode(&frame).is_err());
        assert_eq!(
            decode_request(&resource.encode([1; 16]).unwrap()),
            Ok((resource.clone(), [1; 16], false))
        );
        let mut dirty = frame;
        dirty[15] = 1;
        assert!(decode_request(&dirty).is_err());
        for size in 0..frame.len() {
            assert!(decode_request(&frame[..size]).is_err());
        }
    }
}

#[test]
fn receipts_are_bound_to_resource_runtime_correlation_and_exact_frame() {
    let resource = AccountResource::Balances;
    let frame = encode_reply(&resource, 100, [1; 16], Some(&receipt())).unwrap();
    assert_eq!(
        decode_reply(&frame, &resource, [1; 16]),
        Ok((100, Some(receipt())))
    );
    assert!(decode_reply(&frame, &AccountResource::Fees, [1; 16]).is_err());
    assert!(decode_reply(&frame, &resource, [2; 16]).is_err());
    for size in 0..frame.len() {
        assert!(decode_reply(&frame[..size], &resource, [1; 16]).is_err());
    }
    for offset in [0, 29, 30, 31] {
        let mut dirty = frame;
        dirty[offset] ^= 1;
        assert!(decode_reply(&dirty, &resource, [1; 16]).is_err());
    }
    assert!(encode_reply(&resource, 100, [1; 16], None).is_err());
    for size in [1, exec_ipc::provision::MAX_ACCOUNT_BODY] {
        let frame = encode_reply(&resource, size, [1; 16], Some(&receipt())).unwrap();
        assert_eq!(decode_reply(&frame, &resource, [1; 16]).unwrap().0, size);
    }
    for size in [0, exec_ipc::provision::MAX_ACCOUNT_BODY + 1, usize::MAX] {
        assert!(encode_reply(&resource, size, [1; 16], Some(&receipt())).is_err());
    }
    assert!(encode_reply(&resource, 100, [0; 16], Some(&receipt())).is_err());
    let order = AccountResource::KnownClientOrder("manual-1".into());
    assert!(encode_reply(&order, 100, [1; 16], Some(&receipt())).is_err());
    assert!(encode_reply(&order, 100, [1; 16], None).is_err());
    let mut order_receipt = receipt();
    order_receipt.kind = ObservationKind::KnownClientOrder;
    let frame = encode_reply(&order, 100, [1; 16], Some(&order_receipt)).unwrap();
    assert_eq!(
        decode_reply(&frame, &order, [1; 16]),
        Ok((100, Some(order_receipt)))
    );
    let page = AccountResource::OpenOrders {
        page: 1,
        per_page: 100,
    };
    let frame = encode_reply(&page, 100, [1; 16], None).unwrap();
    assert_eq!(decode_reply(&frame, &page, [1; 16]), Ok((100, None)));
    assert!(decode_reply(&frame, &order, [1; 16]).is_err());
    let mut dirty = frame;
    dirty[32] = 1;
    assert!(decode_reply(&dirty, &page, [1; 16]).is_err());
    for field in 0..8 {
        let mut bad = receipt();
        match field {
            0 => bad.sequence = 0,
            1 => bad.runtime_epoch = 0,
            2 => bad.started_at_ms = 0,
            3 => bad.received_at_ms = 999,
            4 => bad.received_at_ms = 13000,
            5 => bad.credential_generation = [0; 16],
            6 => bad.response_digest = [0; 32],
            _ => bad.event_hash = [0; 32],
        }
        assert!(encode_reply(&resource, 100, [1; 16], Some(&bad)).is_err());
    }
}
