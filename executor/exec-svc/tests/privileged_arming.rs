//! Synthetic native evidence exercises authority composition, never a real funded venue.
use exec_core::{
    arming::{KillReason, OrderRefusal},
    available::Available,
    kernel::Exact,
};
use exec_ipc::{arm::ArmBlocker, StopCommand, StopMode, StopRequest};
use exec_svc::{
    arm_control::{ArmControlError, ArmController, ArmEvidence, PolicyFile},
    StopGate,
};
use sha2::{Digest, Sha256};
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Barrier},
    time::{SystemTime, UNIX_EPOCH},
};

const NOW: u64 = 1_800_000_000_000;
const POLICY: &[u8] = br#"{"schema":1,"venue":"wallex","quote_asset":"USDT","symbols":["BTCUSDT"],"loss_cap_quote":"50","max_order_quote":"10","max_orders_per_day":10,"kill":{"max_loss_quote":"20","stale_data_seconds":120,"max_open_orders":2},"expires_days":7}"#;

struct OwnerFile {
    root: PathBuf,
}
impl OwnerFile {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "gym-arm-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let value = Self { root };
        std::fs::write(value.path(), POLICY).unwrap();
        value
    }
    fn path(&self) -> PathBuf {
        self.root.join("arm-policy.json")
    }
    fn policy(&self) -> PolicyFile {
        PolicyFile::open(&self.path(), Sha256::digest(POLICY).into()).unwrap()
    }
}
impl Drop for OwnerFile {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}

fn evidence(now: u64) -> ArmEvidence {
    ArmEvidence {
        measured_at_ms: now,
        runtime_epoch: 7,
        credential_generation: Some([1; 16]),
        available: Some(Available {
            available_quanta: 50_000_000,
            receipt_seq: 2,
            age_ms: 0,
        }),
        market_received_at_ms: Some(now),
        loss_quote: Exact::parse("0"),
        open_orders: Some(0),
        orders_today: Some(0),
        reconciliation_clean: true,
        privileged_fault: false,
        blockers: Vec::new(),
    }
}

fn stop(gate: &StopGate, command: StopCommand) {
    gate.process(StopRequest {
        command,
        runtime_epoch: gate.runtime_epoch(),
        correlation: [1; 16],
    });
}

fn armed(owner: &OwnerFile) -> (StopGate, ArmController) {
    let gate = StopGate::new(7).unwrap();
    let mut controller = ArmController::new();
    controller
        .approve(
            &gate,
            gate.approval_snapshot().unwrap(),
            owner.policy(),
            &evidence(NOW),
            "owner",
            NOW,
        )
        .unwrap();
    assert_eq!(gate.mode(), StopMode::Armed);
    (gate, controller)
}

#[test]
fn only_a_complete_current_native_preflight_can_arm() {
    let owner = OwnerFile::new();
    for missing in 0..14 {
        let gate = StopGate::new(7).unwrap();
        let mut controller = ArmController::new();
        let mut source = evidence(NOW);
        match missing {
            0 => source = ArmEvidence::missing(NOW, 7),
            1 => source.credential_generation = None,
            2 => source.available = None,
            3 => source.market_received_at_ms = None,
            4 => source.loss_quote = None,
            5 => source.open_orders = None,
            6 => source.orders_today = None,
            7 => source.reconciliation_clean = false,
            8 => source.privileged_fault = true,
            9 => source.blockers.push(ArmBlocker::TradePermission),
            10 => source.blockers.push(ArmBlocker::RecentBackup),
            11 => source.blockers.push(ArmBlocker::ProspectiveEvidence),
            12 => source.blockers.push(ArmBlocker::OpenIncident),
            13 => source.measured_at_ms -= 1001,
            _ => unreachable!(),
        }
        assert!(
            controller
                .approve(
                    &gate,
                    gate.approval_snapshot().unwrap(),
                    owner.policy(),
                    &source,
                    "owner",
                    NOW
                )
                .is_err(),
            "case {missing}"
        );
        assert_eq!(gate.mode(), StopMode::Disarmed);
        assert!(controller.record().is_none());
    }
    let (gate, mut controller) = armed(&owner);
    let lease = controller
        .admit_order(
            &gate,
            &evidence(NOW),
            NOW,
            "BTCUSDT",
            Exact::parse("10").unwrap(),
        )
        .unwrap();
    assert!(lease.allows_effect_at(&gate, NOW));
    assert_eq!(StopGate::new(8).unwrap().mode(), StopMode::Disarmed);
}

