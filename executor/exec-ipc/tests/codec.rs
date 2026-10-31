use exec_ipc::{ProtocolError, StopCommand, StopMode, StopReply, StopRequest, StopResult, FRAME_SIZE};

const CORRELATION: [u8; 16] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];
const EPOCH: u64 = 0x0102030405060708;

fn hex(raw: &[u8]) -> String {
    raw.iter().map(|v| format!("{v:02x}")).collect::<String>()
}

#[test]
fn stop_only_requests_and_acks_match_python_vectors() {
    let fixtures: serde_json::Value = serde_json::from_str(include_str!(
        "../../../contracts/v1/fixtures/stop-wire-v1.json"
    ))
    .unwrap();
    let req = StopRequest { command: StopCommand::PauseEntries, runtime_epoch: EPOCH, correlation: CORRELATION };
    let raw_req = req.encode().unwrap();
    assert_eq!(raw_req.len(), FRAME_SIZE);
    assert_eq!(hex(&raw_req), fixtures["pause_request_hex"].as_str().unwrap());
    assert_eq!(StopRequest::decode(&raw_req), Ok(req));

    let rep = StopReply { result: StopResult::Ack, mode: StopMode::Paused, changed: true, runtime_epoch: EPOCH, correlation: CORRELATION };
    let raw_rep = rep.encode().unwrap();
    assert_eq!(hex(&raw_rep), fixtures["paused_ack_hex"].as_str().unwrap());
    assert_eq!(StopReply::decode(&raw_rep), Ok(rep));
}

#[test]
fn rejects_invalid_headers_and_commands() {
    let req = StopRequest { command: StopCommand::Halt, runtime_epoch: EPOCH, correlation: CORRELATION };
    let raw = req.encode().unwrap();
    for i in [0_usize, 8, 10, 13, 14, 15] {
        let mut corrupt = raw;
        corrupt[i] ^= 1;
        assert!(StopRequest::decode(&corrupt).is_err(), "byte {i}");
    }
    let mut arm = raw;
    arm[12] = 9;
    assert_eq!(StopRequest::decode(&arm), Err(ProtocolError::UnknownCommand));
    assert_eq!(StopRequest::decode(&raw[..39]), Err(ProtocolError::WrongLength));
    assert_eq!(StopRequest::decode(&[0; 41]), Err(ProtocolError::WrongLength));
    assert!(StopReply::decode(&raw).is_err());
}

#[test]
fn zero_identifiers_and_forged_replies_fail() {
    let mut req = StopRequest { command: StopCommand::Status, runtime_epoch: 0, correlation: CORRELATION };
    assert_eq!(req.encode(), Err(ProtocolError::InvalidIdentity));
    req.runtime_epoch = EPOCH;
    req.correlation = [0; 16];
    assert_eq!(req.encode(), Err(ProtocolError::InvalidIdentity));
    let mut reply = StopReply { result: StopResult::StaleRuntime, mode: StopMode::Disarmed, changed: true, runtime_epoch: EPOCH, correlation: CORRELATION };
    assert_eq!(reply.encode(), Err(ProtocolError::InvalidReply));
    reply.changed = false;
    let mut raw = reply.encode().unwrap();
    raw[13] = 7;
    assert_eq!(StopReply::decode(&raw), Err(ProtocolError::InvalidReply));
}
