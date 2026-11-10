//! Reference money rules in exact integer arithmetic, shared with the Python simulator through fixtures
//! (ADR 0005). Pure functions only: no I/O, no authority, no venue access.
//!
//! Amounts are decimal strings parsed into (mantissa, scale) with u128 mantissas; comparisons and products
//! align scales exactly. Anything that would overflow is refused rather than rounded.

/// An exact non-negative decimal: value = mantissa / 10^scale.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Exact {
    pub mantissa: u128,
    pub scale: u32,
}

impl Exact {
    pub fn parse(text: &str) -> Option<Self> {
        let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
        if whole.is_empty()
            || !whole.bytes().all(|b| b.is_ascii_digit())
            || !fraction.bytes().all(|b| b.is_ascii_digit())
            || (text.contains('.') && fraction.is_empty())
            || fraction.len() > 30
        {
            return None;
        }
        let digits = format!("{whole}{fraction}");
        Some(Self {
            mantissa: digits.parse().ok()?,
            scale: fraction.len() as u32,
        })
    }

    fn rescale(self, scale: u32) -> Option<u128> {
        self.mantissa
            .checked_mul(10u128.checked_pow(scale.checked_sub(self.scale)?)?)
    }

    /// Exact comparison of two values.
    pub fn cmp_value(self, other: Self) -> Option<std::cmp::Ordering> {
        let scale = self.scale.max(other.scale);
        Some(self.rescale(scale)?.cmp(&other.rescale(scale)?))
    }

    pub fn checked_mul(self, other: Self) -> Option<Self> {
        Some(Self {
            mantissa: self.mantissa.checked_mul(other.mantissa)?,
            scale: self.scale + other.scale,
        })
    }

    /// Round toward zero to `decimals` places.
    pub fn floor(self, decimals: u32) -> Option<Self> {
        if self.scale <= decimals {
            return Some(self);
        }
        Some(Self {
            mantissa: self.mantissa / 10u128.checked_pow(self.scale - decimals)?,
            scale: decimals,
        })
    }

    pub fn is_zero(self) -> bool {
        self.mantissa == 0
    }
}

/// The executable lot of a holding under known venue precision and minimums; zero when it cannot be sold.
/// Mirrors gym/domain/sim.py `sellable_quantity`.
pub fn sellable(
    quantity: Exact,
    qty_decimals: Option<u32>,
    min_qty: Option<Exact>,
    min_notional: Option<Exact>,
    bid: Exact,
) -> Option<Exact> {
    use std::cmp::Ordering::Less;
    let lot = match qty_decimals {
        Some(d) => quantity.floor(d)?,
        None => quantity,
    };
    let zero = Exact {
        mantissa: 0,
        scale: 0,
    };
    if lot.is_zero() {
        return Some(zero);
    }
    if let Some(minimum) = min_qty {
        if lot.cmp_value(minimum)? == Less {
            return Some(zero);
        }
    }
    if let Some(minimum) = min_notional {
        if lot.checked_mul(bid)?.cmp_value(minimum)? == Less {
            return Some(zero);
        }
    }
    Some(lot)
}

impl Exact {
    pub fn checked_add(self, other: Self) -> Option<Self> {
        let scale = self.scale.max(other.scale);
        Some(Self {
            mantissa: self.rescale(scale)?.checked_add(other.rescale(scale)?)?,
            scale,
        })
    }

    pub fn checked_sub(self, other: Self) -> Option<Self> {
        let scale = self.scale.max(other.scale);
        Some(Self {
            mantissa: self.rescale(scale)?.checked_sub(other.rescale(scale)?)?,
            scale,
        })
    }
}

/// Quote notional of taking `quantity` best-first from `levels` (price, size); None when depth is short.
/// Mirrors gym/domain/sim.py `_walk`.
pub fn walk(levels: &[(Exact, Exact)], quantity: Exact) -> Option<Exact> {
    let (mut left, mut notional) = (
        quantity,
        Exact {
            mantissa: 0,
            scale: 0,
        },
    );
    for &(price, size) in levels {
        if left.is_zero() {
            break;
        }
        let take = if size.cmp_value(left)? == std::cmp::Ordering::Less {
            size
        } else {
            left
        };
        notional = notional.checked_add(take.checked_mul(price)?)?;
        left = left.checked_sub(take)?;
    }
    left.is_zero().then_some(notional)
}

/// A balance change: (amount, true when it is a decrease).
pub type Delta = (Exact, bool);

/// (fee, base delta, quote delta) of one fill with the fee in the received asset.
/// Mirrors gym/domain/sim.py `_settle`.
pub fn settle(
    buy: bool,
    quantity: Exact,
    notional: Exact,
    fee_rate: Exact,
) -> Option<(Exact, Delta, Delta)> {
    if buy {
        let fee = quantity.checked_mul(fee_rate)?;
        Some((fee, (quantity.checked_sub(fee)?, false), (notional, true)))
    } else {
        let fee = notional.checked_mul(fee_rate)?;
        Some((fee, (quantity, true), (notional.checked_sub(fee)?, false)))
    }
}
