//! Elevated administrator arm control. This framing carries no trusted measurements or identity claims.
use crate::StopMode;

pub const REQUEST_SIZE: usize = 1152;
pub const REPLY_SIZE: usize = 128;
pub const MAX_POLICY_PATH: usize = 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ArmBlocker {
    Policy = 0,
    Stopped,
    RuntimeChanged,
    ApprovalChanged,
    CredentialsMissing,
    FreshBalance,
    FreshFeed,
    LossUnknown,
    OpenOrdersUnknown,
    OrdersTodayUnknown,
    Reconciliation,
    PrivilegedFault,
    TradePermission,
    RecentBackup,
    ProspectiveEvidence,
    OpenIncident,
    EvidenceExpired,
}

impl ArmBlocker {
    pub const fn bit(self) -> u64 {
        1 << self as u8
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArmCommand {
    Status,
    Approve {
        runtime_epoch: u64,
        revision: u64,
        policy_sha256: [u8; 32],
        evidence_sha256: [u8; 32],
        policy_path: String,
    },
    Disarm {
        runtime_epoch: u64,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArmRequest {
    pub command: ArmCommand,
    pub correlation: [u8; 16],
}

fn number<const N: usize>(raw: &[u8]) -> Result<[u8; N], &'static str> {
    raw.try_into().map_err(|_| "invalid arm field length")
}

impl ArmRequest {
    pub fn encode(&self) -> Result<[u8; REQUEST_SIZE], &'static str> {
        if self.correlation == [0; 16] {
            return Err("invalid arm correlation");
        }
        let mut out = [0; REQUEST_SIZE];
        out[..8].copy_from_slice(b"TGARM001");
        out[16..32].copy_from_slice(&self.correlation);
        match &self.command {
            ArmCommand::Status => out[8] = 1,
            ArmCommand::Approve {
                runtime_epoch,
                revision,
                policy_sha256,
                evidence_sha256,
                policy_path,
            } => {
                if *runtime_epoch == 0
                    || *policy_sha256 == [0; 32]
                    || *evidence_sha256 == [0; 32]
                    || policy_path.is_empty()
                    || policy_path.len() > MAX_POLICY_PATH
                    || policy_path.chars().any(char::is_control)
                {
                    return Err("invalid arm approval");
                }
                out[8] = 2;
                out[32..40].copy_from_slice(&runtime_epoch.to_be_bytes());
                out[40..48].copy_from_slice(&revision.to_be_bytes());
                out[48..80].copy_from_slice(policy_sha256);
                out[1106..1138].copy_from_slice(evidence_sha256);
                out[80..82].copy_from_slice(&(policy_path.len() as u16).to_be_bytes());
                out[82..82 + policy_path.len()].copy_from_slice(policy_path.as_bytes());
            }
            ArmCommand::Disarm { runtime_epoch } => {
                if *runtime_epoch == 0 {
                    return Err("invalid arm epoch");
                }
                out[8] = 3;
                out[32..40].copy_from_slice(&runtime_epoch.to_be_bytes());
            }
        }
        Ok(out)
    }

    pub fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.len() != REQUEST_SIZE || &raw[..8] != b"TGARM001" {
            return Err("invalid arm frame");
        }
        let runtime_epoch = u64::from_be_bytes(number(&raw[32..40])?);
        let command = match raw[8] {
            1 => ArmCommand::Status,
            2 => {
                let len = usize::from(u16::from_be_bytes(number(&raw[80..82])?));
                if len > MAX_POLICY_PATH {
                    return Err("invalid arm policy path");
                }
                ArmCommand::Approve {
                    runtime_epoch,
                    revision: u64::from_be_bytes(number(&raw[40..48])?),
                    policy_sha256: number(&raw[48..80])?,
                    evidence_sha256: number(&raw[1106..1138])?,
                    policy_path: std::str::from_utf8(&raw[82..82 + len])
                        .map_err(|_| "invalid arm policy path")?
                        .into(),
                }
            }
            3 => ArmCommand::Disarm { runtime_epoch },
            _ => return Err("unsupported arm command"),
        };
        let request = Self {
            command,
            correlation: number(&raw[16..32])?,
        };
        if request.encode()? != raw {
            return Err("noncanonical arm request");
        }
        Ok(request)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ArmResult {
    Status = 0,
    Approved = 1,
    Blocked = 2,
    Disarmed = 3,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArmReply {
    pub result: ArmResult,
    pub mode: StopMode,
    pub correlation: [u8; 16],
    pub runtime_epoch: u64,
    pub revision: u64,
    pub blockers: u64,
    pub record_digest: [u8; 32],
    pub expires_at_ms: u64,
    pub policy_sha256: [u8; 32],
}

impl ArmReply {
    pub fn encode(&self) -> Result<[u8; REPLY_SIZE], &'static str> {
        if self.correlation == [0; 16]
            || self.runtime_epoch == 0
            || self.blockers >> 17 != 0
            || (self.result == ArmResult::Blocked && self.blockers == 0)
            || (self.result == ArmResult::Approved
                && (self.mode != StopMode::Armed || self.blockers != 0))
            || (self.result == ArmResult::Disarmed && self.mode == StopMode::Armed)
            || (self.mode == StopMode::Armed
                && (self.record_digest == [0; 32]
                    || self.policy_sha256 == [0; 32]
                    || self.expires_at_ms == 0))
        {
            return Err("invalid arm reply");
        }
        let mut out = [0; REPLY_SIZE];
        out[..8].copy_from_slice(b"TGARACK1");
        out[8] = self.result as u8;
        out[9] = self.mode as u8;
        out[16..32].copy_from_slice(&self.correlation);
        out[32..40].copy_from_slice(&self.runtime_epoch.to_be_bytes());
        out[40..48].copy_from_slice(&self.revision.to_be_bytes());
        out[48..56].copy_from_slice(&self.blockers.to_be_bytes());
        out[56..88].copy_from_slice(&self.record_digest);
        out[88..96].copy_from_slice(&self.expires_at_ms.to_be_bytes());
        out[96..128].copy_from_slice(&self.policy_sha256);
        Ok(out)
    }

    pub fn decode(raw: &[u8], expected: [u8; 16]) -> Result<Self, &'static str> {
        if raw.len() != REPLY_SIZE || &raw[..8] != b"TGARACK1" {
            return Err("invalid arm acknowledgment");
        }
        let result = match raw[8] {
            0 => ArmResult::Status,
            1 => ArmResult::Approved,
            2 => ArmResult::Blocked,
            3 => ArmResult::Disarmed,
            _ => return Err("invalid arm result"),
        };
        let reply = Self {
            result,
            mode: raw[9].try_into().map_err(|_| "invalid arm mode")?,
            correlation: number(&raw[16..32])?,
            runtime_epoch: u64::from_be_bytes(number(&raw[32..40])?),
            revision: u64::from_be_bytes(number(&raw[40..48])?),
            blockers: u64::from_be_bytes(number(&raw[48..56])?),
            record_digest: number(&raw[56..88])?,
            expires_at_ms: u64::from_be_bytes(number(&raw[88..96])?),
            policy_sha256: number(&raw[96..128])?,
        };
        if reply.correlation != expected || reply.encode()? != raw {
            return Err("uncorrelated or noncanonical arm reply");
        }
        Ok(reply)
    }
}
