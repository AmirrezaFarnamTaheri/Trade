//! Typed operator intent only. No response on this channel permits a venue effect.
use crate::StopMode;
pub const PIPE: &str = r"\\.\pipe\TradingGYM.Operate.v1";
pub const TICKET_SIZE: usize = 352;
pub const REQUEST_SIZE: usize = 400;
pub const REPLY_SIZE: usize = 432;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Ticket {
    pub client_id: String,
    pub account: String,
    pub base: String,
    pub quote: String,
    pub buy: bool,
    pub base_decimals: u8,
    pub price_decimals: u8,
    pub quote_decimals: u8,
    pub base_epoch: u32,
    pub quote_epoch: u32,
    pub runtime_epoch: u64,
    pub ceiling_sequence: u64,
    pub expires_at_ms: u64,
    pub quantity_quanta: u64,
    pub worst_price_quanta: u64,
    pub max_quote_debit: u64,
    pub min_quote_credit: u64,
    pub preview_hash: [u8; 32],
    pub rules_hash: [u8; 32],
    pub credential_generation: [u8; 16],
}
fn name(value: &str, max: usize, asset: bool) -> bool {
    !value.is_empty()
        && value.len() <= max
        && value.bytes().all(|c| {
            if asset {
                c.is_ascii_uppercase() || c.is_ascii_digit()
            } else {
                c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b'.')
            }
        })
}
impl Ticket {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !name(&self.client_id, 64, false)
            || !name(&self.account, 32, false)
            || !name(&self.base, 16, true)
            || !name(&self.quote, 16, true)
            || self.base == self.quote
            || self.base_epoch == 0
            || self.quote_epoch == 0
            || [self.base_decimals, self.price_decimals, self.quote_decimals]
                .iter()
                .any(|d| *d > 18)
            || [
                self.runtime_epoch,
                self.ceiling_sequence,
                self.expires_at_ms,
                self.quantity_quanta,
                self.worst_price_quanta,
            ]
            .contains(&0)
            || self.preview_hash == [0; 32]
            || self.rules_hash == [0; 32]
            || self.credential_generation == [0; 16]
        {
            return Err("invalid operator ticket");
        }
        let gross = self.gross_quote(self.buy)?;
        if (self.buy && (self.max_quote_debit < gross || self.min_quote_credit != 0))
            || (!self.buy
                && (self.max_quote_debit != 0
                    || self.min_quote_credit == 0
                    || self.min_quote_credit > gross))
        {
            return Err("invalid declared quote envelope");
        }
        Ok(())
    }
    fn gross_quote(&self, round_up: bool) -> Result<u64, &'static str> {
        let value = u128::from(self.quantity_quanta) * u128::from(self.worst_price_quanta);
        let scale = i32::from(self.base_decimals) + i32::from(self.price_decimals)
            - i32::from(self.quote_decimals);
        let adjusted = if scale >= 0 {
            let factor = 10u128
                .checked_pow(scale as u32)
                .ok_or("ticket scale overflow")?;
            value / factor + u128::from(round_up && value % factor != 0)
        } else {
            value
                .checked_mul(
                    10u128
                        .checked_pow((-scale) as u32)
                        .ok_or("ticket scale overflow")?,
                )
                .ok_or("ticket amount overflow")?
        };
        adjusted.try_into().map_err(|_| "ticket amount overflow")
    }
    pub fn encode(&self) -> Result<[u8; TICKET_SIZE], &'static str> {
        self.validate()?;
        let mut out = [0; TICKET_SIZE];
        out[0] = if self.buy { 1 } else { 2 };
        out[1..4].copy_from_slice(&[self.base_decimals, self.price_decimals, self.quote_decimals]);
        for (i, (value, offset)) in [
            (&self.client_id, 152),
            (&self.account, 216),
            (&self.base, 248),
            (&self.quote, 264),
        ]
        .iter()
        .enumerate()
        {
            out[4 + i] = value.len() as u8;
            out[*offset..*offset + value.len()].copy_from_slice(value.as_bytes());
        }
        out[8..12].copy_from_slice(&self.base_epoch.to_be_bytes());
        out[12..16].copy_from_slice(&self.quote_epoch.to_be_bytes());
        for (i, value) in [
            self.runtime_epoch,
            self.ceiling_sequence,
            self.expires_at_ms,
            self.quantity_quanta,
            self.worst_price_quanta,
            self.max_quote_debit,
            self.min_quote_credit,
        ]
        .iter()
        .enumerate()
        {
            out[16 + i * 8..24 + i * 8].copy_from_slice(&value.to_be_bytes());
        }
        out[72..104].copy_from_slice(&self.preview_hash);
        out[104..136].copy_from_slice(&self.rules_hash);
        out[136..152].copy_from_slice(&self.credential_generation);
        Ok(out)
    }
    pub fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.len() != TICKET_SIZE || !matches!(raw[0], 1 | 2) {
            return Err("invalid ticket frame");
        }
        let read = |offset: usize, length: usize, max: usize| -> Result<String, &'static str> {
            if length > max {
                return Err("ticket name exceeds bound");
            }
            Ok(std::str::from_utf8(&raw[offset..offset + length])
                .map_err(|_| "invalid ticket text")?
                .into())
        };
        let num = |offset| u64::from_be_bytes(raw[offset..offset + 8].try_into().unwrap());
        let ticket = Self {
            buy: raw[0] == 1,
            base_decimals: raw[1],
            price_decimals: raw[2],
            quote_decimals: raw[3],
            client_id: read(152, usize::from(raw[4]), 64)?,
            account: read(216, usize::from(raw[5]), 32)?,
            base: read(248, usize::from(raw[6]), 16)?,
            quote: read(264, usize::from(raw[7]), 16)?,
            base_epoch: u32::from_be_bytes(raw[8..12].try_into().unwrap()),
            quote_epoch: u32::from_be_bytes(raw[12..16].try_into().unwrap()),
            runtime_epoch: num(16),
            ceiling_sequence: num(24),
            expires_at_ms: num(32),
            quantity_quanta: num(40),
            worst_price_quanta: num(48),
            max_quote_debit: num(56),
            min_quote_credit: num(64),
            preview_hash: raw[72..104].try_into().unwrap(),
            rules_hash: raw[104..136].try_into().unwrap(),
            credential_generation: raw[136..152].try_into().unwrap(),
        };
        if ticket.encode()? != raw {
            return Err("noncanonical operator ticket");
        }
        Ok(ticket)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Command {
    Status,
    Inspect(String),
    Approve(Box<Ticket>),
    Revoke {
        client_id: String,
        expected_sequence: u64,
    },
    Prepare {
        client_id: String,
        expected_sequence: u64,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Request {
    pub command: Command,
    pub correlation: [u8; 16],
}
impl Request {
    pub fn encode(&self) -> Result<[u8; REQUEST_SIZE], &'static str> {
        if self.correlation == [0; 16] {
            return Err("invalid review correlation");
        }
        let mut out = [0; REQUEST_SIZE];
        out[..8].copy_from_slice(b"TGREVW01");
        out[16..32].copy_from_slice(&self.correlation);
        let id = match &self.command {
            Command::Status => {
                out[8] = 1;
                None
            }
            Command::Inspect(id) => {
                out[8] = 2;
                Some(id)
            }
            Command::Approve(ticket) => {
                out[8] = 3;
                out[48..].copy_from_slice(&ticket.encode()?);
                None
            }
            Command::Revoke {
                client_id,
                expected_sequence,
            }
            | Command::Prepare {
                client_id,
                expected_sequence,
            } => {
                if *expected_sequence == 0 {
                    return Err("invalid review version");
                }
                out[8] = if matches!(self.command, Command::Prepare { .. }) {
                    5
                } else {
                    4
                };
                out[32..40].copy_from_slice(&expected_sequence.to_be_bytes());
                Some(client_id)
            }
        };
        if let Some(id) = id {
            if !name(id, 64, false) {
                return Err("invalid review identity");
            }
            out[9] = id.len() as u8;
            out[48..48 + id.len()].copy_from_slice(id.as_bytes());
        }
        Ok(out)
    }
    pub fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.len() != REQUEST_SIZE || &raw[..8] != b"TGREVW01" || raw[9] > 64 {
            return Err("invalid review request");
        }
        let id = || {
            std::str::from_utf8(&raw[48..48 + usize::from(raw[9])])
                .map(str::to_owned)
                .map_err(|_| "invalid review text")
        };
        let command = match raw[8] {
            1 => Command::Status,
            2 => Command::Inspect(id()?),
            3 => Command::Approve(Box::new(Ticket::decode(&raw[48..])?)),
            4 => Command::Revoke {
                client_id: id()?,
                expected_sequence: u64::from_be_bytes(raw[32..40].try_into().unwrap()),
            },
            5 => Command::Prepare {
                client_id: id()?,
                expected_sequence: u64::from_be_bytes(raw[32..40].try_into().unwrap()),
            },
            _ => return Err("unknown review command"),
        };
        let request = Self {
            command,
            correlation: raw[16..32].try_into().unwrap(),
        };
        if request.encode()? != raw {
            return Err("noncanonical review request");
        }
        Ok(request)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum ReviewState {
    Status = 1,
    Recorded = 2,
    Revoked = 3,
    Missing = 4,
    Deferred = 5,
    Refused = 6,
    Prepared = 7,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reply {
    pub state: ReviewState,
    pub mode: StopMode,
    pub correlation: [u8; 16],
    pub current_epoch: u64,
    pub sequence: u64,
    pub recorded_at_ms: u64,
    pub ceiling_sequence: u64,
    pub credential_generation: [u8; 16],
    pub ticket: Option<Ticket>,
}
impl Reply {
    pub fn validate_for(&self, request: &Request) -> Result<(), &'static str> {
        use ReviewState::*;
        let allowed = match &request.command {
            Command::Status => matches!(self.state, Status | Deferred | Refused),
            Command::Inspect(_) => matches!(
                self.state,
                Recorded | Revoked | Prepared | Missing | Deferred | Refused
            ),
            Command::Approve(_) => matches!(self.state, Recorded | Deferred | Refused),
            Command::Revoke { .. } => matches!(self.state, Revoked | Missing | Deferred | Refused),
            Command::Prepare { .. } => {
                matches!(self.state, Prepared | Missing | Deferred | Refused)
            }
        };
        if !allowed || self.correlation != request.correlation {
            return Err("review reply differs from requested action");
        }
        match &request.command {
            Command::Approve(ticket)
                if self.state == Recorded && self.ticket.as_ref() != Some(ticket.as_ref()) =>
            {
                Err("review reply differs from requested ticket")
            }
            Command::Inspect(id)
            | Command::Revoke { client_id: id, .. }
            | Command::Prepare { client_id: id, .. }
                if self
                    .ticket
                    .as_ref()
                    .is_some_and(|ticket| &ticket.client_id != id) =>
            {
                Err("review reply differs from requested identity")
            }
            Command::Revoke {
                expected_sequence, ..
            } if self.state == Revoked && self.sequence <= *expected_sequence => {
                Err("review revocation version did not advance")
            }
            Command::Prepare {
                expected_sequence, ..
            } if self.state == Prepared && self.sequence <= *expected_sequence => {
                Err("review preparation version did not advance")
            }
            _ => Ok(()),
        }
    }
    pub fn encode(&self) -> Result<[u8; REPLY_SIZE], &'static str> {
        if self.correlation == [0; 16]
            || self.current_epoch == 0
            || self.ticket.is_some()
                != matches!(
                    self.state,
                    ReviewState::Recorded | ReviewState::Revoked | ReviewState::Prepared
                )
            || self.ticket.is_some() != (self.sequence > 0 && self.recorded_at_ms > 0)
            || (self.ticket.is_none() && (self.sequence != 0 || self.recorded_at_ms != 0))
        {
            return Err("invalid review reply");
        }
        let mut out = [0; REPLY_SIZE];
        out[..8].copy_from_slice(b"TGREPLY1");
        out[8] = self.state as u8;
        out[9] = self.mode as u8;
        out[10] = u8::from(self.ticket.is_some());
        out[16..32].copy_from_slice(&self.correlation);
        out[32..40].copy_from_slice(&self.current_epoch.to_be_bytes());
        out[40..48].copy_from_slice(&self.sequence.to_be_bytes());
        out[48..56].copy_from_slice(&self.recorded_at_ms.to_be_bytes());
        out[56..64].copy_from_slice(&self.ceiling_sequence.to_be_bytes());
        out[64..80].copy_from_slice(&self.credential_generation);
        if let Some(ticket) = &self.ticket {
            out[80..].copy_from_slice(&ticket.encode()?);
        }
        Ok(out)
    }
    pub fn decode(raw: &[u8], expected: [u8; 16]) -> Result<Self, &'static str> {
        if raw.len() != REPLY_SIZE || &raw[..8] != b"TGREPLY1" || raw[10] > 1 {
            return Err("invalid review reply");
        }
        let state = match raw[8] {
            1 => ReviewState::Status,
            2 => ReviewState::Recorded,
            3 => ReviewState::Revoked,
            4 => ReviewState::Missing,
            5 => ReviewState::Deferred,
            6 => ReviewState::Refused,
            7 => ReviewState::Prepared,
            _ => return Err("unknown review state"),
        };
        let num = |offset| u64::from_be_bytes(raw[offset..offset + 8].try_into().unwrap());
        let reply = Self {
            state,
            mode: raw[9].try_into().map_err(|_| "invalid review mode")?,
            correlation: raw[16..32].try_into().unwrap(),
            current_epoch: num(32),
            sequence: num(40),
            recorded_at_ms: num(48),
            ceiling_sequence: num(56),
            credential_generation: raw[64..80].try_into().unwrap(),
            ticket: if raw[10] == 1 {
                Some(Ticket::decode(&raw[80..])?)
            } else {
                None
            },
        };
        if reply.correlation != expected || reply.encode()? != raw {
            return Err("uncorrelated or noncanonical review reply");
        }
        Ok(reply)
    }
}
