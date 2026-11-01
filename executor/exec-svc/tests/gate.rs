use exec_ipc::{StopCommand, StopMode, StopReply, StopRequest, StopResult};
use exec_svc::StopGate;
use std::sync::Arc;
use std::thread;

fn request(command: StopCommand, epoch: u64) -> StopRequest {
    StopRequest { command, runtime_epoch: epoch, correlation: [3; 16] }
}

#[test]
fn boots_disarmed_and_status_never_grants_authority() {
    assert!(StopGate::new(0).is_err());
    let gate = StopGate::new(7).unwrap();
    let reply = gate.process(request(StopCommand::Status, 7));
    assert_eq!(reply.mode, StopMode::Disarmed);
    assert_eq!(reply.result, StopResult::Ack);
    assert!(!reply.changed);
}

#[test]
fn stop_commands_only_tighten_and_old_epoch_is_rejected() {
    let gate = StopGate::new(7).unwrap();
    assert_eq!(gate.process(request(StopCommand::PauseEntries, 7)).mode, StopMode::Paused);
    assert_eq!(gate.process(request(StopCommand::ExitOnly, 7)).mode, StopMode::ExitOnly);
    let weak = gate.process(request(StopCommand::PauseEntries, 7));
    assert_eq!(weak.mode, StopMode::ExitOnly);
    assert!(!weak.changed);
    let old = gate.process(request(StopCommand::Halt, 6));
    assert_eq!(old.result, StopResult::StaleRuntime);
    assert_eq!(old.runtime_epoch, 7);
    assert_eq!(old.mode, StopMode::ExitOnly);
    assert_eq!(gate.process(request(StopCommand::Halt, 7)).mode, StopMode::Halted);
    assert_eq!(gate.process(request(StopCommand::ExitOnly, 7)).mode, StopMode::Halted);
    assert_eq!(StopGate::new(8).unwrap().mode(), StopMode::Disarmed);
}

#[test]
fn invalid_framing_cannot_change_emergency_state() {
    let gate = StopGate::new(7).unwrap();
    let mut raw = request(StopCommand::Halt, 7).encode().unwrap();
    raw[12] = 9;
    assert!(gate.process_frame(&raw).is_err());
    assert_eq!(gate.mode(), StopMode::Disarmed);
    let ack = gate.process_frame(&request(StopCommand::Halt, 7).encode().unwrap()).unwrap();
    let reply = StopReply::decode(&ack).unwrap();
    assert_eq!(reply.mode, StopMode::Halted);
    assert_eq!(reply.correlation, [3; 16]);
}

#[test]
fn halt_wins_under_concurrent_stop_requests() {
    let gate = Arc::new(StopGate::new(7).unwrap());
    let mut workers = Vec::new();
    for n in 0..32 {
        let gate = gate.clone();
        workers.push(thread::spawn(move || {
            let cmd = match n % 3 {
                0 => StopCommand::Halt,
                1 => StopCommand::PauseEntries,
                _ => StopCommand::ExitOnly,
            };
            gate.process(request(cmd, 7));
        }));
    }
    for worker in workers {
        worker.join().unwrap();
    }
    assert_eq!(gate.mode(), StopMode::Halted);
}
