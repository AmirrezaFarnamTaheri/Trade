//! Administrator-only limit metadata. No identity claim or money permission on this wire.
pub const SIZE: usize = 96;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Ceiling {
    pub currency: String,
    pub unit_epoch: u32,
    pub decimals: u8,
    pub capital_quanta: u64,
}
impl Ceiling {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.currency.is_empty()
            || self.currency.len() > 16
            || !self
                .currency
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
            || self.decimals > 18
            || self.unit_epoch == 0
        {
            return Err("invalid ceiling currency or scale");
        }
        Ok(())
    }
    pub fn from_amount(
        currency: &str,
        unit_epoch: u32,
        decimals: u8,
        amount: &str,
    ) -> Result<Self, &'static str> {
        let mut value = Self {
            currency: currency.into(),
            unit_epoch,
            decimals,
            capital_quanta: 0,
        };
        value.validate()?;
        if amount.is_empty() || amount.len() > 40 {
            return Err("invalid ceiling amount");
        }
        let (whole, fraction) = amount.split_once('.').unwrap_or((amount, ""));
        if whole.is_empty()
            || (amount.contains('.') && fraction.is_empty())
            || fraction.len() > usize::from(decimals)
            || !whole
                .bytes()
                .chain(fraction.bytes())
                .all(|b| b.is_ascii_digit())
        {
            return Err("ceiling amount must be exact nonnegative decimal text");
        }
        let mut quanta = 0u64;
        for byte in whole
            .bytes()
            .chain(fraction.bytes())
            .chain(std::iter::repeat_n(
                b'0',
                usize::from(decimals) - fraction.len(),
            ))
        {
            quanta = quanta
                .checked_mul(10)
                .and_then(|n| n.checked_add(u64::from(byte - b'0')))
                .ok_or("ceiling amount overflow")?;
        }
        value.capital_quanta = quanta;
        Ok(value)
    }
    pub fn amount(&self) -> Result<String, &'static str> {
        self.validate()?;
        if self.decimals == 0 {
            return Ok(self.capital_quanta.to_string());
        }
        let factor = 10u64.pow(u32::from(self.decimals));
        Ok(format!(
            "{}.{:0width$}",
            self.capital_quanta / factor,
            self.capital_quanta % factor,
            width = usize::from(self.decimals)
        ))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CeilingCommand {
    Get,
    Set {
        expected_sequence: u64,
        ceiling: Ceiling,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CeilingRequest {
    pub command: CeilingCommand,
    pub correlation: [u8; 16],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CeilingReply {
    pub sequence: u64,
    pub ceiling: Option<Ceiling>,
    pub correlation: [u8; 16],
}

fn frame(
    magic: &[u8; 8],
    code: u8,
    correlation: [u8; 16],
    sequence: u64,
    ceiling: Option<&Ceiling>,
) -> Result<[u8; SIZE], &'static str> {
    if correlation == [0; 16] {
        return Err("invalid ceiling correlation");
    }
    let mut out = [0; SIZE];
    out[..8].copy_from_slice(magic);
    out[8] = code;
    out[16..32].copy_from_slice(&correlation);
    out[40..48].copy_from_slice(&sequence.to_be_bytes());
    if let Some(value) = ceiling {
        value.validate()?;
        out[9] = value.decimals;
        out[10] = value.currency.len() as u8;
        out[32..40].copy_from_slice(&value.capital_quanta.to_be_bytes());
        out[48..48 + value.currency.len()].copy_from_slice(value.currency.as_bytes());
        out[64..68].copy_from_slice(&value.unit_epoch.to_be_bytes());
    }
    Ok(out)
}
struct Frame {
    code: u8,
    correlation: [u8; 16],
    sequence: u64,
    ceiling: Option<Ceiling>,
}
fn parse(raw: &[u8], magic: &[u8; 8]) -> Result<Frame, &'static str> {
    if raw.len() != SIZE || &raw[..8] != magic || raw[10] > 16 {
        return Err("invalid ceiling frame");
    }
    let currency = std::str::from_utf8(&raw[48..48 + usize::from(raw[10])])
        .map_err(|_| "invalid ceiling currency")?;
    let value = (!currency.is_empty()).then(|| Ceiling {
        currency: currency.into(),
        unit_epoch: u32::from_be_bytes(raw[64..68].try_into().unwrap()),
        decimals: raw[9],
        capital_quanta: u64::from_be_bytes(raw[32..40].try_into().unwrap()),
    });
    let correlation = raw[16..32].try_into().unwrap();
    let sequence = u64::from_be_bytes(raw[40..48].try_into().unwrap());
    if frame(magic, raw[8], correlation, sequence, value.as_ref())? != raw {
        return Err("noncanonical ceiling frame");
    }
    Ok(Frame {
        code: raw[8],
        correlation,
        sequence,
        ceiling: value,
    })
}
impl CeilingRequest {
    pub fn encode(&self) -> Result<[u8; SIZE], &'static str> {
        match &self.command {
            CeilingCommand::Get => frame(b"TGCEIL01", 1, self.correlation, 0, None),
            CeilingCommand::Set {
                expected_sequence,
                ceiling,
            } => frame(
                b"TGCEIL01",
                2,
                self.correlation,
                *expected_sequence,
                Some(ceiling),
            ),
        }
    }
    pub fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        let Frame {
            code,
            correlation,
            sequence,
            ceiling,
        } = parse(raw, b"TGCEIL01")?;
        let command = match (code, sequence, ceiling) {
            (1, 0, None) => CeilingCommand::Get,
            (2, expected_sequence, Some(ceiling)) => CeilingCommand::Set {
                expected_sequence,
                ceiling,
            },
            _ => return Err("invalid ceiling command"),
        };
        Ok(Self {
            command,
            correlation,
        })
    }
}
impl CeilingReply {
    pub fn encode(&self) -> Result<[u8; SIZE], &'static str> {
        if self.ceiling.is_none() != (self.sequence == 0) {
            return Err("invalid ceiling receipt version");
        }
        frame(
            b"TGCACK01",
            u8::from(self.ceiling.is_some()),
            self.correlation,
            self.sequence,
            self.ceiling.as_ref(),
        )
    }
    pub fn decode(raw: &[u8], expected: [u8; 16]) -> Result<Self, &'static str> {
        let Frame {
            code,
            correlation,
            sequence,
            ceiling,
        } = parse(raw, b"TGCACK01")?;
        let result = Self {
            sequence,
            ceiling,
            correlation,
        };
        if correlation != expected
            || code != u8::from(result.ceiling.is_some())
            || result.encode()? != raw
        {
            return Err("invalid ceiling acknowledgment");
        }
        Ok(result)
    }
}