#[test]
fn stop_or_disarm_during_preflight_invalidates_the_approval_snapshot() {
    let owner = OwnerFile::new();
    for command in [
        None,
        Some(StopCommand::PauseEntries),
        Some(StopCommand::ExitOnly),
        Some(StopCommand::Halt),
    ] {
        let gate = StopGate::new(7).unwrap();
        let snapshot = gate.approval_snapshot().unwrap();
        match command {
            None => gate.disarm(),
            Some(command) => stop(&gate, command),
        }
        let mut controller = ArmController::new();
        assert_eq!(
            controller.approve(
                &gate,
                snapshot,
                owner.policy(),
                &evidence(NOW),
                "owner",
                NOW
            ),
            Err(ArmControlError::Blocked(ArmBlocker::ApprovalChanged.bit()))
        );
        if command == Some(StopCommand::Halt) {
            controller.disarm(&gate);
            assert_eq!(gate.mode(), StopMode::Halted);
        }
    }
}

#[test]
fn approval_commit_failure_or_stop_during_commit_never_opens_the_gate() {
    let owner = OwnerFile::new();
    for halted in [false, true] {
        let gate = StopGate::new(7).unwrap();
        let mut controller = ArmController::new();
        let result = controller.approve_committed(
            &gate,
            gate.approval_snapshot().unwrap(),
            owner.policy(),
            &evidence(NOW),
            "owner",
            NOW,
            |record| {
                assert_eq!(gate.mode(), StopMode::Disarmed);
                assert_ne!(record.digest(), [0; 32]);
                if halted {
                    stop(&gate, StopCommand::Halt);
                    Ok(NOW)
                } else {
                    Err(std::io::Error::other("synthetic disk failure"))
                }
            },
        );
        assert!(result.is_err());
        assert_eq!(
            gate.mode(),
            if halted {
                StopMode::Halted
            } else {
                StopMode::Disarmed
            }
        );
        assert!(controller.record().is_none());
    }
}

#[test]
fn slow_or_regressing_approval_commit_cannot_backdate_freshness() {
    let owner = OwnerFile::new();
    for committed_at in [NOW - 1, NOW + 1001, NOW + 120001] {
        let gate = StopGate::new(7).unwrap();
        let mut controller = ArmController::new();
        assert!(controller
            .approve_committed(
                &gate,
                gate.approval_snapshot().unwrap(),
                owner.policy(),
                &evidence(NOW),
                "owner",
                NOW,
                |_| Ok(committed_at)
            )
            .is_err());
        assert_eq!(gate.mode(), StopMode::Disarmed);
        assert!(controller.record().is_none());
    }
}

#[test]
fn concurrent_halt_always_revokes_an_arm_even_when_approval_wins_first() {
    let owner = OwnerFile::new();
    for _ in 0..50 {
        let gate = Arc::new(StopGate::new(7).unwrap());
        let snapshot = gate.approval_snapshot().unwrap();
        let barrier = Arc::new(Barrier::new(2));
        let other = gate.clone();
        let ready = barrier.clone();
        let stopper = std::thread::spawn(move || {
            ready.wait();
            stop(&other, StopCommand::Halt);
        });
        let mut controller = ArmController::new();
        let policy = owner.policy();
        barrier.wait();
        let _result = controller.approve(&gate, snapshot, policy, &evidence(NOW), "owner", NOW);
        stopper.join().unwrap();
        assert_eq!(gate.mode(), StopMode::Halted);
        controller.disarm(&gate);
        assert_eq!(gate.mode(), StopMode::Halted);
    }
}

#[test]
fn every_measured_kill_input_revokes_the_live_gate() {
    let owner = OwnerFile::new();
    for case in 0..12 {
        let (gate, mut controller) = armed(&owner);
        let mut now = NOW;
        let mut source = evidence(now);
        match case {
            0 => {
                now += 7 * 86_400_000;
                source = evidence(now);
            }
            1 => source.runtime_epoch += 1,
            2 => source.privileged_fault = true,
            3 => source.reconciliation_clean = false,
            4 => source.loss_quote = Exact::parse("20"),
            5 => source.loss_quote = Exact::parse("50"),
            6 => source.available.as_mut().unwrap().age_ms = 120001,
            7 => source.market_received_at_ms = Some(NOW - 120001),
            8 => source.open_orders = Some(3),
            9 => source.credential_generation = Some([2; 16]),
            10 => source.loss_quote = None,
            11 => source.blockers.push(ArmBlocker::OpenIncident),
            _ => unreachable!(),
        }
        assert!(
            controller.safety_tick(&gate, &source, now).is_err(),
            "case {case}"
        );
        assert_eq!(gate.mode(), StopMode::Disarmed);
        assert!(controller.record().is_none());
        assert!(controller
            .admit_order(
                &gate,
                &evidence(now),
                now,
                "BTCUSDT",
                Exact::parse("1").unwrap()
            )
            .is_err());
    }
}

