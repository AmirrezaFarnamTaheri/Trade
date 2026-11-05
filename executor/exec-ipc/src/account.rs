//! V2 account GET receipts. V1 stays readable; neither version confers money authority.
use crate::provision::{AccountResource, ACCOUNT_REQUEST_SIZE, MAX_ACCOUNT_BODY};

pub const REPLY_SIZE: usize = 144;
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum ObservationKind {
    Balances = 1,
    Fees = 2,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObservationReceipt {
    pub kind: ObservationKind,
    pub sequence: u64,
    pub runtime_epoch: u64,
    pub started_at_ms: u64,
    pub received_at_ms: u64,
    pub credential_generation: [u8; 16],
    pub response_digest: [u8; 32],
    pub event_hash: [u8; 32],
}

pub fn encode_request(
    resource: &AccountResource,
    correlation: [u8; 16],
) -> Result<[u8; ACCOUNT_REQUEST_SIZE], &'static str> {
    let mut frame = resource.encode(correlation)?;
    frame[..8].copy_from_slice(b"TGAREAD2");
    Ok(frame)
}
pub fn decode_request(raw: &[u8]) -> Result<(AccountResource, [u8; 16], bool), &'static str> {
    if raw.len() != ACCOUNT_REQUEST_SIZE {
        return Err("invalid account request");
    }
    let v2 = &raw[..8] == b"TGAREAD2";
    let mut frame: [u8; ACCOUNT_REQUEST_SIZE] = raw.try_into().unwrap();
    if v2 {
        frame[..8].copy_from_slice(b"TGAREAD1");
    }
    let (resource, correlation) = AccountResource::decode(&frame)?;
    Ok((resource, correlation, v2))
}

pub fn encode_reply(
    resource: &AccountResource,
    length: usize,
    correlation: [u8; 16],
    receipt: Option<&ObservationReceipt>,
) -> Result<[u8; REPLY_SIZE], &'static str> {
    resource.path()?;
    if !(1..=MAX_ACCOUNT_BODY).contains(&length) || correlation == [0; 16] {
        return Err("invalid account reply");
    }
    let kind = match resource {
        AccountResource::Balances => Some(ObservationKind::Balances),
        AccountResource::Fees => Some(ObservationKind::Fees),
        _ => None,
    };
    let mut frame = [0; REPLY_SIZE];
    frame[..8].copy_from_slice(b"TGARESP2");
    frame[8..24].copy_from_slice(&correlation);
    frame[24..28].copy_from_slice(&(length as u32).to_be_bytes());
    if let Some(value) = receipt {
        if kind != Some(value.kind)
            || value.sequence == 0
            || value.runtime_epoch == 0
            || value.started_at_ms == 0
            || value.received_at_ms < value.started_at_ms
            || value.received_at_ms - value.started_at_ms >= 12_000
            || value.credential_generation == [0; 16]
            || value.response_digest == [0; 32]
            || value.event_hash == [0; 32]
        {
            return Err("invalid account receipt");
        }
        frame[28] = value.kind as u8;
        for (offset, number) in [
            (32, value.sequence),
            (40, value.runtime_epoch),
            (48, value.started_at_ms),
            (56, value.received_at_ms),
        ] {
            frame[offset..offset + 8].copy_from_slice(&number.to_be_bytes());
        }
        frame[64..80].copy_from_slice(&value.credential_generation);
        frame[80..112].copy_from_slice(&value.response_digest);
        frame[112..144].copy_from_slice(&value.event_hash);
    } else if kind.is_some() {
        return Err("missing account receipt");
    }
    Ok(frame)
}
pub fn decode_reply(
    raw: &[u8],
    resource: &AccountResource,
    correlation: [u8; 16],
) -> Result<(usize, Option<ObservationReceipt>), &'static str> {
    if raw.len() != REPLY_SIZE {
        return Err("invalid account reply");
    }
    let length = u32::from_be_bytes(raw[24..28].try_into().unwrap()) as usize;
    let receipt = match raw[28] {
        0 => None,
        1 | 2 => Some(ObservationReceipt {
            kind: if raw[28] == 1 {
                ObservationKind::Balances
            } else {
                ObservationKind::Fees
            },
            sequence: u64::from_be_bytes(raw[32..40].try_into().unwrap()),
            runtime_epoch: u64::from_be_bytes(raw[40..48].try_into().unwrap()),
            started_at_ms: u64::from_be_bytes(raw[48..56].try_into().unwrap()),
            received_at_ms: u64::from_be_bytes(raw[56..64].try_into().unwrap()),
            credential_generation: raw[64..80].try_into().unwrap(),
            response_digest: raw[80..112].try_into().unwrap(),
            event_hash: raw[112..144].try_into().unwrap(),
        }),
        _ => return Err("invalid account receipt kind"),
    };
    if encode_reply(resource, length, correlation, receipt.as_ref())?.as_slice() != raw {
        return Err("noncanonical account reply");
    }
    Ok((length, receipt))
}
