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
            || whole.trim_start_matches('0').len() + fraction.len() > 38
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

    /// Divide at an explicit output precision, rounding down; zero divisors and overflow are refused.
    pub fn div_floor(self, other: Self, decimals: u32) -> Option<Self> {
        if other.is_zero() || decimals > 38 {
            return None;
        }
        let exponent = i64::from(other.scale) + i64::from(decimals) - i64::from(self.scale);
        let (numerator, denominator) = if exponent >= 0 {
            (
                self.mantissa
                    .checked_mul(10u128.checked_pow(exponent.try_into().ok()?)?)?,
                other.mantissa,
            )
        } else {
            (
                self.mantissa,
                other
                    .mantissa
                    .checked_mul(10u128.checked_pow((-exponent).try_into().ok()?)?)?,
            )
        };
        Some(Self {
            mantissa: numerator / denominator,
            scale: decimals,
        })
    }

    /// Round toward zero to exactly `decimals` places (padding a shorter value), as Python's
    /// `Decimal.quantize(..., ROUND_DOWN)` does, so both print the same text.
    pub fn floor(self, decimals: u32) -> Option<Self> {
        if self.scale <= decimals {
            return Some(Self {
                mantissa: self.rescale(decimals)?,
                scale: decimals,
            });
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

fn valid_fraction(fraction: Exact) -> Option<()> {
    (fraction.cmp_value(Exact {
        mantissa: 1,
        scale: 0,
    })? != std::cmp::Ordering::Greater)
        .then_some(())
}

/// Known-precision entry quantity, bounded by cash fraction and observed depth.
/// Empty levels mean a single unrestricted quote at `price`.
pub fn cash_quantity(
    cash: Exact,
    fraction: Exact,
    price: Exact,
    levels: &[(Exact, Exact)],
    decimals: u32,
) -> Option<Exact> {
    valid_fraction(fraction)?;
    if decimals > 38 || price.is_zero() {
        return None;
    }
    let mut budget = cash.checked_mul(fraction)?;
    if levels.is_empty() {
        return budget.div_floor(price, decimals);
    }
    let mut quantity = Exact {
        mantissa: 0,
        scale: 0,
    };
    for &(price, size) in levels {
        if price.is_zero() {
            return None;
        }
        let notional = size.checked_mul(price)?;
        if notional.cmp_value(budget)? == std::cmp::Ordering::Greater {
            // Keep the fractional remainder of completed levels until the final lot flooring.
            let part = budget.div_floor(price, decimals.max(quantity.scale))?;
            return quantity.checked_add(part)?.floor(decimals);
        }
        quantity = quantity.checked_add(size)?;
        budget = budget.checked_sub(notional)?;
        if budget.is_zero() {
            break;
        }
    }
    quantity.floor(decimals)
}

/// Known-precision exit quantity, bounded by the actual holding fraction.
pub fn holdings_quantity(holdings: Exact, fraction: Exact, decimals: u32) -> Option<Exact> {
    valid_fraction(fraction)?;
    if decimals > 38 {
        return None;
    }
    holdings.checked_mul(fraction)?.floor(decimals)
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
        // Python's min(size, left) returns `size` on a tie; matching it keeps the decimal exponent identical.
        let take = if left.cmp_value(size)? == std::cmp::Ordering::Less {
            left
        } else {
            size
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
    if fee_rate.cmp_value(Exact {
        mantissa: 1,
        scale: 0,
    })? != std::cmp::Ordering::Less
    {
        return None;
    }
    if buy {
        let fee = quantity.checked_mul(fee_rate)?;
        Some((fee, (quantity.checked_sub(fee)?, false), (notional, true)))
    } else {
        let fee = notional.checked_mul(fee_rate)?;
        Some((fee, (quantity, true), (notional.checked_sub(fee)?, false)))
    }
}

/// Wallex cancels a market order that would move the price more than 2% from the best level.
/// Mirrors gym/domain/sim.py `_trips_price_guard`; exactly 2% does not trip.
pub fn trips_price_guard(levels: &[(Exact, Exact)], quantity: Exact) -> Option<bool> {
    let best = levels.first()?.0;
    let (mut taken, mut worst) = (
        Exact {
            mantissa: 0,
            scale: 0,
        },
        best,
    );
    for &(price, size) in levels {
        if taken.cmp_value(quantity)? != std::cmp::Ordering::Less {
            break;
        }
        taken = taken.checked_add(size)?;
        worst = price;
    }
    let distance = if worst.cmp_value(best)? == std::cmp::Ordering::Less {
        best.checked_sub(worst)?
    } else {
        worst.checked_sub(best)?
    };
    let fifty = Exact {
        mantissa: 50,
        scale: 0,
    };
    Some(distance.checked_mul(fifty)?.cmp_value(best)? == std::cmp::Ordering::Greater)
}

impl std::fmt::Display for Exact {
    /// Plain decimal text with exactly `scale` fraction digits, as Python's Decimal prints a quantized value.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let digits = self.mantissa.to_string();
        let scale = self.scale as usize;
        if scale == 0 {
            return f.write_str(&digits);
        }
        let padded = format!("{digits:0>width$}", width = scale + 1);
        let (whole, fraction) = padded.split_at(padded.len() - scale);
        write!(f, "{whole}.{fraction}")
    }
}