#[test]
fn file_changes_revoke_approval_and_each_effect_holds_the_policy_lease() {
    let owner = OwnerFile::new();
    let (gate, mut controller) = armed(&owner);
    let lease = controller
        .admit_order(
            &gate,
            &evidence(NOW),
            NOW,
            "BTCUSDT",
            Exact::parse("1").unwrap(),
        )
        .unwrap();
    #[cfg(windows)]
    assert!(std::fs::write(owner.path(), POLICY).is_err());
    stop(&gate, StopCommand::PauseEntries);
    assert!(!lease.allows_effect_at(&gate, NOW));
    drop(lease);
    let (gate, mut controller) = armed(&owner);
    std::fs::write(
        owner.path(),
        String::from_utf8(POLICY.to_vec())
            .unwrap()
            .replace("\"50\"", "\"60\""),
    )
    .unwrap();
    assert_eq!(
        controller.safety_tick(&gate, &evidence(NOW), NOW),
        Err(ArmControlError::Blocked(ArmBlocker::Policy.bit()))
    );
    assert_eq!(gate.mode(), StopMode::Disarmed);
    std::fs::write(owner.path(), POLICY).unwrap();
    assert_eq!(gate.mode(), StopMode::Disarmed);
}

#[test]
fn effect_lease_expires_without_waiting_for_the_safety_tick() {
    let owner = OwnerFile::new();
    let (gate, mut controller) = armed(&owner);
    let lease = controller
        .admit_order(
            &gate,
            &evidence(NOW),
            NOW,
            "BTCUSDT",
            Exact::parse("1").unwrap(),
        )
        .unwrap();
    assert!(!lease.allows_effect_at(&gate, NOW - 1));
    assert!(lease.allows_effect_at(&gate, NOW + 7 * 86_400_000 - 1));
    assert!(!lease.allows_effect_at(&gate, NOW + 7 * 86_400_000));
}

#[test]
fn malformed_ambiguous_or_unbound_owner_policy_is_refused() {
    let owner = OwnerFile::new();
    assert!(PolicyFile::open(&owner.path(), [1; 32]).is_err());
    assert!(PolicyFile::open(Path::new("arm-policy.json"), [1; 32]).is_err());
    for raw in [
        b"{}".to_vec(),
        [POLICY, b" ", POLICY].concat(),
        String::from_utf8(POLICY.to_vec())
            .unwrap()
            .replace("\"schema\":1", "\"schema\":1,\"schema\":1")
            .into_bytes(),
        String::from_utf8(POLICY.to_vec())
            .unwrap()
            .replace("\"expires_days\":7", "\"expires_days\":true")
            .into_bytes(),
        vec![b'x'; 8193],
    ] {
        std::fs::write(owner.path(), &raw).unwrap();
        assert!(PolicyFile::open(&owner.path(), Sha256::digest(&raw).into()).is_err());
    }
}

#[test]
fn order_limits_are_checked_after_live_safety_without_silently_rearming() {
    let owner = OwnerFile::new();
    let (gate, mut controller) = armed(&owner);
    assert!(matches!(
        controller.admit_order(
            &gate,
            &evidence(NOW),
            NOW,
            "BTCUSDT",
            Exact::parse("10.01").unwrap()
        ),
        Err(ArmControlError::Order(OrderRefusal::MaxOrder))
    ));
    assert_eq!(gate.mode(), StopMode::Armed);
    let mut source = evidence(NOW);
    source.loss_quote = Exact::parse("20");
    assert!(matches!(
        controller.admit_order(&gate, &source, NOW, "BTCUSDT", Exact::parse("1").unwrap()),
        Err(ArmControlError::Kill(KillReason::KillLoss))
    ));
    assert_eq!(gate.mode(), StopMode::Disarmed);
}
