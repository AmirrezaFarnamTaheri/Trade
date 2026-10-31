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
        Self {
            runtime_epoch,
            mode: Mode::Disarmed,
        }
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

// RED: these tests must fail until the monotone stop transition is implemented.
pub fn step(state: State, _request: StopRequest) -> (State, StopResult) {
    (state, StopResult::Acknowledged { mode: state.mode, changed: false })
}
