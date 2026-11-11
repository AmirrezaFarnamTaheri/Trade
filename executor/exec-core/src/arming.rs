//! Arm records and kill rules (owner decision OD-2). Pure policy: it cannot arm anything by itself.
//!
//! The privileged arm path (not built; the service stays DISARMED) will call `approve` with the owner's policy
//! file and a preflight computed service-side, and then `check` / `admit_order` on every tick and order. Kill rules
//! are code, not something an operator watches: any breach returns `Verdict::Disarm`. Arming always expires.
//! The record digest binds the exact policy file (by SHA-256), the approver, the runtime epoch and the window, so
//! changing any limit changes the digest shown on the approval screen. Python computes the same digest from the
//! shared fixture `contracts/v1/fixtures/arm-record.json`.
use crate::kernel::Exact;
use sha2::{Digest, Sha256};
use std::cmp::Ordering;

const DAY_MS: u64 = 86_400_000;

/// The owner's policy, already parsed from `arm-policy.json`; `policy_sha256` is the hash of the file bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArmPolicy {
    pub policy_sha256: [u8; 32],
    pub venue: String,
    pub quote_asset: String,
    pub symbols: Vec<String>,
    pub loss_cap_quote: Exact,
    pub max_order_quote: Exact,
    pub max_orders_per_day: u32,
    pub kill_max_loss_quote: Exact,
    pub stale_data_seconds: u32,
    pub max_open_orders: u32,
    pub expires_days: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PolicyError {
    Venue,
    QuoteAsset,
    Symbols,
    LossCap,
    MaxOrder,
    OrdersPerDay,
    KillLoss,
    StaleData,
    OpenOrders,
    Expiry,
}

fn le(a: Exact, b: Exact) -> bool {
    a.cmp_value(b).is_some_and(|o| o != Ordering::Greater)
}

impl ArmPolicy {
    /// The same coherence rules as `gym.services.arm_preflight.validate_policy`.
    pub fn validate(&self) -> Result<(), PolicyError> {
        if self.venue != "wallex" {
            return Err(PolicyError::Venue);
        }
        if self.quote_asset != "USDT" && self.quote_asset != "TMN" {
            return Err(PolicyError::QuoteAsset);
        }
        let symbol_ok = |s: &String| {
            (2..=24).contains(&s.len())
                && s.bytes()
                    .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
                && s.ends_with(&self.quote_asset)
        };
        if !(1..=20).contains(&self.symbols.len()) || !self.symbols.iter().all(symbol_ok) {
            return Err(PolicyError::Symbols);
        }
        if self.loss_cap_quote.is_zero() {
            return Err(PolicyError::LossCap);
        }
        if self.max_order_quote.is_zero() || !le(self.max_order_quote, self.loss_cap_quote) {
            return Err(PolicyError::MaxOrder);
        }
        if !(1..=100).contains(&self.max_orders_per_day) {
            return Err(PolicyError::OrdersPerDay);
        }
        if self.kill_max_loss_quote.is_zero() || !le(self.kill_max_loss_quote, self.loss_cap_quote)
        {
            return Err(PolicyError::KillLoss);
        }
        if !(1..=300).contains(&self.stale_data_seconds) {
            return Err(PolicyError::StaleData);
        }
        if !(1..=10).contains(&self.max_open_orders) {
            return Err(PolicyError::OpenOrders);
        }
        if !(1..=30).contains(&self.expires_days) {
            return Err(PolicyError::Expiry);
        }
        Ok(())
    }
}

/// Preflight items the privileged path must establish itself before an approval can succeed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PreflightItem {
    ExecutorHealthy,
    StopGateResponsive,
    CredentialsPresent,
    FreshAccountObservation,
    ReconciliationClean,
    CollectorFeedFresh,
    RecentBackup,
    NoOpenIncident,
}

pub const PREFLIGHT_ITEMS: [PreflightItem; 8] = [
    PreflightItem::ExecutorHealthy,
    PreflightItem::StopGateResponsive,
    PreflightItem::CredentialsPresent,
    PreflightItem::FreshAccountObservation,
    PreflightItem::ReconciliationClean,
    PreflightItem::CollectorFeedFresh,
    PreflightItem::RecentBackup,
    PreflightItem::NoOpenIncident,
];

/// The items that passed; anything not listed counts as failed (fail closed).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Preflight {
    passed: Vec<PreflightItem>,
}

