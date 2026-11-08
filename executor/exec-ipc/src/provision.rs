//! Separate privileged provisioning contract. No claimed identity fields.
pub const PIPE: &str = r"\\.\pipe\TradingGYM.Privileged.v1";
pub const MAX_SECRET: usize = 4096;
pub const HEADER_SIZE: usize = 32;
pub const READY: &[u8; 8] = b"TGREADY1";
pub const ACK_SIZE: usize = 48;

pub fn header(length: usize, correlation: [u8; 16]) -> Result<[u8; HEADER_SIZE], &'static str> {
    if !(1..=MAX_SECRET).contains(&length) || correlation == [0; 16] {
        return Err("invalid provision bounds");
    }
    let mut out = [0; HEADER_SIZE];
    out[..8].copy_from_slice(b"TGPROV01");
    out[8..12].copy_from_slice(&(length as u32).to_be_bytes());
    out[16..].copy_from_slice(&correlation);
    Ok(out)
}
pub fn parse_header(raw: &[u8]) -> Result<(usize, [u8; 16]), &'static str> {
    if raw.len() != HEADER_SIZE || &raw[..8] != b"TGPROV01" || raw[12..16] != [0; 4] {
        return Err("invalid provision header");
    }
    let len = u32::from_be_bytes(raw[8..12].try_into().unwrap()) as usize;
    let id = raw[16..].try_into().unwrap();
    header(len, id)?;
    Ok((len, id))
}
pub fn committed(correlation: [u8; 16], generation: [u8; 16]) -> [u8; ACK_SIZE] {
    let mut out = [0; ACK_SIZE];
    out[..8].copy_from_slice(b"TGPCOM01");
    out[8..24].copy_from_slice(&correlation);
    out[24..40].copy_from_slice(&generation);
    // permission=0 means UNVERIFIED; no funded authority is granted.
    out
}
pub fn confirms(raw: &[u8], correlation: [u8; 16]) -> bool {
    raw.len() == ACK_SIZE
        && &raw[..8] == b"TGPCOM01"
        && raw[8..24] == correlation
        && raw[24..40] != [0; 16]
        && raw[40..] == [0; 8]
}
/// SCM startup arguments are not an IPC command. Only SCM administrators may start recovery.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StartupMode {
    Normal,
    CredentialRecovery,
    /// Explicit SCM-admin fault injection; main loop hangs, account reads stay disabled.
    StopIsolationDrill,
}
impl StartupMode {
    pub fn from_scm_arguments(args: &[String]) -> Result<Self, &'static str> {
        match args {
            [] => Ok(Self::Normal),
            [arg] if arg == "--credential-recovery" => Ok(Self::CredentialRecovery),
            [arg] if arg == "--stop-isolation-drill" => Ok(Self::StopIsolationDrill),
            _ => Err("invalid SCM startup arguments"),
        }
    }
    pub fn allows_account_read(self) -> bool {
        self == Self::Normal
    }
}

pub const ACCOUNT_REQUEST_SIZE: usize = 128;
pub const ACCOUNT_REPLY_SIZE: usize = 32;
pub const MAX_ACCOUNT_BODY: usize = 1_048_576;

