//! Offline, version-distinct operator-review v2 wire. No service listener or order transport.
//!
//! This codec does not authenticate a principal, reserve money, prepare a venue
//! order, or create funded authority. The installed service remains on v1.
//! Only future *submission-side* approvals/preparations narrow client IDs;
//! legacy inspection/revocation retains the original read-side grammar.
use crate::review::{self, Command, Reply, Request, REPLY_SIZE, REQUEST_SIZE};

const REQUEST_MAGIC: [u8; 8] = *b"TGREVW02";
const REPLY_MAGIC: [u8; 8] = *b"TGREPLY2";

/// Check the documented Wallex submit-side ASCII identifier grammar.
pub fn valid_submit_client_id(client_id: &str) -> Result<(), &'static str> {
    if !client_id.is_empty()
        && client_id.len() <= 64
        && client_id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_')
    {
        Ok(())
    } else {
        Err("invalid v2 submit client_id")
    }
}

/// A v2-only review request. No deployed listener accepts these frames.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequestV2(pub Request);

impl RequestV2 {
    fn validate_submission_identity(&self) -> Result<(), &'static str> {
        match &self.0.command {
            Command::Approve(ticket) => valid_submit_client_id(&ticket.client_id),
            Command::Prepare { client_id, .. } => valid_submit_client_id(client_id),
            // Old venue-provided IDs can still be queried or revoked.
            Command::Inspect(_) | Command::Revoke { .. } | Command::Status => Ok(()),
        }
    }

    /// Encode canonical v1-compatible fields using the distinct v2 magic.
    pub fn encode(&self) -> Result<[u8; REQUEST_SIZE], &'static str> {
        self.validate_submission_identity()?;
        let mut raw = self.0.encode()?;
        raw[..8].copy_from_slice(&REQUEST_MAGIC);
        Ok(raw)
    }

    /// Reject v1 frames and all invalid v2 padding, identities, and evidence.
    pub fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.len() != REQUEST_SIZE || raw[..8] != REQUEST_MAGIC {
            return Err("invalid v2 review request frame");
        }
        let mut legacy = [0_u8; REQUEST_SIZE];
        legacy.copy_from_slice(raw);
        legacy[..8].copy_from_slice(b"TGREVW01");
        let req = Self(Request::decode(&legacy)?);
        if req.encode()?.as_slice() != raw {
            return Err("noncanonical v2 review request");
        }
        Ok(req)
    }
}

/// Version-separated review evidence; never a trading or funded-order capability.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReplyV2(pub Reply);

impl ReplyV2 {
    /// Encode a receipt only if its state, correlation and ticket match the v2 intent.
    pub fn encode_for(&self, request: &RequestV2) -> Result<[u8; REPLY_SIZE], &'static str> {
        request.encode()?;
        self.0.validate_for(&request.0)?;
        let mut raw = self.0.encode()?;
        raw[..8].copy_from_slice(&REPLY_MAGIC);
        Ok(raw)
    }

    /// Reject cross-version and miscorrelated receipts before any consumer can use them.
    pub fn decode_for(raw: &[u8], request: &RequestV2) -> Result<Self, &'static str> {
        request.encode()?;
        if raw.len() != REPLY_SIZE || raw[..8] != REPLY_MAGIC {
            return Err("invalid v2 review reply frame");
        }
        let mut legacy = [0_u8; REPLY_SIZE];
        legacy.copy_from_slice(raw);
        legacy[..8].copy_from_slice(b"TGREPLY1");
        let reply = Reply::decode(&legacy, request.0.correlation)?;
        reply.validate_for(&request.0)?;
        let out = Self(reply);
        if out.encode_for(request)?.as_slice() != raw {
            return Err("noncanonical v2 review reply");
        }
        Ok(out)
    }
}
