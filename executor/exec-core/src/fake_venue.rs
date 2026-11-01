//! Seeded, deterministic Fake Venue for the B2 chaos suite (spec 14.1/14.3).
//! Pure: no I/O, clock, keys or real orders. The venue holds ground truth;
//! the client side sees only lossy, duplicated, reordered observations and
//! drives the real `orders` state machine and `ReservationBook`.
use crate::orders::{
    Attempt, BalanceSnapshot, EconomicEffect, Event, FailureStage, Lifecycle, OrderError,
    ReservationBook, Settlement, SettlementEvidence,
};

pub const FIXTURES: &[&str] = &[
    "lost_ack_then_settled_fill",
    "lost_ack_unresolved",
    "connect_refused_then_resend",
    "reset_after_write_no_resend",
    "duplicate_out_of_order_status",
    "ignored_filter_paginated_list",
    "malformed_response",
    "cancel_fill_race",
    "canceled_with_partial_fill",
    "delayed_unblock_expected",
    "delayed_unblock_expired",
    "unknown_new_status",
];

const REQUESTED: u64 = 10_000;
const INITIAL_QUOTE: u64 = 50_000;
const MAX_BALANCE_READS: u64 = 6;

struct Rng(u64);
impl Rng {
    fn new(seed: u64) -> Self { Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1) }
    fn below(&mut self, n: u64) -> u64 {
        let mut x = self.0;
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        self.0 = x;
        x % n
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outcome {
    pub fixture: &'static str,
    pub seed: u64,
    /// POSTs whose bytes reached the venue (funded in a live system).
    pub funded_post_count: u32,
    /// Orders the venue actually created; must never exceed one.
    pub venue_orders: u32,
    pub venue_filled: u64,
    pub recognized_filled: u64,
    pub lifecycle: Lifecycle,
    pub effect: EconomicEffect,
    pub settlement: Settlement,
    pub reservation_released: bool,
    pub frozen: bool,
    pub incident: Option<&'static str>,
    pub trace: Vec<String>,
    pub violations: Vec<String>,
}

struct Client {
    attempt: Attempt,
    trace: Vec<String>,
    violations: Vec<String>,
    incident: Option<&'static str>,
}

impl Client {
    fn step(&mut self, event: Event) {
        match self.attempt.apply(event) {
            Ok(()) => self.trace.push(format!("{event:?}")),
            // Copy-then-commit: rejected updates leave state untouched.
            Err(OrderError::FillRegression) => self.trace.push("STALE_FILL_IGNORED".into()),
            Err(OrderError::IllegalTransition) => self.trace.push(format!("DUPLICATE_IGNORED {event:?}")),
            Err(e) => self.violations.push(format!("unexpected {e:?} on {event:?}")),
        }
    }
    /// Map one by-ID order-detail observation. Unknown raw statuses never
    /// become a transition; they raise an incident instead.
    fn observe(&mut self, status: &str, cumulative: u64) {
        let terminal = match status {
            "NEW" => false,
            "FILLED" | "CANCELED" => true,
            _ => {
                self.incident = Some("UNKNOWN_VENUE_STATUS");
                self.trace.push(format!("UNMAPPED_STATUS {status}"));
                return;
            }
        };
        if matches!(self.attempt.lifecycle(), Lifecycle::Submitting | Lifecycle::Unknown) {
            self.step(Event::Acknowledged);
        }
        if !terminal && self.attempt.lifecycle() == Lifecycle::Acknowledged {
            self.step(Event::Working);
        }
        self.step(Event::CumulativeFilled(cumulative));
        if terminal { self.step(Event::TerminalReported); }
    }
}

pub fn run(fixture: &'static str, seed: u64) -> Outcome {
    let mut rng = Rng::new(seed);
    let mut c = Client {
        attempt: Attempt::new(REQUESTED).expect("nonzero"),
        trace: Vec::new(), violations: Vec::new(), incident: None,
    };
    let mut book = ReservationBook::default();
    let snapshot = BalanceSnapshot::new("main", "TMN", INITIAL_QUOTE, 1).expect("valid");
    // Durable intent + reservation strictly before any send.
    if book.reserve("intent-1", "main", "TMN", REQUESTED, &snapshot, &c.attempt).is_err() {
        c.violations.push("reservation refused".into());
    }
    c.trace.push("INTENT_DURABLE".into());

    // Venue ground truth.
    let (mut posts, mut orders) = (0u32, 0u32);
    let mut fills: Vec<u64> = Vec::new();
    let mut final_status = "FILLED";
    let mut lookups_fail = false;

    // --- Send phase ---
    c.step(Event::BeginSend);
    match fixture {
        "connect_refused_then_resend" => {
            c.step(Event::TransportFailed(FailureStage::BeforeFirstByte));
            if !c.attempt.can_retry_same_identity() {
                c.violations.push("pre-byte failure lost its single same-ID retry".into());
            }
            c.step(Event::BeginSend);
            posts += 1; orders += 1;
            c.step(Event::Acknowledged);
        }
        "lost_ack_then_settled_fill" | "lost_ack_unresolved" => {
            posts += 1; orders += 1;
            c.step(Event::TransportFailed(FailureStage::AfterFirstByte));
            lookups_fail = fixture == "lost_ack_unresolved";
        }
        "reset_after_write_no_resend" => {
            posts += 1;
            // The seed decides whether the venue accepted; the client must
            // behave the same either way until evidence arrives.
            if rng.below(2) == 0 { orders += 1; } else { lookups_fail = true; }
            c.step(Event::TransportFailed(FailureStage::AfterFirstByte));
        }
        _ => {
            posts += 1; orders += 1;
            c.step(Event::Acknowledged);
        }
    }
    if posts > 0 && c.attempt.lifecycle() == Lifecycle::Unknown {
        match c.attempt.apply(Event::BeginSend) {
            Err(OrderError::RetryForbidden) => c.trace.push("RESEND_REFUSED".into()),
            other => c.violations.push(format!("resend after first byte not refused: {other:?}")),
        }
    }

    // --- Venue progression ---
    if orders == 1 {
        match fixture {
            "duplicate_out_of_order_status" => fills = vec![3_000, 7_000, REQUESTED],
            "canceled_with_partial_fill" => { fills = vec![4_000]; final_status = "CANCELED"; }
            "cancel_fill_race" => {
                c.trace.push("CANCEL_REQUESTED".into());
                match rng.below(3) {
                    0 => fills = vec![REQUESTED],
                    1 => { fills = vec![1 + rng.below(REQUESTED - 1)]; final_status = "CANCELED"; }
                    _ => { fills = vec![0]; final_status = "CANCELED"; }
                }
            }
            "unknown_new_status" => { fills = vec![2_500]; final_status = "EXPIRED_IN_MATCH"; }
            _ => fills = vec![REQUESTED],
        }
    }
    let venue_filled = fills.last().copied().unwrap_or(0);

    // --- Observation phase (seeded loss, duplication and reordering) ---
    if fixture == "ignored_filter_paginated_list" {
        for _ in 0..1 + rng.below(5) { c.step(Event::MissingFromList); }
    }
    if fixture == "malformed_response" {
        for _ in 0..1 + rng.below(3) { c.trace.push("READ_UNCERTAIN malformed body".into()); }
    }
    if lookups_fail {
        for _ in 0..3 + rng.below(4) {
            c.trace.push("READ_UNCERTAIN not found by ID (not absence proof)".into());
            c.step(Event::MissingFromList);
        }
    } else if orders == 1 {
        let mut updates: Vec<(&str, u64)> = fills.iter().map(|&q| ("NEW", q)).collect();
        updates.push((final_status, venue_filled));
        for _ in 0..rng.below(3) {
            let pick = updates[rng.below(updates.len() as u64) as usize];
            updates.push(pick);
        }
        for i in (1..updates.len()).rev() {
            updates.swap(i, rng.below(i as u64 + 1) as usize);
        }
        for (status, q) in updates { c.observe(status, q); }
        // Authoritative by-ID re-read: cumulative truth wins over any reordering.
        c.observe(final_status, venue_filled);
    }

    // --- Settlement phase ---
    let mut released = false;
    let lock_reads = match fixture {
        "delayed_unblock_expected" => 1 + rng.below(MAX_BALANCE_READS - 2),
        "delayed_unblock_expired" => u64::MAX,
        _ => 0,
    };
    if c.attempt.lifecycle() == Lifecycle::TerminalReported && c.incident.is_none() {
        let spent = venue_filled;
        for read in 0..MAX_BALANCE_READS {
            let locked = if read < lock_reads { (REQUESTED - spent).max(1) } else { 0 };
            let available = INITIAL_QUOTE - spent - locked;
            // Reconcile spent against what the state machine recognized.
            if spent != c.attempt.filled_quanta() {
                c.violations.push("balance spend differs from recognized fills".into());
                break;
            }
            if locked != 0 { c.trace.push(format!("BALANCE_LOCKED {locked}")); continue; }
            c.step(Event::SettlementVerified);
            let ev = SettlementEvidence::new("main", "TMN", read + 2, true, locked, spent, available)
                .expect("valid");
            match book.release_settled("intent-1", &c.attempt, &ev) {
                Ok(()) => { released = true; c.trace.push("RESERVATION_RELEASED".into()); }
                Err(e) => c.violations.push(format!("release failed {e:?}")),
            }
            if available + spent != INITIAL_QUOTE {
                c.violations.push("per-currency conservation broken".into());
            }
            break;
        }
        if !released && c.violations.is_empty() { c.incident = Some("BLOCKED_BALANCE_NOT_RELEASED"); }
    }
    let frozen = !released;
    if frozen && c.incident.is_none() { c.incident = Some("UNRESOLVED_ORDER"); }
    if frozen { c.trace.push(format!("ASSET_FROZEN {}", c.incident.unwrap_or(""))); }

    // --- Invariants ---
    let a = c.attempt;
    let mut v = c.violations;
    if orders > 1 || posts > 1 { v.push("duplicate venue order".into()); }
    if a.filled_quanta() > venue_filled { v.push("recognized more than venue filled".into()); }
    if c.trace.first().map(String::as_str) != Some("INTENT_DURABLE") { v.push("send before durable intent".into()); }
    if released && (a.filled_quanta() != venue_filled || a.lifecycle() != Lifecycle::Closed) {
        v.push("settled without matching venue truth".into());
    }
    if frozen && (!a.holds_slot() || book.reserved("main", "TMN") != REQUESTED) {
        v.push("unresolved order lost its slot or reservation".into());
    }
    Outcome {
        fixture, seed, funded_post_count: posts, venue_orders: orders, venue_filled,
        recognized_filled: a.filled_quanta(), lifecycle: a.lifecycle(), effect: a.effect(),
        settlement: a.settlement(), reservation_released: released, frozen,
        incident: c.incident, trace: c.trace, violations: v,
    }
}
