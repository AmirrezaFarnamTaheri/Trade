use exec_core::{step, Mode, State, StopCommand, StopRequest, StopResult};

fn stop(state: State, command: StopCommand) -> (State, StopResult) {
    step(State { ..state }, StopRequest {
        runtime_epoch: state.runtime_epoch,
        command,
    })
}

#[test]
fn runtime_is_disarmed_and_stop_commands_only_tighten() {
    let boot = State::new(17);
    assert_eq!(boot.mode, Mode::Disarmed);
    let (paused, _) = stop(boot, StopCommand::PauseEntries);
    assert_eq!(paused.mode, Mode::Paused);
    let (exit_only, _) = stop(paused, StopCommand::ExitOnly);
    assert_eq!(exit_only.mode, Mode::ExitOnly);
    let (still_exit_only, ack) = stop(exit_only, StopCommand::PauseEntries);
    assert_eq!(still_exit_only.mode, Mode::ExitOnly);
    assert_eq!(ack, StopResult::Acknowledged { mode: Mode::ExitOnly, changed: false });
    let (halted, _) = stop(still_exit_only, StopCommand::Halt);
    assert_eq!(halted.mode, Mode::Halted);
    assert_eq!(stop(halted, StopCommand::ExitOnly).0.mode, Mode::Halted);
    assert_eq!(State::new(18).mode, Mode::Disarmed);
}

#[test]
fn rejects_stale_runtime_commands_without_mutation() {
    let state = State::new(42);
    let (after, result) = step(state, StopRequest {
        runtime_epoch: 41,
        command: StopCommand::Halt,
    });
    assert_eq!(after, state);
    assert_eq!(result, StopResult::StaleRuntime { current_epoch: 42 });
}
