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
    if kind == AccountKind::KnownClientOrder {
        return normalized_order(result).map(|order| json!({"success":true,"result":order}));
    }
    if matches!(kind, AccountKind::OpenOrders | AccountKind::OrderHistory) {
        let request = value.get("request").ok_or("missing page request")?;
        let page = request["page"].as_u64().ok_or("invalid page request")?;
        let per_page = request["per_page"].as_u64().ok_or("invalid page request")?;
        if !(1..=1000).contains(&page) || !(1..=100).contains(&per_page) {
            return Err("invalid page request bounds");
        }
        let groups = result.as_object().ok_or("invalid order page")?;
        if groups.len() > 100 {
            return Err("unbounded order groups");
        }
        let mut orders = Vec::new();
        let mut identities = std::collections::BTreeSet::new();
        for rows in groups.values() {
            for row in rows.as_array().ok_or("invalid order group")? {
                if orders.len() >= per_page as usize {
                    return Err("unbounded order page");
                }
                let order = normalized_order(row)?;
                if !identities.insert(order["clientOrderId"].as_str().unwrap().to_owned()) {
                    return Err("duplicate page order identity");
                }
                orders.push(order);
            }
        }
        let mut out = json!({"success":true,"result":{"orders":orders},
                             "request":{"page":page,"per_page":per_page}});
        if let Some(info) = value.get("result_info") {
            if info.get("page").is_some() && info.get("per_page").is_some() {
                if info["page"].as_u64() != Some(page)
                    || info["per_page"].as_u64() != Some(per_page)
                {
                    return Err("order page echo mismatch");
                }
                out["result_info"] = json!({"page":page,"per_page":per_page});
            }
        }
        return Ok(out);
    }
    let rows = match kind {
        AccountKind::Balances => result.get("balances"),
        AccountKind::Fees => Some(result),
        _ => unreachable!(),
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
            _ => unreachable!(),
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
        _ => unreachable!(),
    })
}

// Fixed-point decimal digits avoid both binary rounding and a new money dependency.
type OrderAmount = [u8; 104];
fn order_amount(
    value: Option<&Value>,
    positive: bool,
) -> Result<(&str, OrderAmount), &'static str> {
    let text = amount(value, false)?;
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    if text.len() > 80 || fraction.len() > 24 {
        return Err("unsupported order amount precision");
    }
    let mut digits = [0; 104];
    let offset = 80 - whole.len();
    for (i, digit) in whole.bytes().chain(fraction.bytes()).enumerate() {
        digits[offset + i] = digit - b'0';
    }
    if positive && digits == [0; 104] {
        return Err("zero order amount");
    }
    Ok((text, digits))
}
fn order_text<'a>(row: &'a Value, field: &str, max: usize) -> Result<&'a str, &'static str> {
    row.get(field)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= max && s.is_ascii())
        .ok_or("invalid order text")
}
/// The shared fill-timestamp profile in `contracts/v1/fixtures/fill-timestamps.json`:
/// an epoch integer in range, or RFC 3339 with seconds, optional 1..=9 fraction
/// digits, `Z` or `±HH:MM`, and a real calendar date and time.
pub fn fill_timestamp(value: &Value) -> bool {
    if let Some(n) = value.as_u64() {
        return (946_684_800..=4_102_444_800_000).contains(&n);
    }
    let Some(text) = value.as_str() else {
        return false;
    };
    let b = text.as_bytes();
    let digits = |range: std::ops::Range<usize>| -> Option<u32> {
        let part = b.get(range)?;
        part.iter().all(u8::is_ascii_digit).then(|| {
            part.iter()
                .fold(0u32, |acc, d| acc * 10 + u32::from(d - b'0'))
        })
    };
    if b.len() < 20
        || b[4] != b'-'
        || b[7] != b'-'
        || b[10] != b'T'
        || b[13] != b':'
        || b[16] != b':'
    {
        return false;
    }
    let (Some(year), Some(month), Some(day), Some(hour), Some(minute), Some(second)) = (
        digits(0..4),
        digits(5..7),
        digits(8..10),
        digits(11..13),
        digits(14..16),
        digits(17..19),
    ) else {
        return false;
    };
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let month_days = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    if !(1..=12).contains(&month)
        || day == 0
        || day > month_days[month as usize - 1]
        || hour > 23
        || minute > 59
        || second > 59
    {
        return false;
    }
    let mut rest = &b[19..];
    if let Some(fraction) = rest.strip_prefix(b".") {
        let count = fraction.iter().take_while(|c| c.is_ascii_digit()).count();
        if !(1..=9).contains(&count) {
            return false;
        }
        rest = &fraction[count..];
    }
    match rest {
        [b'Z'] => true,
        [sign, h1, h2, b':', m1, m2] if b"+-".contains(sign) => {
            [h1, h2, m1, m2].iter().all(|c| c.is_ascii_digit())
                && (h1 - b'0') * 10 + (h2 - b'0') <= 23
                && (m1 - b'0') * 10 + (m2 - b'0') <= 59
        }
        _ => false,
    }
}

