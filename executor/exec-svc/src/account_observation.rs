//! Sanitized, exact account receipts. Value/locked are observations, never spendable funds.
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};
use std::fmt;

pub use exec_ipc::account::ObservationKind as AccountKind;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AccountObservation {
    kind: AccountKind,
    generation: [u8; 16],
    runtime_epoch: u64,
    request_id: [u8; 16],
    started_at_ms: u64,
    received_at_ms: u64,
    response_digest: [u8; 32],
    data: Value,
}

// serde_json::Value otherwise silently overwrites duplicate object identities.
struct Unique(Value);
impl<'de> Deserialize<'de> for Unique {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct UniqueVisitor;
        impl<'de> Visitor<'de> for UniqueVisitor {
            type Value = Unique;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("bounded unique JSON")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Unique, E> {
                Ok(Unique(Value::Bool(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> Result<Unique, E> {
                serde_json::Number::from_f64(v)
                    .map(|n| Unique(Value::Number(n)))
                    .ok_or_else(|| E::custom("invalid JSON number"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Unique, E> {
                Ok(Unique(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Unique, A::Error> {
                let mut items = Vec::new();
                while let Some(Unique(value)) = seq.next_element()? {
                    items.push(value);
                }
                Ok(Unique(Value::Array(items)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Unique, A::Error> {
                let mut items = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if items.contains_key(&key) {
                        return Err(de::Error::custom("duplicate JSON field"));
                    }
                    let Unique(value) = map.next_value()?;
                    items.insert(key, value);
                }
                Ok(Unique(Value::Object(items)))
            }
        }
        deserializer.deserialize_any(UniqueVisitor)
    }
}

fn parse(raw: &[u8]) -> Result<Value, &'static str> {
    if !(1..=exec_ipc::provision::MAX_ACCOUNT_BODY).contains(&raw.len()) {
        return Err("invalid account response bounds");
    }
    let mut decoder = serde_json::Deserializer::from_slice(raw);
    let Unique(value) = Unique::deserialize(&mut decoder).map_err(|_| "invalid account JSON")?;
    decoder.end().map_err(|_| "trailing account data")?;
    Ok(value)
}

/// Check decoded fields as well as raw bytes: JSON escapes must not bypass key-echo refusal.
pub fn reject_credential_echo(raw: &[u8], key: &[u8]) -> Result<(), &'static str> {
    fn contains(value: &Value, key: &[u8]) -> bool {
        let matches = |text: &[u8]| text.windows(key.len()).any(|part| part == key);
        match value {
            Value::String(text) => matches(text.as_bytes()),
            Value::Array(items) => items.iter().any(|value| contains(value, key)),
            Value::Object(items) => items
                .iter()
                .any(|(name, value)| matches(name.as_bytes()) || contains(value, key)),
            Value::Number(number) => matches(number.to_string().as_bytes()),
            _ => false,
        }
    }
    if key.is_empty() || contains(&parse(raw)?, key) {
        return Err("credential echo refused");
    }
    Ok(())
}

fn amount(value: Option<&Value>, fee: bool) -> Result<&str, &'static str> {
    let value = value
        .and_then(Value::as_str)
        .ok_or("inexact account amount")?;
    if value.is_empty() || value.len() > 256 {
        return Err("invalid account amount bounds");
    }
    let (whole, fraction) = value
        .split_once('.')
        .map_or((value, None), |(a, b)| (a, Some(b)));
    if whole.is_empty()
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || fraction.is_some_and(|s| s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()))
        || (fee && whole.bytes().any(|b| b != b'0'))
    {
        return Err("invalid account amount");
    }
    Ok(value)
}

fn normalized(kind: AccountKind, value: &Value) -> Result<Value, &'static str> {
    if value.get("success") != Some(&Value::Bool(true)) {
        return Err("unconfirmed account response");
    }
    let result = value.get("result").ok_or("missing account result")?;
    let rows = match kind {
        AccountKind::Balances => result.get("balances"),
        AccountKind::Fees => Some(result),
    }
    .and_then(Value::as_object)
    .ok_or("invalid account collection")?;
    if rows.len() > 1024 {
        return Err("unbounded account collection");
    }
    let mut out = Map::new();
    for (name, row) in rows {
        let fields = match kind {
            AccountKind::Balances => ["value", "locked"],
            AccountKind::Fees => ["makerFeeRate", "takerFeeRate"],
        };
        // Account-level fee metadata does not describe an instrument's cost.
        if kind == AccountKind::Fees && !fields.iter().any(|key| row.get(key).is_some()) {
            continue;
        }
        let bounds = if kind == AccountKind::Balances {
            1..=20
        } else {
            3..=32
        };
        if !bounds.contains(&name.len()) || !name.bytes().all(|b| b.is_ascii_alphanumeric()) {
            return Err("invalid account row identity");
        }
        let name = name.to_ascii_uppercase();
        let first = amount(row.get(fields[0]), kind == AccountKind::Fees)?;
        let second = amount(row.get(fields[1]), kind == AccountKind::Fees)?;
        let row = Value::Object(Map::from_iter([
            (fields[0].into(), Value::String(first.into())),
            (fields[1].into(), Value::String(second.into())),
        ]));
        if out.insert(name, row).is_some() {
            return Err("duplicate account row identity");
        }
    }
    Ok(match kind {
        AccountKind::Balances => json!({"success":true,"result":{"balances":out}}),
        AccountKind::Fees => json!({"success":true,"result":out}),
    })
}

impl AccountObservation {
    /// Inputs must come from the service's fixed-origin transport, not an IPC caller.
    #[allow(clippy::too_many_arguments)]
    pub fn from_response(
        kind: AccountKind,
        raw: &[u8],
        generation: [u8; 16],
        runtime_epoch: u64,
        request_id: [u8; 16],
        started_at_ms: u64,
        received_at_ms: u64,
    ) -> Result<Self, &'static str> {
        let observation = Self {
            kind,
            generation,
            runtime_epoch,
            request_id,
            started_at_ms,
            received_at_ms,
            response_digest: exec_store::hash_event(&[0; 32], raw),
            data: normalized(kind, &parse(raw)?)?,
        };
        observation.validate()?;
        Ok(observation)
    }
    fn validate(&self) -> Result<(), &'static str> {
        if self.generation == [0; 16]
            || self.runtime_epoch == 0
            || self.request_id == [0; 16]
            || self.started_at_ms == 0
            || self.received_at_ms < self.started_at_ms
            || self.received_at_ms - self.started_at_ms >= 12_000
            || self.response_digest == [0; 32]
        {
            return Err("invalid account receipt context");
        }
        Ok(())
    }
    pub fn kind(&self) -> AccountKind {
        self.kind
    }
    pub fn generation(&self) -> [u8; 16] {
        self.generation
    }
    pub fn request_id(&self) -> [u8; 16] {
        self.request_id
    }
    pub fn started_at_ms(&self) -> u64 {
        self.started_at_ms
    }
    pub fn received_at_ms(&self) -> u64 {
        self.received_at_ms
    }
    pub fn data(&self) -> &Value {
        &self.data
    }
    pub(crate) fn receipt(
        &self,
        sequence: u64,
        event_hash: [u8; 32],
    ) -> exec_ipc::account::ObservationReceipt {
        exec_ipc::account::ObservationReceipt {
            kind: self.kind,
            sequence,
            runtime_epoch: self.runtime_epoch,
            started_at_ms: self.started_at_ms,
            received_at_ms: self.received_at_ms,
            credential_generation: self.generation,
            response_digest: self.response_digest,
            event_hash,
        }
    }
    pub fn is_fresh(&self, generation: [u8; 16], epoch: u64, now: u64, max_age: u64) -> bool {
        (1..=30_000).contains(&max_age)
            && generation == self.generation
            && epoch == self.runtime_epoch
            && now >= self.received_at_ms
            && now - self.started_at_ms <= max_age
    }

    pub(crate) fn encode(&self) -> Result<Vec<u8>, &'static str> {
        self.validate()?;
        let data = serde_json::to_vec(&self.data).map_err(|_| "account encoding failed")?;
        if data.len() > exec_ipc::provision::MAX_ACCOUNT_BODY - 128 {
            return Err("account receipt too large");
        }
        let mut raw = vec![self.kind as u8];
        raw.extend_from_slice(&self.generation);
        for number in [self.runtime_epoch, self.started_at_ms, self.received_at_ms] {
            raw.extend_from_slice(&number.to_be_bytes());
        }
        raw.extend_from_slice(&self.request_id);
        raw.extend_from_slice(&self.response_digest);
        raw.extend_from_slice(&data);
        Ok(raw)
    }
    pub(crate) fn decode(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.len() < 90 {
            return Err("short account receipt");
        }
        let kind = match raw[0] {
            1 => AccountKind::Balances,
            2 => AccountKind::Fees,
            _ => return Err("invalid account kind"),
        };
        let observation = Self {
            kind,
            generation: raw[1..17].try_into().unwrap(),
            runtime_epoch: u64::from_be_bytes(raw[17..25].try_into().unwrap()),
            started_at_ms: u64::from_be_bytes(raw[25..33].try_into().unwrap()),
            received_at_ms: u64::from_be_bytes(raw[33..41].try_into().unwrap()),
            request_id: raw[41..57].try_into().unwrap(),
            response_digest: raw[57..89].try_into().unwrap(),
            data: parse(&raw[89..])?,
        };
        if normalized(kind, &observation.data)? != observation.data || observation.encode()? != raw
        {
            return Err("noncanonical account receipt");
        }
        Ok(observation)
    }
}
