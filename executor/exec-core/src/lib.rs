//! Pure Executor control core. No I/O, venue credentials, or order transport.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Disarmed,
    Paused,
    ExitOnly,
    Halted,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct State {
    pub runtime_epoch: u64,
    pub mode: Mode,
}

impl State {
    pub fn new(runtime_epoch: u64) -> Self {
        Self { runtime_epoch, mode: Mode::Disarmed }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StopCommand {
    PauseEntries,
    ExitOnly,
    Halt,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StopRequest {
    pub runtime_epoch: u64,
    pub command: StopCommand,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StopResult {
    Acknowledged { mode: Mode, changed: bool },
    StaleRuntime { current_epoch: u64 },
}

/// T0 requests can only reduce authority. Arming requires a separate,
/// privileged path that does not exist in this read-only foundation.
pub fn step(state: State, request: StopRequest) -> (State, StopResult) {
    if request.runtime_epoch != state.runtime_epoch {
        return (state, StopResult::StaleRuntime { current_epoch: state.runtime_epoch });
    }
    let requested = match request.command {
        StopCommand::PauseEntries => Mode::Paused,
        StopCommand::ExitOnly => Mode::ExitOnly,
        StopCommand::Halt => Mode::Halted,
    };
    fn rank(mode: Mode) -> u8 {
        match mode {
            Mode::Disarmed => 0,
            Mode::Paused => 1,
            Mode::ExitOnly => 2,
            Mode::Halted => 3,
        }
    }
    let mode = if rank(requested) > rank(state.mode) { requested } else { state.mode };
    let changed = mode != state.mode;
    (State { mode, ..state }, StopResult::Acknowledged { mode, changed })
}

pub mod orders;

pub mod authority;
