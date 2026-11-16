//! Synthetic native sources exercise the real durable admission, without venue effects.
use exec_core::{
    available::Available,
    kernel::Exact,
    orders::{Event, FailureStage},
};
use exec_ipc::{ceiling::Ceiling, review::Ticket, StopMode};
use exec_svc::{
    account_observation::{AccountKind, AccountObservation},
    arm_control::{ArmController, ArmEvidence, PolicyFile},
    balance_receipts::BalanceReceipts,
    native_admission::{self, AdmittedOrder, NativeInputs},
    native_market::MarketObservation,
    offline_recovery::*,
    StopGate,
};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

const POLICY:&[u8]=br#"{"schema":1,"venue":"wallex","quote_asset":"USDT","symbols":["BTCUSDT"],"loss_cap_quote":"50","max_order_quote":"10","max_orders_per_day":10,"kill":{"max_loss_quote":"20","stale_data_seconds":120,"max_open_orders":2},"expires_days":7}"#;
const AT: u64 = 2_003;
struct Fixture {
    ledger: DurableOrderJournal,
    _credentials: DurableOrderJournal,
    balances: BalanceReceipts,
    controller: ArmController,
    gate: StopGate,
    arm: ArmEvidence,
    fees: AccountObservation,
    market: MarketObservation,
    inventory: BTreeMap<String, Exact>,
    root: tempfile::TempDir,
}
impl Fixture {
    fn new(buy: bool) -> Self {
        let root = tempfile::tempdir().unwrap();
        let mut ledger = DurableOrderJournal::open(root.path().join("execution.sqlite")).unwrap();
        let mut credentials =
            DurableOrderJournal::open(root.path().join("credentials.sqlite")).unwrap();
        credentials
            .commit_credential(CredentialMetadata {
                generation: [3; 16],
                ciphertext_digest: [4; 32],
                permission: CredentialPermission::Unverified,
            })
            .unwrap();
        let mut balances = BalanceReceipts::default();
        for (id, start) in [(10, 1100), (11, 1120)] {
            let read = balances.begin([3; 16], 10, [id; 16], start).unwrap();
            let observation=AccountObservation::from_response(AccountKind::Balances,
                br#"{"success":true,"result":{"balances":{"USDT":{"value":"20","locked":"0"},"BTC":{"value":"1","locked":"0"}}}}"#,
                [3;16],10,[id;16],start,start+10).unwrap();
            balances
                .complete(read, observation, &mut credentials, Some(&mut ledger))
                .unwrap();
        }
        ledger
            .commit_ceiling(CeilingChange {
                ceiling: Ceiling::from_amount("USDT", 1, 6, "50").unwrap(),
                principal: "S-1-5-21-100-1001".into(),
                operator_user: "S-1-5-21-100-1000".into(),
                logon: "S-1-5-5-100-200".into(),
                recorded_at_ms: 1000,
                request_id: [1; 16],
                expected_sequence: 0,
            })
            .unwrap();
        let ticket = Ticket {
            client_id: "intent_1".into(),
            account: "main".into(),
            base: "BTC".into(),
            quote: "USDT".into(),
            buy,
            base_decimals: 8,
            price_decimals: 2,
            quote_decimals: 6,
            base_epoch: 1,
            quote_epoch: 1,
            runtime_epoch: 10,
            ceiling_sequence: ledger.installation_ceiling().unwrap().0,
            expires_at_ms: 20000,
            quantity_quanta: 10000,
            worst_price_quanta: 8000000,
            max_quote_debit: if buy { 8010000 } else { 0 },
            min_quote_credit: if buy { 0 } else { 7990000 },
            preview_hash: [1; 32],
            rules_hash: [2; 32],
            credential_generation: [3; 16],
        };
        ledger
            .record_approval(OperatorApproval {
                ticket,
                principal: "S-1-5-21-100-1000".into(),
                logon: "S-1-5-5-100-200".into(),
                recorded_at_ms: 2000,
                request_id: [2; 16],
                mode: StopMode::Disarmed,
            })
            .unwrap();
        let prepare = IntentPreparation {
            client_id: "intent_1".into(),
            expected_sequence: ledger.operator_approval("intent_1").unwrap().sequence,
            principal: "S-1-5-21-100-1000".into(),
            logon: "S-1-5-5-100-200".into(),
            runtime_epoch: 10,
            credential_generation: [3; 16],
            recorded_at_ms: 2001,
            request_id: [3; 16],
            mode: StopMode::Disarmed,
        };
        ledger.prepare_intent(prepare).unwrap();
        let gate = StopGate::new(10).unwrap();
        let arm = ArmEvidence {
            measured_at_ms: AT,
            runtime_epoch: 10,
            credential_generation: Some([3; 16]),
            available: Some(Available {
                available_quanta: 20000000,
                receipt_seq: 2,
                age_ms: 0,
            }),
            market_received_at_ms: Some(AT),
            loss_quote: Exact::parse("0"),
            open_orders: Some(0),
            orders_today: Some(0),
            reconciliation_clean: true,
            privileged_fault: false,
            blockers: vec![],
        };
        std::fs::write(root.path().join("arm-policy.json"), POLICY).unwrap();
        let mut controller = ArmController::new();
        controller
            .approve(
                &gate,
                gate.approval_snapshot().unwrap(),
                PolicyFile::open(
                    &root.path().join("arm-policy.json"),
                    Sha256::digest(POLICY).into(),
                )
                .unwrap(),
                &arm,
                "owner",
                AT,
            )
            .unwrap();
        let fees=AccountObservation::from_response(AccountKind::Fees,
            br#"{"success":true,"result":{"BTCUSDT":{"makerFeeRate":"0.001","takerFeeRate":"0.001"}}}"#,[3;16],10,[12;16],1900,1910).unwrap();
        let market=MarketObservation::from_response("BTCUSDT",
            br#"{"success":true,"result":{"bid":[{"price":79000,"quantity":1}],"ask":[{"price":80000,"quantity":1}]}}"#,1900,1910).unwrap();
        let inventory = BTreeMap::from([("BTC".into(), Exact::parse("0.001").unwrap())]);
        Self {
            ledger,
            _credentials: credentials,
            balances,
            controller,
            gate,
            arm,
            fees,
            market,
            inventory,
            root,
        }
    }
    fn context(&self) -> IntentPreparation {
        IntentPreparation {
            client_id: "intent_1".into(),
            expected_sequence: self.ledger.operator_approval("intent_1").unwrap().sequence,
            principal: "S-1-5-21-100-1000".into(),
            logon: "S-1-5-5-100-200".into(),
            runtime_epoch: 10,
            credential_generation: [3; 16],
            recorded_at_ms: AT,
            request_id: [4; 16],
            mode: StopMode::Armed,
        }
    }
    fn admit(&mut self, context: IntentPreparation) -> Result<AdmittedOrder, RecoveryError> {
        native_admission::admit(
            &mut self.controller,
            &self.gate,
            &mut self.ledger,
            context,
            NativeInputs {
                arm: &self.arm,
                balances: &self.balances,
                fees: &self.fees,
                market: &self.market,
                own_inventory: &self.inventory,
            },
        )
    }
}

#[test]
fn exact_native_admission_commits_once_before_transport_and_preserves_unknown_holds() {
    let mut f = Fixture::new(true);
    let context = f.context();
    let admitted = f.admit(context.clone()).unwrap();
    assert_eq!(f.ledger.reserved("main", "USDT"), 8010000);
    let body: serde_json::Value = serde_json::from_slice(&admitted.body).unwrap();
    assert_eq!(body["quantity"], "0.00010000");
    assert_eq!(body["price"], "80000.00");
    assert_eq!(body["client_id"], "intent_1");
    assert_eq!(body["type"], "LIMIT");
    assert!(admitted.allows_effect_at(&f.gate, AT));
    assert!(!admitted.allows_effect_at(&f.gate, 20000));
    assert!(f.admit(context).is_err());
    f.ledger.record_event("intent_1", Event::BeginSend).unwrap();
    f.ledger
        .record_event(
            "intent_1",
            Event::TransportFailed(FailureStage::AfterFirstByte),
        )
        .unwrap();
    assert!(f.ledger.release_denied_reservation("intent_1").is_err());
    drop(admitted);
    let path = f.root.path().join("execution.sqlite");
    drop(f.ledger);
    let replay = DurableOrderJournal::open(path).unwrap();
    assert_eq!(replay.reserved("main", "USDT"), 8010000);
    assert!(!replay
        .get("intent_1")
        .unwrap()
        .attempt
        .can_retry_same_identity());
}

#[test]
fn every_refusal_preserves_the_unconsumed_review_and_does_not_reserve() {
    for case in 0..13 {
        let mut f = Fixture::new(true);
        let mut context = f.context();
        match case {
            0 => context.runtime_epoch += 1,
            1 => context.credential_generation = [9; 16],
            2 => context.expected_sequence -= 1,
            3 => context.principal = "S-1-5-21-100-1001".into(),
            4 => context.logon = "S-1-5-5-100-201".into(),
            5 => context.recorded_at_ms = 20000,
            6 => context.mode = StopMode::Disarmed,
            7 => {
                f.gate.disarm();
            }
            8 => {
                f.balances.own_activity(1990).unwrap();
            }
            9 => f.arm.privileged_fault = true,
            10 => f.arm.available = None,
            11 => {
                f.fees=AccountObservation::from_response(AccountKind::Fees,br#"{"success":true,"result":{"BTCUSDT":{"makerFeeRate":"0.01","takerFeeRate":"0.01"}}}"#,[3;16],10,[13;16],1900,1910).unwrap();
            }
            12 => {
                let read = f.balances.begin([3; 16], 10, [14; 16], 1990).unwrap();
                f.balances.abort(read);
            }
            _ => unreachable!(),
        }
        let count = f.ledger.record_count();
        let sequence = f.ledger.operator_approval("intent_1").unwrap().sequence;
        assert!(f.admit(context).is_err(), "case {case}");
        assert_eq!(f.ledger.record_count(), count);
        assert_eq!(f.ledger.reserved("main", "USDT"), 0);
        assert_eq!(
            f.ledger.operator_approval("intent_1").unwrap().sequence,
            sequence
        );
    }
}

#[test]
fn sell_uses_own_fill_inventory_and_holds_outgoing_fee_through_restart() {
    let mut f = Fixture::new(false);
    f.inventory.clear();
    assert!(f.admit(f.context()).is_err()); // Deposited BTC is not an executor position.
    f.inventory
        .insert("BTC".into(), Exact::parse("0.00010009").unwrap());
    assert!(f.admit(f.context()).is_err()); // One fee quantum short.
    f.inventory
        .insert("BTC".into(), Exact::parse("0.00010010").unwrap());
    let order = f.admit(f.context()).unwrap();
    assert_eq!(f.ledger.reserved("main", "BTC"), 10010);
    f.gate.disarm();
    assert!(!order.allows_effect_at(&f.gate, AT));
    drop(order);
    let path = f.root.path().join("execution.sqlite");
    drop(f.ledger);
    let replay = DurableOrderJournal::open(path).unwrap();
    assert_eq!(replay.reserved("main", "BTC"), 10010);
    assert_eq!(
        replay.get("intent_1").unwrap().attempt.requested_quanta(),
        10000
    );
}

#[test]
fn exact_rounding_refuses_overflow_and_never_rounds_a_hold_down() {
    assert_eq!(
        native_admission::rounded_quanta(Exact::parse("0.000000001").unwrap(), 8, true),
        Some(1)
    );
    assert_eq!(
        native_admission::rounded_quanta(Exact::parse("0.000000001").unwrap(), 8, false),
        Some(0)
    );
    assert_eq!(
        native_admission::rounded_quanta(Exact::parse("18446744073709551616").unwrap(), 0, true),
        None
    );
}

#[test]
fn real_attempt_composition_distinguishes_proven_unsent_and_uncertain_bytes_without_retry() {
    use exec_svc::native_effect::{execute, SendOutcome};
    for case in 0..4 {
        let mut f = Fixture::new(true);
        let order = f.admit(f.context()).unwrap();
        let mut calls = 0;
        let outcome = execute(
            &mut f.ledger,
            &order,
            &f.gate,
            || Some(AT),
            |_, allowed| {
                calls += 1;
                assert!(allowed());
                match case {
                    0 => Err(FailureStage::BeforeFirstByte),
                    1 => Err(FailureStage::AfterFirstByte),
                    2 => Ok(false),
                    3 => Ok(true),
                    _ => unreachable!(),
                }
            },
        )
        .unwrap();
        assert_eq!(calls, 1);
        assert_eq!(
            outcome,
            match case {
                0 => SendOutcome::NotSent,
                3 => SendOutcome::Observed,
                _ => SendOutcome::Pending,
            }
        );
        assert_eq!(
            f.ledger.reserved("main", "USDT"),
            if case == 0 { 0 } else { 8010000 }
        );
        assert!(execute(
            &mut f.ledger,
            &order,
            &f.gate,
            || Some(AT),
            |_, _| panic!("identity sent twice")
        )
        .is_err());
        drop(order);
        let path = f.root.path().join("execution.sqlite");
        drop(f.ledger);
        let replay = DurableOrderJournal::open(path).unwrap();
        assert_eq!(
            replay.reserved("main", "USDT"),
            if case == 0 { 0 } else { 8010000 }
        );
    }
}

#[test]
fn stop_before_or_during_transport_setup_never_sends_and_releases_only_a_proven_unsent_hold() {
    use exec_svc::native_effect::{execute, SendOutcome};
    for during in [false, true] {
        let mut f = Fixture::new(true);
        let order = f.admit(f.context()).unwrap();
        if !during {
            f.gate.disarm();
        }
        let outcome = execute(
            &mut f.ledger,
            &order,
            &f.gate,
            || Some(AT),
            |_, allowed| {
                assert!(during);
                f.gate.disarm();
                assert!(!allowed());
                Err(FailureStage::BeforeFirstByte)
            },
        )
        .unwrap();
        assert_eq!(outcome, SendOutcome::NotSent);
        assert_eq!(f.ledger.reserved("main", "USDT"), 0);
    }
}

fn native_terminal(
    f: &mut Fixture,
    buy: bool,
    partial: bool,
    sum: Option<&str>,
    base_fee: bool,
) -> AccountObservation {
    let quantity = if partial { "0.00005" } else { "0.0001" };
    let mut fill = serde_json::json!({"quantity":quantity,"price":"80000","fee":if base_fee {"0.00000010"}else if partial {"0.004"}else{"0.008"},
        "feeAsset":if base_fee {"BTC"}else{"USDT"},"timestamp":1700000000000u64});
    if let Some(sum) = sum {
        fill["sum"] = sum.into();
    }
    let body=serde_json::to_vec(&serde_json::json!({"success":true,"result":{"clientOrderId":"intent_1","symbol":"BTCUSDT",
        "side":if buy {"BUY"}else{"SELL"},"status":if partial {"CANCELED"}else{"FILLED"},"origQty":"0.0001","executedQty":quantity,"fills":[fill]}})).unwrap();
    let observation = AccountObservation::from_order_response(
        "intent_1", &body, [3; 16], 10, [15; 16], 2100, 2110,
    )
    .unwrap();
    f._credentials
        .record_account_observation(observation.clone())
        .unwrap();
    f.ledger
        .record_account_observation(observation.clone())
        .unwrap();
    observation
}
fn fresh_settlement_pair(f: &mut Fixture, locked: &str) {
    for (id, start) in [(20, 2200), (21, 2220)] {
        let read = f.balances.begin([3; 16], 10, [id; 16], start).unwrap();
        let body = serde_json::to_vec(&serde_json::json!({"success":true,"result":{"balances":{
            "USDT":{"value":"18.992","locked":locked},"BTC":{"value":"1.0001","locked":locked}}}}))
        .unwrap();
        let observation = AccountObservation::from_response(
            AccountKind::Balances,
            &body,
            [3; 16],
            10,
            [id; 16],
            start,
            start + 10,
        )
        .unwrap();
        f.balances
            .complete(read, observation, &mut f._credentials, Some(&mut f.ledger))
            .unwrap();
    }
}

#[test]
fn native_terminal_fills_and_later_pair_close_and_release_atomically_even_with_a_credit() {
    use exec_svc::{native_effect::execute, native_settlement};
    for (buy, partial, base_fee) in [
        (true, false, false),
        (true, true, false),
        (false, false, true),
    ] {
        let mut f = Fixture::new(buy);
        let order = f.admit(f.context()).unwrap();
        execute(&mut f.ledger, &order, &f.gate, || Some(AT), |_, _| Ok(true)).unwrap();
        f.balances.own_activity(2100).unwrap();
        native_terminal(
            &mut f,
            buy,
            partial,
            Some(if partial { "4" } else { "8" }),
            base_fee,
        );
        assert!(
            !native_settlement::reconcile(&mut f.ledger, &f.balances, [3; 16], 10, 2110).unwrap()
        );
        fresh_settlement_pair(&mut f, "0");
        let count = f.ledger.record_count();
        assert!(
            native_settlement::reconcile(&mut f.ledger, &f.balances, [3; 16], 10, 2230).unwrap()
        );
        assert_eq!(f.ledger.record_count(), count + 1);
        assert_eq!(
            f.ledger.reserved("main", if buy { "USDT" } else { "BTC" }),
            0
        );
        assert_eq!(
            f.ledger.get("intent_1").unwrap().attempt.lifecycle(),
            exec_core::orders::Lifecycle::Closed
        );
        assert_eq!(
            f.ledger.get("intent_1").unwrap().attempt.filled_quanta(),
            if partial { 5000 } else { 10000 }
        );
        drop(order);
        let path = f.root.path().join("execution.sqlite");
        drop(f.ledger);
        let replay = DurableOrderJournal::open(path).unwrap();
        assert!(replay.reconciliation_ready());
        assert!(replay.reviewed_pending_ids().is_empty());
    }
}

#[test]
fn missing_gross_cash_locked_balance_or_changed_context_never_releases_a_terminal_hold() {
    use exec_svc::{native_effect::execute, native_settlement};
    for case in 0..4 {
        let mut f = Fixture::new(true);
        let order = f.admit(f.context()).unwrap();
        execute(&mut f.ledger, &order, &f.gate, || Some(AT), |_, _| Ok(true)).unwrap();
        f.balances.own_activity(2100).unwrap();
        native_terminal(
            &mut f,
            true,
            false,
            if case == 0 { None } else { Some("8") },
            false,
        );
        fresh_settlement_pair(&mut f, if case == 1 { "0.1" } else { "0" });
        let count = f.ledger.record_count();
        assert!(!native_settlement::reconcile(
            &mut f.ledger,
            &f.balances,
            if case == 2 { [9; 16] } else { [3; 16] },
            if case == 3 { 11 } else { 10 },
            2230
        )
        .unwrap());
        assert_eq!(f.ledger.reserved("main", "USDT"), 8010000);
        assert_eq!(f.ledger.record_count(), count);
    }
}

#[test]
fn invalid_atomic_settlement_keeps_both_the_attempt_and_hold_unchanged() {
    use exec_svc::native_effect::execute;
    let mut f = Fixture::new(true);
    let order = f.admit(f.context()).unwrap();
    execute(&mut f.ledger, &order, &f.gate, || Some(AT), |_, _| Ok(true)).unwrap();
    f.balances.own_activity(2100).unwrap();
    native_terminal(&mut f, true, false, Some("8"), false);
    fresh_settlement_pair(&mut f, "0");
    let evidence = f
        .balances
        .settlement_evidence("USDT", 6, 8008000, 2110, 2230)
        .unwrap();
    for case in 0..5 {
        let mut bad = evidence.clone();
        let mut filled = 10000;
        match case {
            0 => bad.locked_quanta = 1,
            1 => bad.spent_quanta = 8010001,
            2 => bad.sequence = 1,
            3 => bad.complete = false,
            4 => filled = 10001,
            _ => unreachable!(),
        };
        let count = f.ledger.record_count();
        let before = f.ledger.get("intent_1").unwrap().attempt;
        assert!(f.ledger.settle_reviewed("intent_1", filled, &bad).is_err());
        assert_eq!(f.ledger.record_count(), count);
        assert_eq!(f.ledger.get("intent_1").unwrap().attempt, before);
        assert_eq!(f.ledger.reserved("main", "USDT"), 8010000);
    }
}

#[test]
fn restart_recovery_releases_only_durably_proven_unsent_reviews() {
    use exec_svc::native_settlement;
    for case in 0..4 {
        let mut f = Fixture::new(true);
        let order = f.admit(f.context()).unwrap();
        match case {
            0 => {}
            1 => f.ledger.record_event("intent_1", Event::Denied).unwrap(),
            2 | 3 => {
                f.ledger.record_event("intent_1", Event::BeginSend).unwrap();
                f.ledger
                    .record_event(
                        "intent_1",
                        Event::TransportFailed(if case == 2 {
                            FailureStage::BeforeFirstByte
                        } else {
                            FailureStage::AfterFirstByte
                        }),
                    )
                    .unwrap();
            }
            _ => unreachable!(),
        }
        drop(order);
        let path = f.root.path().join("execution.sqlite");
        drop(f.ledger);
        let mut replay = DurableOrderJournal::open(path).unwrap();
        native_settlement::recover_unsent(&mut replay).unwrap();
        assert_eq!(
            replay.reserved("main", "USDT"),
            if case == 3 { 8010000 } else { 0 }
        );
        assert_eq!(replay.reconciliation_ready(), case != 3);
    }
}

#[test]
fn a_balance_pair_that_predates_the_terminal_read_cannot_settle_and_partial_terminal_cash_is_kept()
{
    use exec_svc::{native_effect::execute, native_settlement};
    let mut f = Fixture::new(true);
    let order = f.admit(f.context()).unwrap();
    execute(&mut f.ledger, &order, &f.gate, || Some(AT), |_, _| Ok(true)).unwrap();
    let terminal = native_terminal(&mut f, true, true, Some("4"), false);
    assert!(!native_settlement::reconcile(&mut f.ledger, &f.balances, [3; 16], 10, 2110).unwrap());
    assert_eq!(f.ledger.reserved("main", "USDT"), 8010000);
    let mut raw = terminal.data().clone();
    raw["result"]["status"] = "FILLED".into();
    let partial = AccountObservation::from_order_response(
        "intent_1",
        &serde_json::to_vec(&raw).unwrap(),
        [3; 16],
        10,
        [16; 16],
        2100,
        2110,
    )
    .unwrap();
    let summary = native_settlement::summarize(&order.ticket, &partial).unwrap();
    assert!(summary.terminal);
    assert_eq!(summary.filled_quanta, 5000);
    assert_eq!(summary.spent_quanta, 4004000);
}
