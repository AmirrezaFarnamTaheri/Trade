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
