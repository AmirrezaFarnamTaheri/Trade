use exec_ipc::provision::*;
#[test]
fn fixed_reads_reject_injection_and_noncanonical_frames() {
    for resource in [
        AccountResource::Balances,
        AccountResource::Fees,
        AccountResource::KnownClientOrder("Client_123.a-b".into()),
        AccountResource::KnownClientOrder("a".repeat(96)),
    ] {
        let frame = resource.encode([9; 16]).unwrap();
        assert_eq!(
            AccountResource::decode(&frame),
            Ok((resource.clone(), [9; 16]))
        );
        assert!(parse_header(&frame).is_err());
        for n in 0..frame.len() {
            assert!(AccountResource::decode(&frame[..n]).is_err());
        }
        for offset in [0, 10, 15, 127] {
            let mut altered = frame;
            altered[offset] ^= 0xff;
            assert!(AccountResource::decode(&altered).is_err());
        }
    }
    for id in [
        "",
        "../withdraw",
        "https://evil.test",
        "a/b",
        "a?x=y",
        "a#x",
        "a%2f",
        "-a",
        "a\r\nX:evil",
        "é",
    ] {
        assert!(AccountResource::KnownClientOrder(id.into())
            .encode([9; 16])
            .is_err());
    }
    assert!(AccountResource::KnownClientOrder("a".repeat(97))
        .path()
        .is_err());
    assert!(AccountResource::Balances.encode([0; 16]).is_err());
    let mut frame = AccountResource::Balances.encode([9; 16]).unwrap();
    frame[8] = 4;
    assert!(AccountResource::decode(&frame).is_err());
    assert!(AccountResource::decode(&header(12, [9; 16]).unwrap()).is_err());
}
#[test]
fn response_bounds_reserved_and_correlations_are_exact() {
    for size in [1, MAX_ACCOUNT_BODY] {
        let frame = account_reply(size, [1; 16]).unwrap();
        assert_eq!(parse_account_reply(&frame, [1; 16]), Ok(size));
        assert!(parse_account_reply(&frame, [2; 16]).is_err());
        for offset in [0, 28, 31] {
            let mut altered = frame;
            altered[offset] ^= 1;
            assert!(parse_account_reply(&altered, [1; 16]).is_err());
        }
        for n in 0..frame.len() {
            assert!(parse_account_reply(&frame[..n], [1; 16]).is_err());
        }
    }
    for size in [0, MAX_ACCOUNT_BODY + 1, usize::MAX] {
        assert!(account_reply(size, [1; 16]).is_err());
    }
}

#[test]
fn paged_account_reads_have_fixed_paths_and_canonical_bounds() {
    for resource in [
        AccountResource::OpenOrders {
            page: 1,
            per_page: 100,
        },
        AccountResource::OrderHistory {
            page: 1000,
            per_page: 1,
        },
    ] {
        let frame = resource.encode([9; 16]).unwrap();
        assert_eq!(
            AccountResource::decode(&frame),
            Ok((resource.clone(), [9; 16]))
        );
        for index in [9, 13, 15, 32, 127] {
            let mut altered = frame;
            altered[index] = 255;
            assert!(AccountResource::decode(&altered).is_err());
        }
    }
    assert_eq!(
        AccountResource::OpenOrders {
            page: 1,
            per_page: 100
        }
        .path()
        .unwrap(),
        "/v1/account/openOrders?page=1&per_page=100"
    );
    assert_eq!(
        AccountResource::OrderHistory {
            page: 1000,
            per_page: 1
        }
        .path()
        .unwrap(),
        "/v1/account/orders?page=1000&per_page=1"
    );
    for (page, per_page) in [(0, 10), (1001, 10), (1, 0), (1, 101)] {
        for resource in [
            AccountResource::OpenOrders { page, per_page },
            AccountResource::OrderHistory { page, per_page },
        ] {
            assert!(resource.encode([9; 16]).is_err());
        }
    }
    for resource in [
        AccountResource::Balances,
        AccountResource::Fees,
        AccountResource::KnownClientOrder("x".into()),
    ] {
        for offset in [10, 11, 12] {
            let mut frame = resource.encode([9; 16]).unwrap();
            frame[offset] = 1;
            assert!(AccountResource::decode(&frame).is_err());
        }
    }
}
#[test]
fn recovery_is_explicit_and_never_enables_reads() {
    let normal = StartupMode::from_scm_arguments(&[]).unwrap();
    let recovery = StartupMode::from_scm_arguments(&["--credential-recovery".into()]).unwrap();
    assert!(normal.allows_account_read());
    assert!(!recovery.allows_account_read());
    let drill = StartupMode::from_scm_arguments(&["--stop-isolation-drill".into()]).unwrap();
    assert_eq!(drill, StartupMode::StopIsolationDrill);
    assert!(!drill.allows_account_read());
    for args in [
        vec!["recovery".into()],
        vec!["--credential-recovery".into(), "extra".into()],
        vec!["--normal".into()],
        vec!["--stop-isolation-drill".into(), "extra".into()],
    ] {
        assert!(StartupMode::from_scm_arguments(&args).is_err());
    }
    let ack = committed([1; 16], [2; 16]);
    assert!(confirms(&ack, [1; 16]));
    assert_eq!(&ack[40..], &[0; 8]);
}
