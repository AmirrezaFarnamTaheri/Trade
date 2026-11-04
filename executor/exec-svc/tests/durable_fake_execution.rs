use exec_core::orders::Lifecycle;
use exec_ipc::{StopCommand, StopRequest};
use exec_svc::{
    fake_execution::{Dispatch, ExecutionError, FakeExecution, FakeMarket, FakeVenue},
    offline_recovery::{Purpose, Side},
    StopGate,
};
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{SystemTime, UNIX_EPOCH},
};
fn path() -> PathBuf {
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    std::env::temp_dir().join(format!(
        "tg-execution-{}-{}-{}.db",
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ))
}
fn market(base: &str, now: u64) -> FakeMarket {
    FakeMarket {
        base: base.into(),
        quote: "USDT".into(),
        price: 10,
        observed_at_ms: now,
        open: true,
        rules_version: "rules-1".into(),
        method: "limit".into(),
        certified_until_ms: 10_000,
    }
}
fn venue() -> FakeVenue {
    let mut venue = FakeVenue::default();
    venue.set_market(market("BTC", 100));
    venue.set_market(market("ETH", 100));
    for (asset, value) in [("USDT", 1000), ("BTC", 0), ("ETH", 20)] {
        venue.set_balance("main", asset, value, 1);
    }
    venue
}
fn stop(gate: &StopGate, command: StopCommand) {
    gate.process(StopRequest {
        runtime_epoch: gate.runtime_epoch(),
        correlation: [1; 16],
        command,
    });
}
#[test]
fn lost_ack_restart_partial_received_asset_fee_and_reconciled_exit() {
    let path = path();
    let gate = Arc::new(StopGate::new(1).unwrap());
    let mut venue = venue();
    {
        let mut service = FakeExecution::open(&path, gate.clone()).unwrap();
        let approval = service
            .approve(
                &venue,
                "conversion",
                "main",
                "BTCUSDT",
                10,
                Purpose::Conversion,
                Side::Buy,
                110,
                1000,
                100,
            )
            .unwrap();
        service
            .submit(&mut venue, approval, 100, Dispatch::LoseAcknowledgement)
            .unwrap();
        assert_eq!(service.lifecycle("conversion"), Some(Lifecycle::Unknown));
        assert_eq!(service.journal().reserved("main", "USDT"), 110);
    }
    let mut service = FakeExecution::open(&path, gate.clone()).unwrap();
    assert_eq!(
        service.retry(&mut venue, "conversion", 101, Dispatch::Acknowledge),
        Err(ExecutionError::RetryForbidden)
    );
    assert_eq!(venue.order_count(), 1);
    venue.fill("conversion", 7, "BTC", 1, false).unwrap();
    service.cancel(&mut venue, "conversion").unwrap();
    service.reconcile(&mut venue, "conversion").unwrap();
    service.reconcile(&mut venue, "conversion").unwrap();
    assert_eq!(service.lifecycle("conversion"), Some(Lifecycle::Closed));
    assert_eq!(service.journal().reserved("main", "USDT"), 0);
    assert_eq!(venue.balance("main", "BTC").unwrap().0, 6);
    let saved = service.journal().get("conversion").unwrap();
    assert_eq!(saved.execution.as_ref().unwrap().instrument, "BTCUSDT");
    assert_eq!(
        saved.execution_settlement.as_ref().unwrap().fee_asset,
        "BTC"
    );
    stop(&gate, StopCommand::PauseEntries);
    let exit = service
        .approve(
            &venue,
            "exit",
            "main",
            "BTCUSDT",
            6,
            Purpose::ProtectiveExit,
            Side::Sell,
            60,
            1000,
            101,
        )
        .unwrap();
    service
        .submit(&mut venue, exit, 101, Dispatch::Acknowledge)
        .unwrap();
    venue.fill("exit", 6, "USDT", 1, true).unwrap();
    service.reconcile(&mut venue, "exit").unwrap();
    assert_eq!(venue.balance("main", "BTC").unwrap().0, 0);
    assert_eq!(venue.balance("main", "USDT").unwrap().0, 989);
    drop(service);
    let recovered = FakeExecution::open(&path, Arc::new(StopGate::new(2).unwrap())).unwrap();
    assert_eq!(recovered.lifecycle("exit"), Some(Lifecycle::Closed));
    assert_eq!(
        recovered
            .journal()
            .get("conversion")
            .unwrap()
            .execution_settlement
            .as_ref()
            .unwrap()
            .filled_quanta,
        7
    );
}
#[test]
fn approval_is_rechecked_for_price_rules_expiry_closure_and_stop() {
    for mutation in 0..5 {
        let path = path();
        let gate = Arc::new(StopGate::new(7).unwrap());
        let mut venue = venue();
        let mut service = FakeExecution::open(&path, gate.clone()).unwrap();
        let approval = service
            .approve(
                &venue,
                "intent",
                "main",
                "BTCUSDT",
                10,
                Purpose::Entry,
                Side::Buy,
                110,
                1000,
                100,
            )
            .unwrap();
        let mut changed = market("BTC", 100);
        let expected = match mutation {
            0 => {
                changed.price = 11;
                ExecutionError::OutsideEnvelope
            }
            1 => {
                changed.rules_version = "rules-2".into();
                ExecutionError::RulesChanged
            }
            2 => {
                changed.open = false;
                ExecutionError::Closed
            }
            3 => ExecutionError::Expired,
            _ => {
                stop(&gate, StopCommand::Halt);
                ExecutionError::Stopped
            }
        };
        venue.set_market(changed);
        assert_eq!(
            service.submit(
                &mut venue,
                approval,
                if mutation == 3 { 1000 } else { 100 },
                Dispatch::Acknowledge
            ),
            Err(expected)
        );
        assert_eq!(venue.post_count(), 0);
        assert_eq!(service.journal().record_count(), 0);
    }
}
#[test]
fn before_byte_retry_preserves_identity_but_unknown_never_retries() {
    let path = path();
    let gate = Arc::new(StopGate::new(1).unwrap());
    let mut venue = venue();
    let mut service = FakeExecution::open(&path, gate).unwrap();
    let approval = service
        .approve(
            &venue,
            "entry",
            "main",
            "BTCUSDT",
            10,
            Purpose::Entry,
            Side::Buy,
            110,
            1000,
            100,
        )
        .unwrap();
    service
        .submit(&mut venue, approval, 100, Dispatch::BeforeFirstByte)
        .unwrap();
    assert_eq!(venue.post_count(), 0);
    service
        .retry(&mut venue, "entry", 101, Dispatch::LoseAcknowledgement)
        .unwrap();
    assert_eq!(
        service.retry(&mut venue, "entry", 102, Dispatch::Acknowledge),
        Err(ExecutionError::RetryForbidden)
    );
    assert_eq!(venue.post_count(), 1);
    assert_eq!(service.journal().reserved("main", "USDT"), 110);
}
#[test]
fn unknown_entry_blocks_entries_but_not_other_instrument_verified_exit() {
    let path = path();
    let gate = Arc::new(StopGate::new(1).unwrap());
    let mut venue = venue();
    let mut service = FakeExecution::open(&path, gate.clone()).unwrap();
    let entry = service
        .approve(
            &venue,
            "btc-entry",
            "main",
            "BTCUSDT",
            10,
            Purpose::Entry,
            Side::Buy,
            110,
            1000,
            100,
        )
        .unwrap();
    service
        .submit(&mut venue, entry, 100, Dispatch::LoseAcknowledgement)
        .unwrap();
    assert!(matches!(
        service.approve(
            &venue,
            "entry-2",
            "main",
            "ETHUSDT",
            1,
            Purpose::Entry,
            Side::Buy,
            20,
            1000,
            101
        ),
        Err(ExecutionError::Conflict)
    ));
    stop(&gate, StopCommand::ExitOnly);
    let exit = service
        .approve(
            &venue,
            "eth-exit",
            "main",
            "ETHUSDT",
            5,
            Purpose::ProtectiveExit,
            Side::Sell,
            50,
            1000,
            101,
        )
        .unwrap();
    service
        .submit(&mut venue, exit, 101, Dispatch::Acknowledge)
        .unwrap();
    assert_eq!(venue.post_count(), 2);
    stop(&gate, StopCommand::Halt);
    assert_eq!(
        service.cancel(&mut venue, "eth-exit"),
        Err(ExecutionError::Stopped)
    );
    venue.fill("eth-exit", 5, "USDT", 0, true).unwrap();
    service.reconcile(&mut venue, "eth-exit").unwrap();
    assert_eq!(service.journal().reserved("main", "USDT"), 110);
}