/// No method, URL, headers, credential or caller identity crosses this contract.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AccountResource {
    Balances,
    Fees,
    KnownClientOrder(String),
    OpenOrders { page: u16, per_page: u8 },
    OrderHistory { page: u16, per_page: u8 },
}
impl AccountResource {
    pub fn path(&self) -> Result<String, &'static str> {
        match self {
            Self::Balances => Ok("/v1/account/balances".into()),
            Self::Fees => Ok("/v1/account/fee".into()),
            Self::OpenOrders { page, per_page } | Self::OrderHistory { page, per_page }
                if (1..=1000).contains(page) && (1..=100).contains(per_page) =>
            {
                let collection = if matches!(self, Self::OpenOrders { .. }) {
                    "openOrders"
                } else {
                    "orders"
                };
                Ok(format!(
                    "/v1/account/{collection}?page={page}&per_page={per_page}"
                ))
            }
            Self::KnownClientOrder(id)
                if !id.is_empty()
                    && id.len() <= 96
                    && id.as_bytes()[0].is_ascii_alphanumeric()
                    && id
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b)) =>
            {
                Ok(format!("/v1/account/orders/{id}"))
            }
            _ => Err("invalid known client order ID"),
        }
    }
    pub fn encode(
        &self,
        correlation: [u8; 16],
    ) -> Result<[u8; ACCOUNT_REQUEST_SIZE], &'static str> {
        self.path()?;
        if correlation == [0; 16] {
            return Err("invalid correlation");
        }
        let mut out = [0; ACCOUNT_REQUEST_SIZE];
        out[..8].copy_from_slice(b"TGAREAD1");
        out[16..32].copy_from_slice(&correlation);
        out[8] = match self {
            Self::Balances => 1,
            Self::Fees => 2,
            Self::KnownClientOrder(id) => {
                out[9] = id.len() as u8;
                out[32..32 + id.len()].copy_from_slice(id.as_bytes());
                3
            }
            Self::OpenOrders { page, per_page } | Self::OrderHistory { page, per_page } => {
                out[10..12].copy_from_slice(&page.to_be_bytes());
                out[12] = *per_page;
                if matches!(self, Self::OpenOrders { .. }) {
                    4
                } else {
                    5
                }
            }
        };
        Ok(out)
    }
    pub fn decode(raw: &[u8]) -> Result<(Self, [u8; 16]), &'static str> {
        if raw.len() != ACCOUNT_REQUEST_SIZE || &raw[..8] != b"TGAREAD1" || raw[13..16] != [0; 3] {
            return Err("invalid account request");
        }
        let len = usize::from(raw[9]);
        if len > 96 || raw[32 + len..].iter().any(|b| *b != 0) {
            return Err("invalid account request");
        }
        let resource = match (raw[8], len) {
            (1, 0) => Self::Balances,
            (2, 0) => Self::Fees,
            (3, 1..=96) => Self::KnownClientOrder(
                std::str::from_utf8(&raw[32..32 + len])
                    .map_err(|_| "invalid account request")?
                    .into(),
            ),
            (4 | 5, 0) => {
                let page = u16::from_be_bytes(raw[10..12].try_into().unwrap());
                let per_page = raw[12];
                if raw[8] == 4 {
                    Self::OpenOrders { page, per_page }
                } else {
                    Self::OrderHistory { page, per_page }
                }
            }
            _ => return Err("invalid account request"),
        };
        let id = raw[16..32].try_into().unwrap();
        if resource.encode(id)?.as_slice() != raw {
            return Err("invalid account request");
        }
        Ok((resource, id))
    }
}
pub fn account_reply(
    length: usize,
    correlation: [u8; 16],
) -> Result<[u8; ACCOUNT_REPLY_SIZE], &'static str> {
    if !(1..=MAX_ACCOUNT_BODY).contains(&length) || correlation == [0; 16] {
        return Err("invalid account reply");
    }
    let mut out = [0; ACCOUNT_REPLY_SIZE];
    out[..8].copy_from_slice(b"TGARESP1");
    out[8..24].copy_from_slice(&correlation);
    out[24..28].copy_from_slice(&(length as u32).to_be_bytes());
    Ok(out)
}
pub fn parse_account_reply(raw: &[u8], correlation: [u8; 16]) -> Result<usize, &'static str> {
    if raw.len() != ACCOUNT_REPLY_SIZE {
        return Err("invalid account reply");
    }
    let len = u32::from_be_bytes(raw[24..28].try_into().unwrap()) as usize;
    if account_reply(len, correlation)?.as_slice() != raw {
        return Err("invalid account reply");
    }
    Ok(len)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_bounds_reserved_fields_and_correlation() {
        for len in [1, MAX_SECRET] {
            let raw = header(len, [7; 16]).unwrap();
            assert_eq!(parse_header(&raw), Ok((len, [7; 16])));
            for n in 0..HEADER_SIZE {
                assert!(parse_header(&raw[..n]).is_err());
            }
        }
        for len in [0, MAX_SECRET + 1, usize::MAX] {
            assert!(header(len, [7; 16]).is_err());
        }
        assert!(header(1, [0; 16]).is_err());
        let mut raw = header(1, [7; 16]).unwrap();
        raw[12] = 1;
        assert!(parse_header(&raw).is_err());
        let mut ack = committed([7; 16], [8; 16]);
        assert!(confirms(&ack, [7; 16]));
        assert!(!confirms(&ack, [6; 16]));
        ack[40] = 1;
        assert!(!confirms(&ack, [7; 16]));
    }
}
