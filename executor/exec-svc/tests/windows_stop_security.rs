#![cfg(windows)]
use exec_ipc::{StopCommand, StopMode, StopReply, StopRequest, StopResult, FRAME_SIZE};
#[test]
fn security_wiring_stays_fail_closed() {
    let client = include_str!("../src/bin/gym-stopctl.rs");
    assert!(
        client
            .find("authenticate_pipe(pipe.as_handle(), expected_pid)?")
            .unwrap()
            < client.find("pipe.write_all(&frame)").unwrap()
    );
    assert!(client.contains("recv_timeout(std::time::Duration::from_millis(900))"));
    let listener = include_str!("../src/windows_pipe.rs");
    assert!(listener.contains("let replacement = create_pipe(service_sid, logon_sid, false)?;"));
    let host = include_str!("../src/main.rs");
    assert!(host.contains("catch_unwind"));
    assert!(host.contains("failed.store(true, Ordering::SeqCst)"));
    assert!(host.contains("stop_on_failure.store(true, Ordering::SeqCst)"));
}

#[test]
fn bounded_frames_and_correlated_ack() {
    let request = StopRequest {
        command: StopCommand::Halt,
        runtime_epoch: 12,
        correlation: [9; 16],
    };
    let frame = request.encode().unwrap();
    for length in 0..FRAME_SIZE {
        assert!(StopRequest::decode(&frame[..length]).is_err());
    }
    let mut oversized = frame.to_vec();
    oversized.push(0);
    assert!(StopRequest::decode(&oversized).is_err());
    for index in 0..16 {
        let mut invalid = frame;
        invalid[index] ^= 0xff;
        assert!(StopRequest::decode(&invalid).is_err());
    }
    let reply = StopReply {
        result: StopResult::Ack,
        mode: StopMode::Halted,
        changed: true,
        runtime_epoch: 12,
        correlation: [9; 16],
    };
    assert!(reply.confirms(request));
    assert!(!StopReply {
        runtime_epoch: 13,
        ..reply
    }
    .confirms(request));
    assert!(!StopReply {
        correlation: [8; 16],
        ..reply
    }
    .confirms(request));
    assert!(!StopReply {
        mode: StopMode::Paused,
        ..reply
    }
    .confirms(request));
}
