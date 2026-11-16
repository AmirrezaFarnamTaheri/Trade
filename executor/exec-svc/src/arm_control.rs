//! Service-side arm approval. IPC callers never supply the measured evidence.
use crate::{ApprovalSnapshot, StopGate};
use exec_core::{
    arming::{self, ArmPolicy, ArmRecord, KillInputs, Preflight, Verdict},
    available::Available,
    kernel::Exact,
};
pub use exec_ipc::arm::ArmBlocker;
use exec_ipc::StopMode;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{self, Read},
    path::{Component, Path, PathBuf},
};

const MAX_POLICY_BYTES: u64 = 8192;
const EVIDENCE_MAX_AGE_MS: u64 = 1000;

/// Native measurements at the current runtime. Missing values are explicit blockers.
#[derive(Debug, Clone)]
pub struct ArmEvidence {
    pub measured_at_ms: u64,
    pub runtime_epoch: u64,
    pub credential_generation: Option<[u8; 16]>,
    pub available: Option<Available>,
    pub market_received_at_ms: Option<u64>,
    pub loss_quote: Option<Exact>,
    pub open_orders: Option<u32>,
    pub orders_today: Option<u32>,
    pub reconciliation_clean: bool,
    pub privileged_fault: bool,
    pub blockers: Vec<ArmBlocker>,
}

impl ArmEvidence {
    pub fn missing(now_ms: u64, runtime_epoch: u64) -> Self {
        Self {
            measured_at_ms: now_ms,
            runtime_epoch,
            credential_generation: None,
            available: None,
            market_received_at_ms: None,
            loss_quote: None,
            open_orders: None,
            orders_today: None,
            reconciliation_clean: false,
            privileged_fault: false,
            blockers: vec![
                ArmBlocker::TradePermission,
                ArmBlocker::RecentBackup,
                ArmBlocker::ProspectiveEvidence,
                ArmBlocker::OpenIncident,
            ],
        }
    }

    /// Only the native evidence producer may remove a blocker after verifying its source.
    pub fn blockers(&self, policy: &ArmPolicy, epoch: u64, now_ms: u64) -> u64 {
        let mut blocked = self.blockers.iter().fold(0, |bits, item| bits | item.bit());
        let mut require = |ok: bool, item: ArmBlocker| {
            if !ok {
                blocked |= item.bit();
            }
        };
        require(self.runtime_epoch == epoch, ArmBlocker::RuntimeChanged);
        require(
            self.measured_at_ms <= now_ms && now_ms - self.measured_at_ms <= EVIDENCE_MAX_AGE_MS,
            ArmBlocker::EvidenceExpired,
        );
        require(
            self.credential_generation
                .is_some_and(|generation| generation != [0; 16]),
            ArmBlocker::CredentialsMissing,
        );
        let stale_ms = u64::from(policy.stale_data_seconds)
            .saturating_mul(1000)
            .min(120_000);
        let elapsed = now_ms.saturating_sub(self.measured_at_ms);
        require(
            self.available.is_some_and(|value| {
                value.receipt_seq != 0
                    && value
                        .age_ms
                        .checked_add(elapsed)
                        .is_some_and(|age| age <= stale_ms)
            }),
            ArmBlocker::FreshBalance,
        );
        require(
            self.market_received_at_ms
                .is_some_and(|at| at <= now_ms && now_ms - at <= stale_ms),
            ArmBlocker::FreshFeed,
        );
        require(
            self.loss_quote.is_some_and(|value| value.scale <= 38),
            ArmBlocker::LossUnknown,
        );
        require(self.open_orders.is_some(), ArmBlocker::OpenOrdersUnknown);
        require(self.orders_today.is_some(), ArmBlocker::OrdersTodayUnknown);
        require(self.reconciliation_clean, ArmBlocker::Reconciliation);
        require(!self.privileged_fault, ArmBlocker::PrivilegedFault);
        blocked
    }

