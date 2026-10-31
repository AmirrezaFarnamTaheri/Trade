//! Exact, bounded T0 stop-only wire contract. Does not authenticate a caller;
//! Windows pipe DACL and client-token restrictions remain mandatory.
use std::convert::TryInto;

pub const FRAME_SIZE: usize = 40;
pub const VERSION: u16 = 1;
const MAGIC: [u8; 8] = *b"TGSTOP01";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum StopCommand {
    Status = 1,
    PauseEntries = 2,
    ExitOnly = 3,
    Halt = 4,
}

impl TryFrom<u8> for StopCommand {
    type Error = ProtocolError;
    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            1 => Ok(Self::Status),
            2 => Ok(Self::PauseEntries),
            3 => Ok(Self::ExitOnly),
            4 => Ok(Self::Halt),
            _ => Err(ProtocolError::UnknownCommand),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum StopMode {
    Disarmed = 0,
    Paused = 1,
    ExitOnly = 2,
    Halted = 3,
}

impl TryFrom<u8> for StopMode {
    type Error = ProtocolError;
    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Disarmed),
            1 => Ok(Self::Paused),
            2 => Ok(Self::ExitOnly),
            3 => Ok(Self::Halted),
            _ => Err(ProtocolError::InvalidReply),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum StopResult {
    Ack = 128,
    StaleRuntime = 129,
}

impl TryFrom<u8> for StopResult {
    type Error = ProtocolError;
    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            128 => Ok(Self::Ack),
            129 => Ok(Self::StaleRuntime),
            _ => Err(ProtocolError::InvalidReply),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProtocolError {
    WrongLength,
    InvalidHeader,
    InvalidIdentity,
    UnknownCommand,
    InvalidReply,
}

impl std::fmt::Display for ProtocolError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "stop-only IPC error: {self:?}")
    }
}
impl std::error::Error for ProtocolError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StopRequest {
    pub command: StopCommand,
    pub runtime_epoch: u64,
    pub correlation: [u8; 16],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StopReply {
    pub result: StopResult,
    pub mode: StopMode,
    pub changed: bool,
    pub runtime_epoch: u64,
    pub correlation: [u8; 16],
}

fn valid_identity(epoch: u64, correlation: &[u8; 16]) -> bool {
    epoch != 0 && correlation.iter().any(|byte| *byte != 0)
}

fn encode_frame(
    code: u8,
    mode: u8,
    changed: u8,
    epoch: u64,
    correlation: &[u8; 16],
) -> Result<[u8; FRAME_SIZE], ProtocolError> {
    if !valid_identity(epoch, correlation) {
        return Err(ProtocolError::InvalidIdentity);
    }
    let mut out = [0_u8; FRAME_SIZE];
    out[..8].copy_from_slice(&MAGIC);
    out[8..10].copy_from_slice(&VERSION.to_be_bytes());
    out[10..12].copy_from_slice(&(FRAME_SIZE as u16).to_be_bytes());
    out[12] = code;
    out[13] = mode;
    out[14] = changed;
    out[16..24].copy_from_slice(&epoch.to_be_bytes());
    out[24..].copy_from_slice(correlation);
    Ok(out)
}

fn parse_frame(raw: &[u8]) -> Result<(u8, u8, u8, u64, [u8; 16]), ProtocolError> {
    if raw.len() != FRAME_SIZE {
        return Err(ProtocolError::WrongLength);
    }
    if &raw[..8] != MAGIC.as_slice()
        || &raw[8..10] != VERSION.to_be_bytes().as_slice()
        || &raw[10..12] != (FRAME_SIZE as u16).to_be_bytes().as_slice()
        || raw[15] != 0
    {
        return Err(ProtocolError::InvalidHeader);
    }
    let epoch = u64::from_be_bytes(raw[16..24].try_into().expect("fixed frame"));
    let correlation: [u8; 16] = raw[24..40].try_into().expect("fixed frame");
    if !valid_identity(epoch, &correlation) {
        return Err(ProtocolError::InvalidIdentity);
    }
    Ok((raw[12], raw[13], raw[14], epoch, correlation))
}

impl StopRequest {
    pub fn encode(self) -> Result<[u8; FRAME_SIZE], ProtocolError> {
        encode_frame(self.command as u8, 0, 0, self.runtime_epoch, &self.correlation)
    }

    pub fn decode(raw: &[u8]) -> Result<Self, ProtocolError> {
        let (code, mode, changed, runtime_epoch, correlation) = parse_frame(raw)?;
        if mode != 0 || changed != 0 {
            return Err(ProtocolError::InvalidHeader);
        }
        Ok(Self { command: code.try_into()?, runtime_epoch, correlation })
    }
}

impl StopReply {
    /// Caller must not treat a stale, uncorrelated or weaker ACK as success.
    /// Authentication of the pipe server remains an OS responsibility.
    pub fn confirms(self, request: StopRequest) -> bool {
        let required_mode = match request.command {
            StopCommand::Status => StopMode::Disarmed,
            StopCommand::PauseEntries => StopMode::Paused,
            StopCommand::ExitOnly => StopMode::ExitOnly,
            StopCommand::Halt => StopMode::Halted,
        };
        self.result == StopResult::Ack
            && self.runtime_epoch == request.runtime_epoch
            && self.correlation == request.correlation
            && (self.mode as u8) >= (required_mode as u8)
    }

    pub fn encode(self) -> Result<[u8; FRAME_SIZE], ProtocolError> {
        if self.result == StopResult::StaleRuntime && self.changed {
            return Err(ProtocolError::InvalidReply);
        }
        encode_frame(
            self.result as u8,
            self.mode as u8,
            self.changed as u8,
            self.runtime_epoch,
            &self.correlation,
        )
    }

    pub fn decode(raw: &[u8]) -> Result<Self, ProtocolError> {
        let (code, mode, changed, runtime_epoch, correlation) = parse_frame(raw)?;
        let result = code.try_into()?;
        let mode = mode.try_into()?;
        if changed > 1 || (result == StopResult::StaleRuntime && changed != 0) {
            return Err(ProtocolError::InvalidReply);
        }
        Ok(Self { result, mode, changed: changed == 1, runtime_epoch, correlation })
    }
}
