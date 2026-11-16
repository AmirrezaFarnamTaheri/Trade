//! Separate elevated submission wire. Review v1/v2 can never encode this request.
use crate::{review_v2::valid_submit_client_id, StopMode};
pub const REQUEST_SIZE: usize = 128;
pub const REPLY_SIZE: usize = 128;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SubmitRequest {
    pub submit: bool,
    pub client_id: String,
    pub expected_sequence: u64,
    pub runtime_epoch: u64,
    pub arm_revision: u64,
    pub correlation: [u8; 16],
}
impl SubmitRequest {
    pub fn encode(&self) -> Result<[u8; REQUEST_SIZE], &'static str> {
        valid_submit_client_id(&self.client_id)?;
        if self.runtime_epoch == 0
            || self.correlation == [0; 16]
            || (self.submit && (self.expected_sequence == 0 || self.arm_revision == 0))
            || (!self.submit && (self.expected_sequence != 0 || self.arm_revision != 0))
        {
            return Err("invalid native submission request");
        }
        let mut raw = [0; REQUEST_SIZE];
        raw[..8].copy_from_slice(b"TGSUB001");
        raw[8] = if self.submit { 1 } else { 2 };
        raw[9] = self.client_id.len() as u8;
        raw[16..24].copy_from_slice(&self.runtime_epoch.to_be_bytes());
        raw[24..40].copy_from_slice(&self.correlation);
        raw[40..48].copy_from_slice(&self.expected_sequence.to_be_bytes());
        raw[48..48 + self.client_id.len()].copy_from_slice(self.client_id.as_bytes());
        raw[112..120].copy_from_slice(&self.arm_revision.to_be_bytes());
        Ok(raw)
    }
    pub fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.len() != REQUEST_SIZE
            || &raw[..8] != b"TGSUB001"
            || !matches!(raw[8], 1 | 2)
            || raw[9] > 64
        {
            return Err("invalid native submit frame");
        }
        let num = |at| u64::from_be_bytes(raw[at..at + 8].try_into().unwrap());
        let request = Self {
            submit: raw[8] == 1,
            client_id: std::str::from_utf8(&raw[48..48 + usize::from(raw[9])])
                .map_err(|_| "invalid submit text")?
                .into(),
            expected_sequence: num(40),
            runtime_epoch: num(16),
            arm_revision: num(112),
            correlation: raw[24..40].try_into().unwrap(),
        };
        if request.encode()?.as_slice() != raw {
            return Err("noncanonical native submit frame");
        }
        Ok(request)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum SubmitState {
    Refused = 1,
    NotSent = 2,
    Pending = 3,
    Observed = 4,
    Settled = 5,
    Missing = 6,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SubmitReply {
    pub state: SubmitState,
    pub mode: StopMode,
    pub runtime_epoch: u64,
    pub correlation: [u8; 16],
    pub sequence: u64,
    pub client_id: String,
}
impl SubmitReply {
    pub fn encode(&self) -> Result<[u8; REPLY_SIZE], &'static str> {
        valid_submit_client_id(&self.client_id)?;
        if self.runtime_epoch == 0
            || self.correlation == [0; 16]
            || (matches!(
                self.state,
                SubmitState::Pending | SubmitState::Observed | SubmitState::Settled
            ) && self.sequence == 0)
            || (self.state == SubmitState::Missing && self.sequence != 0)
        {
            return Err("invalid native submit reply");
        }
        let mut raw = [0; REPLY_SIZE];
        raw[..8].copy_from_slice(b"TGSBACK1");
        raw[8] = self.state as u8;
        raw[9] = self.mode as u8;
        raw[10] = self.client_id.len() as u8;
        raw[16..24].copy_from_slice(&self.runtime_epoch.to_be_bytes());
        raw[24..40].copy_from_slice(&self.correlation);
        raw[40..48].copy_from_slice(&self.sequence.to_be_bytes());
        raw[48..48 + self.client_id.len()].copy_from_slice(self.client_id.as_bytes());
        Ok(raw)
    }
    pub fn decode_for(raw: &[u8], request: &SubmitRequest) -> Result<Self, &'static str> {
        if raw.len() != REPLY_SIZE || &raw[..8] != b"TGSBACK1" || raw[10] > 64 {
            return Err("invalid native submit reply frame");
        }
        let state = match raw[8] {
            1 => SubmitState::Refused,
            2 => SubmitState::NotSent,
            3 => SubmitState::Pending,
            4 => SubmitState::Observed,
            5 => SubmitState::Settled,
            6 => SubmitState::Missing,
            _ => return Err("unknown submit state"),
        };
        let num = |at| u64::from_be_bytes(raw[at..at + 8].try_into().unwrap());
        let reply = Self {
            state,
            mode: raw[9].try_into().map_err(|_| "invalid submit mode")?,
            runtime_epoch: num(16),
            correlation: raw[24..40].try_into().unwrap(),
            sequence: num(40),
            client_id: std::str::from_utf8(&raw[48..48 + usize::from(raw[10])])
                .map_err(|_| "invalid submit text")?
                .into(),
        };
        if reply.correlation != request.correlation
            || reply.client_id != request.client_id
            || reply.runtime_epoch != request.runtime_epoch
            || reply.encode()?.as_slice() != raw
        {
            return Err("submit reply context changed");
        }
        Ok(reply)
    }
}