    fn inputs(
        &self,
        policy: &ArmPolicy,
        epoch: u64,
        now_ms: u64,
    ) -> Result<KillInputs, ArmControlError> {
        let blocked = self.blockers(policy, epoch, now_ms);
        if blocked != 0 {
            return Err(ArmControlError::Blocked(blocked));
        }
        let missing = || ArmControlError::Blocked(ArmBlocker::EvidenceExpired.bit());
        let available = self.available.ok_or_else(missing)?;
        let received = self.market_received_at_ms.ok_or_else(missing)?;
        Ok(KillInputs {
            now_ms,
            runtime_epoch: self.runtime_epoch,
            loss_quote: self.loss_quote.ok_or_else(missing)?,
            newest_data_age_ms: available
                .age_ms
                .saturating_add(now_ms - self.measured_at_ms)
                .max(now_ms - received),
            open_orders: self.open_orders.ok_or_else(missing)?,
            orders_today: self.orders_today.ok_or_else(missing)?,
            reconciliation_clean: self.reconciliation_clean,
            privileged_fault: self.privileged_fault,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArmControlError {
    Blocked(u64),
    Kill(arming::KillReason),
    Order(arming::OrderRefusal),
}

impl ArmControlError {
    pub fn blocker_mask(&self) -> u64 {
        match self {
            Self::Blocked(mask) => *mask,
            Self::Kill(_) | Self::Order(_) => ArmBlocker::Stopped.bit(),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawPolicy {
    schema: u32,
    venue: String,
    quote_asset: String,
    symbols: Vec<String>,
    loss_cap_quote: String,
    max_order_quote: String,
    max_orders_per_day: u32,
    kill: RawKill,
    expires_days: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawKill {
    max_loss_quote: String,
    stale_data_seconds: u32,
    max_open_orders: u32,
}

fn parse_policy(raw: &[u8]) -> io::Result<ArmPolicy> {
    let invalid = || io::Error::other("invalid owner arm policy");
    let value: RawPolicy = serde_json::from_slice(raw).map_err(|_| invalid())?;
    if value.schema != 1 {
        return Err(invalid());
    }
    let policy = ArmPolicy {
        policy_sha256: Sha256::digest(raw).into(),
        venue: value.venue,
        quote_asset: value.quote_asset,
        symbols: value.symbols,
        loss_cap_quote: Exact::parse(&value.loss_cap_quote).ok_or_else(invalid)?,
        max_order_quote: Exact::parse(&value.max_order_quote).ok_or_else(invalid)?,
        max_orders_per_day: value.max_orders_per_day,
        kill_max_loss_quote: Exact::parse(&value.kill.max_loss_quote).ok_or_else(invalid)?,
        stale_data_seconds: value.kill.stale_data_seconds,
        max_open_orders: value.kill.max_open_orders,
        expires_days: value.expires_days,
    };
    policy.validate().map_err(|_| invalid())?;
    Ok(policy)
}

/// The open policy file stays read-only and uneditable during one admission/effect on Windows.
/// Keep this lease alive until the final venue-effect boundary has checked the stop gate again.
#[must_use = "keep the policy lease until the venue-effect boundary"]
pub struct PolicyLease {
    _file: File,
    runtime_epoch: u64,
    revision: u64,
    armed_at_ms: u64,
    expires_at_ms: u64,
}

impl PolicyLease {
    /// Repeat immediately before each venue effect; the file lease alone grants no authority.
    pub fn allows_effect_at(&self, gate: &StopGate, now_ms: u64) -> bool {
        now_ms >= self.armed_at_ms
            && now_ms < self.expires_at_ms
            && gate.is_armed_at(self.runtime_epoch, self.revision)
    }
}

pub struct PolicyFile {
    path: PathBuf,
    policy: ArmPolicy,
}

impl PolicyFile {
    pub fn open(path: &Path, expected_sha256: [u8; 32]) -> io::Result<Self> {
        if !path.is_absolute()
            || path.components().any(|part| part == Component::ParentDir)
            || !path
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.eq_ignore_ascii_case("arm-policy.json"))
            || path.to_string_lossy().starts_with("\\\\")
        {
            return Err(io::Error::other("invalid local arm policy path"));
        }
        let path = path.to_path_buf();
        let (_lease, policy) = Self::read(&path)?;
        if expected_sha256 == [0; 32] || policy.policy_sha256 != expected_sha256 {
            return Err(io::Error::other("owner arm policy hash changed"));
        }
        Ok(Self { path, policy })
    }

    pub fn policy(&self) -> &ArmPolicy {
        &self.policy
    }

    fn read(path: &Path) -> io::Result<(PolicyLease, ArmPolicy)> {
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_file()
            || metadata.file_type().is_symlink()
            || metadata.len() > MAX_POLICY_BYTES
        {
            return Err(io::Error::other("invalid arm policy file"));
        }
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ);
        }
        let mut file = options.open(path)?;
        if !file.metadata()?.is_file() {
            return Err(io::Error::other("invalid arm policy handle"));
        }
        let mut raw = Vec::new();
        (&mut file)
            .take(MAX_POLICY_BYTES + 1)
            .read_to_end(&mut raw)?;
        if raw.is_empty() || raw.len() as u64 > MAX_POLICY_BYTES {
            return Err(io::Error::other("invalid arm policy bounds"));
        }
        let policy = parse_policy(&raw)?;
        Ok((
            PolicyLease {
                _file: file,
                runtime_epoch: 0,
                revision: 0,
                armed_at_ms: 0,
                expires_at_ms: 0,
            },
            policy,
        ))
    }

    fn lease(&self) -> io::Result<PolicyLease> {
        let (lease, policy) = Self::read(&self.path)?;
        if policy != self.policy {
            return Err(io::Error::other("owner arm policy changed"));
        }
        Ok(lease)
    }
}

#[derive(Default)]
pub struct ArmController {
    record: Option<ArmRecord>,
    policy: Option<PolicyFile>,
    generation: Option<[u8; 16]>,
}

impl ArmController {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn policy(&self) -> Option<&ArmPolicy> {
        self.record.as_ref().map(|record| &record.policy)
    }
    pub fn record(&self) -> Option<&ArmRecord> {
        self.record.as_ref()
    }

    pub fn approve(
        &mut self,
        gate: &StopGate,
        snapshot: ApprovalSnapshot,
        policy: PolicyFile,
        evidence: &ArmEvidence,
        approver: &str,
        now_ms: u64,
    ) -> Result<ArmRecord, ArmControlError> {
        self.approve_committed(gate, snapshot, policy, evidence, approver, now_ms, |_| {
            Ok(now_ms)
        })
    }

    /// The native host persists the approval before the gate can gain authority.
    #[allow(clippy::too_many_arguments)]
    pub fn approve_committed(
        &mut self,
        gate: &StopGate,
        snapshot: ApprovalSnapshot,
        policy: PolicyFile,
        evidence: &ArmEvidence,
        approver: &str,
        now_ms: u64,
        persist: impl FnOnce(&ArmRecord) -> io::Result<u64>,
    ) -> Result<ArmRecord, ArmControlError> {
        let _lease = policy
            .lease()
            .map_err(|_| ArmControlError::Blocked(ArmBlocker::Policy.bit()))?;
        let inputs = evidence.inputs(policy.policy(), gate.runtime_epoch(), now_ms)?;
        let record = arming::approve(
            policy.policy.clone(),
            &Preflight::passing(&arming::PREFLIGHT_ITEMS),
            approver,
            gate.runtime_epoch(),
            now_ms,
        )
        .map_err(|_| ArmControlError::Blocked(ArmBlocker::Policy.bit()))?;
        if let Verdict::Disarm(reason) = record.check(&inputs) {
            return Err(ArmControlError::Kill(reason));
        }
        let committed_at_ms = persist(&record)
            .map_err(|_| ArmControlError::Blocked(ArmBlocker::PrivilegedFault.bit()))?;
        let inputs = evidence.inputs(&record.policy, gate.runtime_epoch(), committed_at_ms)?;
        if let Verdict::Disarm(reason) = record.check(&inputs) {
            return Err(ArmControlError::Kill(reason));
        }
        gate.arm(snapshot)
            .map_err(|_| ArmControlError::Blocked(ArmBlocker::ApprovalChanged.bit()))?;
        self.generation = evidence.credential_generation;
        self.record = Some(record.clone());
        self.policy = Some(policy);
        Ok(record)
    }

    pub fn disarm(&mut self, gate: &StopGate) {
        gate.disarm();
        self.record = None;
        self.policy = None;
        self.generation = None;
    }

    fn check(
        &self,
        gate: &StopGate,
        evidence: &ArmEvidence,
        now_ms: u64,
    ) -> Result<PolicyLease, ArmControlError> {
        if gate.mode() != StopMode::Armed {
            return Err(ArmControlError::Blocked(ArmBlocker::Stopped.bit()));
        }
        if evidence.credential_generation != self.generation {
            return Err(ArmControlError::Blocked(
                ArmBlocker::CredentialsMissing.bit(),
            ));
        }
        let record = self
            .record
            .as_ref()
            .ok_or(ArmControlError::Blocked(ArmBlocker::Stopped.bit()))?;
        let inputs = evidence.inputs(&record.policy, gate.runtime_epoch(), now_ms)?;
        if let Verdict::Disarm(reason) = record.check(&inputs) {
            return Err(ArmControlError::Kill(reason));
        }
        self.policy
            .as_ref()
            .ok_or(ArmControlError::Blocked(ArmBlocker::Policy.bit()))?
            .lease()
            .map_err(|_| ArmControlError::Blocked(ArmBlocker::Policy.bit()))
    }

    pub fn safety_tick(
        &mut self,
        gate: &StopGate,
        evidence: &ArmEvidence,
        now_ms: u64,
    ) -> Result<(), ArmControlError> {
        if gate.mode() != StopMode::Armed {
            self.record = None;
            self.policy = None;
            self.generation = None;
            return Ok(());
        }
        match self.check(gate, evidence, now_ms) {
            Ok(_lease) => Ok(()),
            Err(error) => {
                self.disarm(gate);
                Err(error)
            }
        }
    }

    pub fn admit_order(
        &mut self,
        gate: &StopGate,
        evidence: &ArmEvidence,
        now_ms: u64,
        symbol: &str,
        notional: Exact,
    ) -> Result<PolicyLease, ArmControlError> {
        let revision = gate.revision();
        let mut lease = match self.check(gate, evidence, now_ms) {
            Ok(lease) => lease,
            Err(error) => {
                self.disarm(gate);
                return Err(error);
            }
        };
        let record = self
            .record
            .as_ref()
            .ok_or(ArmControlError::Blocked(ArmBlocker::Stopped.bit()))?;
        let inputs = evidence.inputs(&record.policy, gate.runtime_epoch(), now_ms)?;
        record
            .admit_order(symbol, notional, &inputs)
            .map_err(ArmControlError::Order)?;
        if gate.mode() != StopMode::Armed || gate.revision() != revision {
            return Err(ArmControlError::Blocked(ArmBlocker::Stopped.bit()));
        }
        lease.runtime_epoch = gate.runtime_epoch();
        lease.revision = revision;
        lease.armed_at_ms = record.armed_at_ms;
        lease.expires_at_ms = record.expires_at_ms;
        Ok(lease)
    }
}
