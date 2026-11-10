//! Properties of the proposed ActiveHoldBook (ADR 0003), against a simulated venue.
use exec_core::holds::{ActiveHoldBook, HoldError};
use exec_core::orders::{
    Attempt, BalanceSnapshot, Event, ReservationBook, ReservationError, SettlementEvidence,
};

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

/// A venue: true balance, funds locked by open orders, and what an observation would show.
struct Venue {
    balance: u64,
    locked: Vec<(String, u64)>,
}
impl Venue {
    fn available(&self) -> u64 {
        self.balance - self.locked.iter().map(|(_, q)| q).sum::<u64>()
    }
}

#[test]
fn never_overspends_and_never_wedges_under_random_interleavings() {
    for seed in 0..300u64 {
        let mut rng = Rng(seed);
        let tolerance = rng.below(3);
        let mut venue = Venue {
            balance: 1_000 + rng.below(100_000),
            locked: vec![],
        };
        let mut book = ActiveHoldBook::default();
        book.set_tolerance("main", "USDT", tolerance).unwrap();
        let mut seq = 1;
        book.observe("main", "USDT", venue.available(), seq)
            .unwrap();
        let (mut open, mut next_id, mut admitted, mut refused) =
            (Vec::<(String, u64)>::new(), 0u64, 0, 0);
        for _ in 0..400 {
            match rng.below(6) {
                0 | 1 => {
                    // Admit an order whose maximum spend is q; the venue locks q when it is sent.
                    let q = 1 + rng.below(venue.balance / 4 + 1);
                    let id = format!("o{next_id}");
                    next_id += 1;
                    match book.reserve(&id, "main", "USDT", q) {
                        Ok(()) => {
                            admitted += 1;
                            assert!(
                                q <= venue.available(),
                                "seed {seed}: admitted more than the venue can lock"
                            );
                            venue.locked.push((id.clone(), q));
                            open.push((id, q));
                        }
                        Err(HoldError::InsufficientAvailable | HoldError::Reconciling) => {
                            refused += 1
                        }
                        Err(e) => panic!("seed {seed}: unexpected {e:?}"),
                    }
                }
                2 if !open.is_empty() => {
                    // Terminal: spend up to the hold, rarely a tolerated or untolerated overspend.
                    let (id, q) = open.remove(rng.below(open.len() as u64) as usize);
                    venue.locked.retain(|(i, _)| i != &id);
                    let spent = match rng.below(20) {
                        0 => q + tolerance,
                        1 => q + tolerance + 1,
                        _ => rng.below(q + 1),
                    }
                    .min(venue.balance);
                    venue.balance -= spent;
                    book.settle(&id, spent).unwrap();
                }
                3 if !open.is_empty() => {
                    let (id, _) = open.remove(rng.below(open.len() as u64) as usize);
                    venue.locked.retain(|(i, _)| i != &id);
                    book.release_unsent(&id).unwrap();
                }
                4 => venue.balance += rng.below(3), // dust credit or rebate from outside
                _ => {
                    seq += 1;
                    book.observe("main", "USDT", venue.available(), seq)
                        .unwrap();
                }
            }
        }
        // Drain: settle what is open, then one fresh observation leaves nothing held and nothing wedged.
        for (id, q) in open.drain(..) {
            venue.locked.retain(|(i, _)| i != &id);
            let spent = q.min(venue.balance);
            venue.balance -= spent;
            book.settle(&id, spent).unwrap();
        }
        seq += 1;
        book.observe("main", "USDT", venue.available(), seq)
            .unwrap();
        assert_eq!(
            book.active("main", "USDT"),
            0,
            "seed {seed}: holds or spends left after a fresh observation"
        );
        assert!(
            !book.reconciling("main", "USDT"),
            "seed {seed}: reconcile did not clear on a newer observation"
        );
        if venue.balance > 0 {
            book.reserve("final", "main", "USDT", venue.balance)
                .unwrap(); // the whole balance is usable again
        }
        assert!(admitted > 0, "seed {seed}: nothing was admitted");
        let _ = refused;
    }
}