fn normalized_order(row: &Value) -> Result<Value, &'static str> {
    let id = order_text(row, "clientOrderId", 96)?;
    exec_ipc::provision::AccountResource::KnownClientOrder(id.into()).path()?;
    let symbol = order_text(row, "symbol", 32)?;
    let side = order_text(row, "side", 4)?;
    let status = order_text(row, "status", 128)?;
    if symbol.len() < 3
        || !symbol
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
        || !matches!(side, "BUY" | "SELL")
        || !status
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_ .:-".contains(&b))
    {
        return Err("invalid order identity or status");
    }
    let (quantity, requested) = order_amount(row.get("origQty"), true)?;
    let (filled, executed) = order_amount(row.get("executedQty"), false)?;
    if executed > requested {
        return Err("order overfill");
    }
    let mut out = json!({"clientOrderId":id,"symbol":symbol,"side":side,"status":status,
                         "origQty":quantity,"executedQty":filled});
    if let Some(fills) = row.get("fills").filter(|value| !value.is_null()) {
        let fills = fills
            .as_array()
            .filter(|items| items.len() <= 256)
            .ok_or("invalid fill list")?;
        let mut clean = Vec::new();
        let mut total = [0u8; 104];
        for fill in fills {
            let (quantity, digits) = order_amount(fill.get("quantity"), true)?;
            let (price, _) = order_amount(fill.get("price"), true)?;
            let (fee, _) = order_amount(fill.get("fee"), false)?;
            let asset = order_text(fill, "feeAsset", 20)?;
            if !asset
                .bytes()
                .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
            {
                return Err("invalid fill fee asset");
            }
            let timestamp = fill.get("timestamp").ok_or("missing fill timestamp")?;
            if !fill_timestamp(timestamp) {
                return Err("invalid fill timestamp");
            }
            let mut carry = 0;
            for i in (0..104).rev() {
                let sum = total[i] + digits[i] + carry;
                total[i] = sum % 10;
                carry = sum / 10;
            }
            if carry != 0 || total > requested {
                return Err("fill quantity overflow");
            }
            clean.push(json!({"quantity":quantity,"price":price,"fee":fee,
                              "feeAsset":asset,"timestamp":timestamp}));
        }
        if !fills.is_empty() && total != executed {
            return Err("fill quantity mismatch");
        }
        out["fills"] = Value::Array(clean);
    }
    Ok(out)
}

impl AccountObservation {
    /// The page identity is taken from the service request, never the venue body.
    #[allow(clippy::too_many_arguments)]
    pub fn from_page_response(
        resource: &exec_ipc::provision::AccountResource,
        raw: &[u8],
        generation: [u8; 16],
        runtime_epoch: u64,
        request_id: [u8; 16],
        started_at_ms: u64,
        received_at_ms: u64,
    ) -> Result<Self, &'static str> {
        use exec_ipc::provision::AccountResource;
        resource.path()?;
        let (kind, page, per_page) = match resource {
            AccountResource::OpenOrders { page, per_page } => {
                (AccountKind::OpenOrders, page, per_page)
            }
            AccountResource::OrderHistory { page, per_page } => {
                (AccountKind::OrderHistory, page, per_page)
            }
            _ => return Err("not an order page request"),
        };
        let mut body = parse(raw)?;
        if !body.is_object() {
            return Err("invalid order page response");
        }
        body["request"] = json!({"page":page,"per_page":per_page});
        let observation = Self {
            kind,
            generation,
            runtime_epoch,
            request_id,
            started_at_ms,
            received_at_ms,
            response_digest: exec_store::hash_event(&[0; 32], raw),
            data: normalized(kind, &body)?,
        };
        observation.validate()?;
        Ok(observation)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn from_order_response(
        client_id: &str,
        raw: &[u8],
        generation: [u8; 16],
        runtime_epoch: u64,
        request_id: [u8; 16],
        started_at_ms: u64,
        received_at_ms: u64,
    ) -> Result<Self, &'static str> {
        let value = Self::from_response(
            AccountKind::KnownClientOrder,
            raw,
            generation,
            runtime_epoch,
            request_id,
            started_at_ms,
            received_at_ms,
        )?;
        if value.data["result"]["clientOrderId"].as_str() != Some(client_id) {
            return Err("order response identity mismatch");
        }
        Ok(value)
    }
    pub(crate) fn key(&self) -> (AccountKind, String) {
        if matches!(
            self.kind,
            AccountKind::OpenOrders | AccountKind::OrderHistory
        ) {
            return (
                self.kind,
                format!(
                    "{}/{}",
                    self.data["request"]["page"], self.data["request"]["per_page"]
                ),
            );
        }
        (
            self.kind,
            self.data["result"]["clientOrderId"]
                .as_str()
                .unwrap_or("")
                .into(),
        )
    }
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
        if matches!(kind, AccountKind::OpenOrders | AccountKind::OrderHistory) {
            return Err("page requires a service-owned request");
        }
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
            3 => AccountKind::KnownClientOrder,
            4 => AccountKind::OpenOrders,
            5 => AccountKind::OrderHistory,
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