impl Preflight {
    pub fn passing(items: &[PreflightItem]) -> Self {
        Self {
            passed: items.to_vec(),
        }
    }
    pub fn failing(&self) -> Vec<PreflightItem> {
        PREFLIGHT_ITEMS
            .iter()
            .copied()
            .filter(|i| !self.passed.contains(i))
            .collect()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ArmRefusal {
    Policy(PolicyError),
    Blocked(Vec<PreflightItem>),
    Approver,
    Clock,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ArmRecord {
    pub policy: ArmPolicy,
    pub approver: String,
    pub runtime_epoch: u64,
    pub armed_at_ms: u64,
    pub expires_at_ms: u64,
}

/// One owner click on a READY state. Refused unless the policy is coherent and every preflight item passed.
pub fn approve(
    policy: ArmPolicy,
    preflight: &Preflight,
    approver: &str,
    runtime_epoch: u64,
    now_ms: u64,
) -> Result<ArmRecord, ArmRefusal> {
    policy.validate().map_err(ArmRefusal::Policy)?;
    let failing = preflight.failing();
    if !failing.is_empty() {
        return Err(ArmRefusal::Blocked(failing));
    }
    if approver.is_empty()
        || approver.len() > 64
        || !approver
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.@".contains(&b))
    {
        return Err(ArmRefusal::Approver);
    }
    let expires_at_ms = u64::from(policy.expires_days)
        .checked_mul(DAY_MS)
        .and_then(|d| now_ms.checked_add(d))
        .ok_or(ArmRefusal::Clock)?;
    Ok(ArmRecord {
        policy,
        approver: approver.to_string(),
        runtime_epoch,
        armed_at_ms: now_ms,
        expires_at_ms,
    })
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Live inputs the privileged path measures on every tick.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct KillInputs {
    pub now_ms: u64,
    pub runtime_epoch: u64,
    /// Realised plus marked loss since arming, in quote units (zero when flat or up).
    pub loss_quote: Exact,
    pub newest_data_age_ms: u64,
    pub open_orders: u32,
    pub orders_today: u32,
    pub reconciliation_clean: bool,
    pub privileged_fault: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KillReason {
    Expired,
    RuntimeRestarted,
    LossCap,
    KillLoss,
    StaleData,
    TooManyOpenOrders,
    ReconciliationMismatch,
    PrivilegedFault,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verdict {
    Armed,
    Disarm(KillReason),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OrderRefusal {
    Disarmed(KillReason),
    Symbol,
    MaxOrder,
    OrdersPerDay,
    OpenOrders,
}

impl ArmRecord {
    /// Canonical text whose SHA-256 is the arm-record digest.
    pub fn canonical(&self) -> String {
        format!(
            "TGARM1\npolicy_sha256={}\napprover={}\nruntime_epoch={}\narmed_at_ms={}\nexpires_at_ms={}\n",
            hex(&self.policy.policy_sha256),
            self.approver,
            self.runtime_epoch,
            self.armed_at_ms,
            self.expires_at_ms
        )
    }

    pub fn digest(&self) -> [u8; 32] {
        Sha256::digest(self.canonical().as_bytes()).into()
    }

    pub fn digest_hex(&self) -> String {
        hex(&self.digest())
    }

    /// Every tick: any breach disarms. A restart (new runtime epoch) always comes up disarmed.
    pub fn check(&self, inputs: &KillInputs) -> Verdict {
        let p = &self.policy;
        let reason = if inputs.privileged_fault {
            Some(KillReason::PrivilegedFault)
        } else if inputs.runtime_epoch != self.runtime_epoch {
            Some(KillReason::RuntimeRestarted)
        } else if inputs.now_ms >= self.expires_at_ms || inputs.now_ms < self.armed_at_ms {
            Some(KillReason::Expired)
        } else if !inputs.reconciliation_clean {
            Some(KillReason::ReconciliationMismatch)
        } else if le(p.loss_cap_quote, inputs.loss_quote) {
            Some(KillReason::LossCap)
        } else if le(p.kill_max_loss_quote, inputs.loss_quote) {
            Some(KillReason::KillLoss)
        } else if inputs.newest_data_age_ms > u64::from(p.stale_data_seconds) * 1000 {
            Some(KillReason::StaleData)
        } else if inputs.open_orders > p.max_open_orders {
            Some(KillReason::TooManyOpenOrders)
        } else {
            None
        };
        reason.map_or(Verdict::Armed, Verdict::Disarm)
    }

    /// Before each new order: the record must still be armed and the order inside every per-order limit.
    pub fn admit_order(
        &self,
        symbol: &str,
        notional_quote: Exact,
        inputs: &KillInputs,
    ) -> Result<(), OrderRefusal> {
        if let Verdict::Disarm(reason) = self.check(inputs) {
            return Err(OrderRefusal::Disarmed(reason));
        }
        let p = &self.policy;
        if !p.symbols.iter().any(|s| s == symbol) {
            return Err(OrderRefusal::Symbol);
        }
        if notional_quote.is_zero() || !le(notional_quote, p.max_order_quote) {
            return Err(OrderRefusal::MaxOrder);
        }
        if inputs.orders_today >= p.max_orders_per_day {
            return Err(OrderRefusal::OrdersPerDay);
        }
        if inputs.open_orders >= p.max_open_orders {
            return Err(OrderRefusal::OpenOrders);
        }
        Ok(())
    }
}
