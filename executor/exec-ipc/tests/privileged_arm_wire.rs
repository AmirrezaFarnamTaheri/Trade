use exec_ipc::{arm::*, StopCommand, StopMode, StopReply, StopRequest, StopResult};

fn request() -> ArmRequest {
    ArmRequest {
        correlation: [1; 16],
        command: ArmCommand::Approve {
            runtime_epoch: 7,
            revision: 9,
            policy_sha256: [2; 32],
            evidence_sha256: [4; 32],
            policy_path: "D:/Trade/data/live/arm-policy.json".into(),
        },
    }
}

fn reply() -> ArmReply {
    ArmReply {
        result: ArmResult::Approved,
        mode: StopMode::Armed,
        correlation: [1; 16],
        runtime_epoch: 7,
        revision: 10,
        blockers: 0,
        record_digest: [3; 32],
        expires_at_ms: 1000,
        policy_sha256: [2; 32],
    }
}

#[test]
fn arm_frames_are_bounded_canonical_and_have_no_measurement_fields() {
    for command in [
        ArmCommand::Status,
        request().command,
        ArmCommand::Disarm { runtime_epoch: 7 },
    ] {
        let original = ArmRequest {
            command,
            correlation: [1; 16],
        };
        let raw = original.encode().unwrap();
        assert_eq!(ArmRequest::decode(&raw).unwrap(), original);
        for length in 0..raw.len() {
            assert!(ArmRequest::decode(&raw[..length]).is_err());
        }
        for index in [0, 7, 9, 15, 1151] {
            let mut bad = raw;
            bad[index] ^= 1;
            assert!(ArmRequest::decode(&bad).is_err());
        }
        let mut extra = raw.to_vec();
        extra.push(0);
        assert!(ArmRequest::decode(&extra).is_err());
    }
    let mut oversized = request();
    if let ArmCommand::Approve { policy_path, .. } = &mut oversized.command {
        *policy_path = "x".repeat(MAX_POLICY_PATH + 1);
    }
    assert!(oversized.encode().is_err());
    let mut raw = request().encode().unwrap();
    raw[80..82].copy_from_slice(&u16::MAX.to_be_bytes());
    assert!(ArmRequest::decode(&raw).is_err());
}

#[test]
fn arm_ack_requires_identity_and_coherent_authority() {
    let original = reply();
    let raw = original.encode().unwrap();
    assert_eq!(ArmReply::decode(&raw, [1; 16]).unwrap(), original);
    assert!(ArmReply::decode(&raw, [2; 16]).is_err());
    for index in [0, 8, 9, 10, 15] {
        let mut bad = raw;
        bad[index] ^= 255;
        assert!(ArmReply::decode(&bad, [1; 16]).is_err());
    }
    for bad in [
        ArmReply {
            mode: StopMode::Disarmed,
            ..reply()
        },
        ArmReply {
            blockers: ArmBlocker::RecentBackup.bit(),
            ..reply()
        },
        ArmReply {
            record_digest: [0; 32],
            ..reply()
        },
        ArmReply {
            result: ArmResult::Disarmed,
            ..reply()
        },
    ] {
        assert!(bad.encode().is_err());
    }
}

#[test]
fn armed_wire_value_never_confirms_pause_exit_or_halt() {
    for command in [
        StopCommand::Status,
        StopCommand::PauseEntries,
        StopCommand::ExitOnly,
        StopCommand::Halt,
    ] {
        let request = StopRequest {
            command,
            runtime_epoch: 7,
            correlation: [1; 16],
        };
        let reply = StopReply {
            result: StopResult::Ack,
            mode: StopMode::Armed,
            changed: false,
            runtime_epoch: 7,
            correlation: [1; 16],
        };
        let decoded = StopReply::decode(&reply.encode().unwrap()).unwrap();
        assert_eq!(decoded.confirms(request), command == StopCommand::Status);
    }
}