#[test]
fn overlapping_orders_against_different_observations_are_admitted() {
    let mut book = ActiveHoldBook::default();
    book.observe("main", "USDT", 1000, 1).unwrap();
    book.reserve("a", "main", "USDT", 300).unwrap();
    book.observe("main", "USDT", 700, 2).unwrap(); // the venue now shows a's lock
                                                   // The old book refuses any new hold whose snapshot differs from a pending one; this model admits it.
    book.reserve("b", "main", "USDT", 300).unwrap();
    assert_eq!(
        book.reserve("c", "main", "USDT", 101),
        Err(HoldError::InsufficientAvailable)
    );
}

#[test]
fn untolerated_overspend_blocks_entries_until_a_newer_observation() {
    let mut book = ActiveHoldBook::default();
    book.set_tolerance("main", "USDT", 1).unwrap();
    book.observe("main", "USDT", 1000, 1).unwrap();
    book.reserve("a", "main", "USDT", 100).unwrap();
    book.settle("a", 101).unwrap(); // within tolerance
    assert!(!book.reconciling("main", "USDT"));
    book.reserve("b", "main", "USDT", 100).unwrap();
    book.settle("b", 150).unwrap(); // beyond tolerance
    assert_eq!(
        book.reserve("c", "main", "USDT", 1),
        Err(HoldError::Reconciling)
    );
    assert_eq!(
        book.observe("main", "USDT", 749, 1),
        Err(HoldError::StaleObservation)
    );
    book.observe("main", "USDT", 749, 2).unwrap();
    book.reserve("c", "main", "USDT", 749).unwrap();
}

/// Default book: exact, a dust credit keeps the hold. With a declared tolerance the credit releases; a shortfall
/// never does.
#[test]
fn reservation_book_tolerates_only_a_declared_dust_credit_and_never_a_shortfall() {
    let settled = || {
        let mut attempt = Attempt::new(100).unwrap();
        for event in [
            Event::BeginSend,
            Event::Acknowledged,
            Event::TerminalReported,
            Event::CumulativeFilled(100),
            Event::SettlementVerified,
        ] {
            attempt.apply(event).unwrap();
        }
        attempt
    };
    let reserve = |book: &mut ReservationBook| {
        book.reserve(
            "a",
            "main",
            "USDT",
            100,
            &BalanceSnapshot::new("main", "USDT", 1000, 1).unwrap(),
            &Attempt::new(100).unwrap(),
        )
        .unwrap();
    };
    // Spent 100 and the venue credited one quantum of dust: available 901.
    let credit = SettlementEvidence::new("main", "USDT", 2, true, 0, 100, 901).unwrap();
    let mut book = ReservationBook::default();
    reserve(&mut book);
    assert_eq!(
        book.release_settled("a", &settled(), &credit),
        Err(ReservationError::BalanceMismatch)
    );
    let mut book = ReservationBook::with_credit_tolerance(1);
    reserve(&mut book);
    book.release_settled("a", &settled(), &credit).unwrap();
    assert!(!book.is_reserved("a"));
    let two = SettlementEvidence::new("main", "USDT", 2, true, 0, 100, 902).unwrap();
    let mut book = ReservationBook::with_credit_tolerance(1);
    reserve(&mut book);
    assert_eq!(
        book.release_settled("a", &settled(), &two),
        Err(ReservationError::BalanceMismatch)
    );
    // Spent 100 but available is 899: money is missing, refused whatever the tolerance.
    let mut book = ReservationBook::with_credit_tolerance(5);
    reserve(&mut book);
    let short = SettlementEvidence::new("main", "USDT", 2, true, 0, 100, 899).unwrap();
    assert_eq!(
        book.release_settled("a", &settled(), &short),
        Err(ReservationError::BalanceMismatch)
    );
    assert!(book.is_reserved("a"));
}
