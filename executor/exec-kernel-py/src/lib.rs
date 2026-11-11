//! The exec-core reference money rules, callable from the Python simulator (ADR 0005 stage 3).
//! Values cross the boundary as plain decimal strings, never floats.
use exec_core::kernel::{self, Exact};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

fn exact(text: &str) -> PyResult<Exact> {
    Exact::parse(text)
        .ok_or_else(|| PyValueError::new_err(format!("not a plain non-negative decimal: {text:?}")))
}

fn overflow() -> PyErr {
    PyValueError::new_err("exact arithmetic overflow")
}

fn levels(raw: Vec<(String, String)>) -> PyResult<Vec<(Exact, Exact)>> {
    raw.iter()
        .map(|(p, s)| Ok((exact(p)?, exact(s)?)))
        .collect()
}

/// Sellable lot of a holding under venue precision and minimums ("0" when it cannot be sold).
#[pyfunction]
#[pyo3(signature = (quantity, qty_decimals, min_qty, min_notional, bid))]
fn sellable(
    quantity: &str,
    qty_decimals: Option<u32>,
    min_qty: Option<&str>,
    min_notional: Option<&str>,
    bid: &str,
) -> PyResult<String> {
    kernel::sellable(
        exact(quantity)?,
        qty_decimals,
        min_qty.map(exact).transpose()?,
        min_notional.map(exact).transpose()?,
        exact(bid)?,
    )
    .map(|v| v.to_string())
    .ok_or_else(overflow)
}

/// Quote notional of taking `quantity` best-first from (price, size) levels; None when depth is short.
#[pyfunction]
fn walk(levels_: Vec<(String, String)>, quantity: &str) -> PyResult<Option<String>> {
    Ok(kernel::walk(&levels(levels_)?, exact(quantity)?).map(|v| v.to_string()))
}

/// True when the walk would move the price more than 2% from the best level.
#[pyfunction]
fn trips_price_guard(levels_: Vec<(String, String)>, quantity: &str) -> PyResult<bool> {
    kernel::trips_price_guard(&levels(levels_)?, exact(quantity)?).ok_or_else(overflow)
}

#[pyfunction]
fn cash_quantity(
    cash: &str,
    fraction: &str,
    price: &str,
    levels_: Vec<(String, String)>,
    qty_decimals: u32,
) -> PyResult<String> {
    kernel::cash_quantity(
        exact(cash)?,
        exact(fraction)?,
        exact(price)?,
        &levels(levels_)?,
        qty_decimals,
    )
    .map(|v| v.to_string())
    .ok_or_else(overflow)
}

#[pyfunction]
fn holdings_quantity(holdings: &str, fraction: &str, qty_decimals: u32) -> PyResult<String> {
    kernel::holdings_quantity(exact(holdings)?, exact(fraction)?, qty_decimals)
        .map(|v| v.to_string())
        .ok_or_else(overflow)
}

#[pyfunction]
fn settle(
    buy: bool,
    quantity: &str,
    notional: &str,
    fee_rate: &str,
) -> PyResult<(String, String, String)> {
    let (fee, base, quote) =
        kernel::settle(buy, exact(quantity)?, exact(notional)?, exact(fee_rate)?)
            .ok_or_else(overflow)?;
    let signed = |(value, negative): kernel::Delta| {
        if negative {
            format!("-{value}")
        } else {
            value.to_string()
        }
    };
    Ok((fee.to_string(), signed(base), signed(quote)))
}

#[pymodule]
fn exec_kernel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sellable, m)?)?;
    m.add_function(wrap_pyfunction!(walk, m)?)?;
    m.add_function(wrap_pyfunction!(trips_price_guard, m)?)?;
    m.add_function(wrap_pyfunction!(cash_quantity, m)?)?;
    m.add_function(wrap_pyfunction!(holdings_quantity, m)?)?;
    m.add_function(wrap_pyfunction!(settle, m)?)?;
    Ok(())
}
