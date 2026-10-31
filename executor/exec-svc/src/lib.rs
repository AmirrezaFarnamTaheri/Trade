//! Stop control is outside the money loop: an atomic, monotone gate with
//! independent request validation. No venue execution or credential handling.
use exec_ipc::{ProtocolError, StopCommand, StopMode, StopReply, StopRequest, StopResult, FRAME_SIZE};
use std::sync::atomic::{AtomicU8, Ordering};

/// The LocalService primary user is required but is not sufficient by itself.
/// The SCM host also checks its restricted service-SID membership at runtime.
pub fn is_local_service_sid(sid: &str) -> bool {
    sid == "S-1-5-19"
}

/// A SID from the *OS process token*, not an IPC or configuration claim.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenGroup {
    pub sid: String,
    pub enabled: bool,
}

/// A disabled service SID or an unrestricted service token is not sufficient.
/// `service_sid` must come from Windows LookupAccountNameW for the fixed SCM
/// service name; both SID lists must be retrieved from the actual process token.
pub fn is_restricted_executor_token(
    user_sid: &str,
    service_sid: &str,
    groups: &[TokenGroup],
    restricting_sids: &[String],
) -> bool {
    let suffix = match service_sid.strip_prefix("S-1-5-80-") {
        Some(suffix) => suffix,
        None => return false,
    };
    let pieces: Vec<_> = suffix.split('-').collect();
    if !is_local_service_sid(user_sid)
        || pieces.len() != 5
        || pieces.iter().any(|piece| {
            piece.is_empty()
                || !piece.bytes().all(|byte| byte.is_ascii_digit())
                || piece.parse::<u32>().is_err()
        })
    {
        return false;
    }
    groups.iter().any(|group| group.enabled && group.sid == service_sid)
        && restricting_sids.iter().any(|sid| sid == service_sid)
}

#[cfg(windows)]
pub mod windows_identity;

#[cfg(windows)]
pub mod windows_pipe;

pub struct StopGate {
    runtime_epoch: u64,
    mode: AtomicU8,
}

impl StopGate {
    pub fn new(runtime_epoch: u64) -> Result<Self, ProtocolError> {
        if runtime_epoch == 0 {
            return Err(ProtocolError::InvalidIdentity);
        }
        Ok(Self { runtime_epoch, mode: AtomicU8::new(StopMode::Disarmed as u8) })
    }

    pub fn mode(&self) -> StopMode {
        self.mode.load(Ordering::SeqCst).try_into().expect("mode only stored by StopGate")
    }

    pub fn runtime_epoch(&self) -> u64 {
        self.runtime_epoch
    }

    /// Linearizable stop: HALT wins over every weaker concurrent request.
    /// This flag must be read before every future venue effect.
    pub fn process(&self, request: StopRequest) -> StopReply {
        let (result, changed) = if request.runtime_epoch != self.runtime_epoch {
            (StopResult::StaleRuntime, false)
        } else {
            match request.command {
                StopCommand::Status => (StopResult::Ack, false),
                command => {
                    let target = match command {
                        StopCommand::PauseEntries => StopMode::Paused as u8,
                        StopCommand::ExitOnly => StopMode::ExitOnly as u8,
                        StopCommand::Halt => StopMode::Halted as u8,
                        StopCommand::Status => unreachable!(),
                    };
                    let old = self.mode.fetch_max(target, Ordering::SeqCst);
                    (StopResult::Ack, old < target)
                }
            }
        };
        StopReply {
            result,
            mode: self.mode(),
            changed,
            runtime_epoch: self.runtime_epoch,
            correlation: request.correlation,
        }
    }

    pub fn process_frame(&self, bytes: &[u8]) -> Result<[u8; FRAME_SIZE], ProtocolError> {
        let request = StopRequest::decode(bytes)?;
        self.process(request).encode()
    }
}
