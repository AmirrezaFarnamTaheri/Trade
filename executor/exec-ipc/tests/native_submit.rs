use exec_ipc::{submit::*, StopMode};
fn request() -> SubmitRequest {
    SubmitRequest {
        submit: true,
        client_id: "intent_1".into(),
        expected_sequence: 3,
        runtime_epoch: 7,
        arm_revision: 2,
        correlation: [1; 16],
    }
}
#[test]
fn canonical_submission_frames_are_separate_from_every_review_version() {
    let request = request();
    let raw = request.encode().unwrap();
    assert_eq!(SubmitRequest::decode(&raw).unwrap(), request);
    assert!(exec_ipc::review::Request::decode(&raw).is_err());
    assert!(exec_ipc::review_v2::RequestV2::decode(&raw).is_err());
    assert!(exec_ipc::arm::ArmRequest::decode(&raw).is_err());
    for index in 0..REQUEST_SIZE {
        let mut changed = raw;
        changed[index] ^= 128;
        if let Ok(parsed) = SubmitRequest::decode(&changed) {
            assert_eq!(parsed.encode().unwrap(), changed);
        }
    }
    for index in [10, 11, 12, 13, 14, 15, 120, 127] {
        let mut changed = raw;
        changed[index] = 1;
        assert!(SubmitRequest::decode(&changed).is_err());
    }
}
#[test]
fn identity_versions_and_inspection_are_strict() {
    for id in ["", "old-id", "old.id", "BTC/USDT", "unsafe\n"] {
        let mut r = request();
        r.client_id = id.into();
        assert!(r.encode().is_err());
    }
    for case in 0..5 {
        let mut r = request();
        match case {
            0 => r.expected_sequence = 0,
            1 => r.runtime_epoch = 0,
            2 => r.arm_revision = 0,
            3 => r.correlation = [0; 16],
            4 => r.submit = false,
            _ => unreachable!(),
        };
        assert!(r.encode().is_err());
    }
    let mut r = request();
    r.submit = false;
    r.expected_sequence = 0;
    r.arm_revision = 0;
    assert_eq!(SubmitRequest::decode(&r.encode().unwrap()).unwrap(), r);
}
#[test]
fn a_submit_reply_must_match_identity_correlation_runtime_and_durable_state() {
    let request = request();
    let reply = SubmitReply {
        state: SubmitState::Pending,
        mode: StopMode::Disarmed,
        runtime_epoch: 7,
        correlation: [1; 16],
        sequence: 4,
        client_id: "intent_1".into(),
    };
    let raw = reply.encode().unwrap();
    assert_eq!(SubmitReply::decode_for(&raw, &request).unwrap(), reply);
    for index in [0, 10, 11, 15, 16, 23, 24, 39, 48, 120, 127] {
        let mut changed = raw;
        changed[index] ^= 1;
        assert!(
            SubmitReply::decode_for(&changed, &request).is_err(),
            "byte {index}"
        );
    }
    let mut invalid = reply.clone();
    invalid.sequence = 0;
    assert!(invalid.encode().is_err());
    invalid.state = SubmitState::Missing;
    invalid.sequence = 4;
    assert!(invalid.encode().is_err());
}