#[test]
fn zero_fill_cancel_releases_only_after_a_fresh_terminal_balance() {
    let path = path();
    let gate = Arc::new(StopGate::new(1).unwrap());
    let mut venue = venue();
    let mut service = FakeExecution::open(&path, gate.clone()).unwrap();
    let entry = service
        .approve(
            &venue,
            "unfilled",
            "main",
            "BTCUSDT",
            10,
            Purpose::Entry,
            Side::Buy,
            110,
            1000,
            100,
        )
        .unwrap();
    service
        .submit(&mut venue, entry, 100, Dispatch::Acknowledge)
        .unwrap();
    service.cancel(&mut venue, "unfilled").unwrap();
    assert_eq!(service.journal().reserved("main", "USDT"), 110);
    drop(service);
    let mut service = FakeExecution::open(&path, gate).unwrap();
    service.reconcile(&mut venue, "unfilled").unwrap();
    assert_eq!(service.lifecycle("unfilled"), Some(Lifecycle::Closed));
    assert_eq!(service.journal().reserved("main", "USDT"), 0);
    assert_eq!(venue.balance("main", "USDT").unwrap().0, 1000);
    assert!(venue.balance("main", "USDT").unwrap().1 > 1);
}
#[test]
fn concurrent_exit_credits_are_order_specific_durable_and_idempotent() {
    for exit_quantity in [5, 15] {
        for entry_fills_first in [true, false] {
            let path = path();
            let gate = Arc::new(StopGate::new(1).unwrap());
            let mut venue = venue();
            let mut service = FakeExecution::open(&path, gate.clone()).unwrap();
            let entry = service
                .approve(
                    &venue,
                    "buy-btc",
                    "main",
                    "BTCUSDT",
                    10,
                    Purpose::Entry,
                    Side::Buy,
                    110,
                    1000,
                    100,
                )
                .unwrap();
            service
                .submit(&mut venue, entry, 100, Dispatch::LoseAcknowledgement)
                .unwrap();
            let exit = service
                .approve(
                    &venue,
                    "sell-eth",
                    "main",
                    "ETHUSDT",
                    exit_quantity,
                    Purpose::ProtectiveExit,
                    Side::Sell,
                    200,
                    1000,
                    101,
                )
                .unwrap();
            service
                .submit(&mut venue, exit, 101, Dispatch::Acknowledge)
                .unwrap();
            if entry_fills_first {
                venue.fill("buy-btc", 10, "BTC", 1, true).unwrap();
            }
            venue
                .fill("sell-eth", exit_quantity, "USDT", 1, true)
                .unwrap();
            if !entry_fills_first {
                venue.fill("buy-btc", 10, "BTC", 1, true).unwrap();
            }
            service.reconcile(&mut venue, "sell-eth").unwrap();
            drop(service);
            let mut service = FakeExecution::open(&path, gate).unwrap();
            service.reconcile(&mut venue, "buy-btc").unwrap();
            assert_eq!(service.lifecycle("buy-btc"), Some(Lifecycle::Closed));
            assert_eq!(service.journal().reserved("main", "USDT"), 0);
            assert_eq!(
                venue.balance("main", "USDT").unwrap().0,
                900 + exit_quantity * 10 - 1
            );
            assert_eq!(
                service
                    .journal()
                    .get("buy-btc")
                    .unwrap()
                    .execution_settlement
                    .as_ref()
                    .unwrap()
                    .balance
                    .spent_quanta,
                100
            );
            let later = service
                .approve(
                    &venue,
                    "later-exit",
                    "main",
                    "ETHUSDT",
                    1,
                    Purpose::ProtectiveExit,
                    Side::Sell,
                    10,
                    1000,
                    102,
                )
                .unwrap();
            service
                .submit(&mut venue, later, 102, Dispatch::Acknowledge)
                .unwrap();
            venue.fill("later-exit", 1, "USDT", 0, true).unwrap();
            service.reconcile(&mut venue, "later-exit").unwrap();
            let records = service.journal().record_count();
            service.reconcile(&mut venue, "buy-btc").unwrap();
            assert_eq!(service.journal().record_count(), records);
            drop(service);
            assert_eq!(
                FakeExecution::open(&path, Arc::new(StopGate::new(2).unwrap()))
                    .unwrap()
                    .lifecycle("buy-btc"),
                Some(Lifecycle::Closed)
            );
        }
    }
}
#[test]
fn unexplained_credit_does_not_release_an_unknown_entry() {
    let path = path();
    let gate = Arc::new(StopGate::new(1).unwrap());
    let mut venue = venue();
    let mut service = FakeExecution::open(&path, gate).unwrap();
    let entry = service
        .approve(
            &venue,
            "unknown",
            "main",
            "BTCUSDT",
            10,
            Purpose::Entry,
            Side::Buy,
            110,
            1000,
            100,
        )
        .unwrap();
    service
        .submit(&mut venue, entry, 100, Dispatch::LoseAcknowledgement)
        .unwrap();
    venue.fill("unknown", 10, "BTC", 1, true).unwrap();
    venue.set_balance("main", "USDT", 901, 3);
    assert!(service.reconcile(&mut venue, "unknown").is_err());
    assert_eq!(service.lifecycle("unknown"), Some(Lifecycle::Unknown));
    assert_eq!(service.journal().reserved("main", "USDT"), 110);
}
