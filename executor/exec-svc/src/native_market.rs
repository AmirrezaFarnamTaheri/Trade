//! Exact public depth used by the native arm/admission loop. Receipt time is local, not a venue sequence.
use exec_core::kernel::Exact;
use serde::Deserialize;
use serde_json::value::RawValue;

#[derive(Deserialize)]
struct Response {
    success: bool,
    result: Book,
}
#[derive(Deserialize)]
struct Book {
    bid: Vec<Level>,
    ask: Vec<Level>,
}
#[derive(Deserialize)]
struct Level {
    price: Box<RawValue>,
    quantity: Box<RawValue>,
}

fn amount(raw: &RawValue) -> Result<Exact, &'static str> {
    let raw = raw.get();
    let text = if raw.starts_with('"') {
        serde_json::from_str::<String>(raw).map_err(|_| "invalid book amount")?
    } else {
        raw.to_owned()
    };
    let (decimal, exponent) = text
        .split_once(['e', 'E'])
        .map_or((text.as_str(), "0"), |parts| parts);
    let mut value = Exact::parse(decimal)
        .filter(|value| !value.is_zero())
        .ok_or("invalid book amount")?;
    let exponent: i32 = exponent.parse().map_err(|_| "invalid book exponent")?;
    if !(-38..=38).contains(&exponent) {
        return Err("book exponent overflow");
    }
    let scale = i64::from(value.scale) - i64::from(exponent);
    if scale < 0 {
        value.mantissa = value
            .mantissa
            .checked_mul(
                10u128
                    .checked_pow((-scale) as u32)
                    .ok_or("book exponent overflow")?,
            )
            .ok_or("book amount overflow")?;
        value.scale = 0;
    } else if scale <= 38 {
        value.scale = scale as u32;
    } else {
        return Err("book precision overflow");
    }
    Ok(value)
}

#[derive(Clone, Debug)]
pub struct MarketObservation {
    symbol: String,
    bid: Exact,
    ask: Exact,
    received_at_ms: u64,
    bids: Vec<(Exact, Exact)>,
}

impl MarketObservation {
    /// Call only with bytes received by the service's fixed public HTTPS transport.
    pub fn from_response(
        symbol: &str,
        raw: &[u8],
        started_at_ms: u64,
        received_at_ms: u64,
    ) -> Result<Self, &'static str> {
        if !(3..=32).contains(&symbol.len())
            || !symbol
                .bytes()
                .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit())
            || raw.is_empty()
            || raw.len() > exec_ipc::provision::MAX_ACCOUNT_BODY
            || started_at_ms == 0
            || received_at_ms < started_at_ms
            || received_at_ms - started_at_ms >= 12_000
        {
            return Err("invalid native market receipt");
        }
        let value: Response = serde_json::from_slice(raw).map_err(|_| "invalid book response")?;
        if !value.success
            || value.result.bid.is_empty()
            || value.result.ask.is_empty()
            || value.result.bid.len() > 1000
            || value.result.ask.len() > 1000
        {
            return Err("empty or unconfirmed book");
        }
        let side = |rows: &[Level], bids: bool| -> Result<Exact, &'static str> {
            let mut last = None;
            for row in rows {
                let price = amount(&row.price)?;
                amount(&row.quantity)?;
                if let Some(previous) = last {
                    let order = price
                        .cmp_value(previous)
                        .ok_or("book comparison overflow")?;
                    if (bids && order != std::cmp::Ordering::Less)
                        || (!bids && order != std::cmp::Ordering::Greater)
                    {
                        return Err("noncanonical depth order");
                    }
                }
                last = Some(price);
            }
            amount(&rows[0].price)
        };
        let bid = side(&value.result.bid, true)?;
        let ask = side(&value.result.ask, false)?;
        if bid.cmp_value(ask).ok_or("book comparison overflow")? != std::cmp::Ordering::Less {
            return Err("crossed native book");
        }
        let bids = value
            .result
            .bid
            .iter()
            .map(|row| Ok((amount(&row.price)?, amount(&row.quantity)?)))
            .collect::<Result<_, &'static str>>()?;
        Ok(Self {
            symbol: symbol.into(),
            bid,
            ask,
            received_at_ms,
            bids,
        })
    }
    pub fn symbol(&self) -> &str {
        &self.symbol
    }
    pub fn bid(&self) -> Exact {
        self.bid
    }
    pub fn ask(&self) -> Exact {
        self.ask
    }
    pub fn received_at_ms(&self) -> u64 {
        self.received_at_ms
    }
    pub fn liquidation_value(&self, quantity: Exact) -> Option<Exact> {
        exec_core::kernel::walk(&self.bids, quantity)
    }
    pub fn is_fresh(&self, now_ms: u64, max_age_ms: u64) -> bool {
        now_ms >= self.received_at_ms && now_ms - self.received_at_ms <= max_age_ms.min(120_000)
    }
}
