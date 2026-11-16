use super::{now_ms, random_id, require_service_identity, Secret, Vault};
use exec_core::arming::ArmPolicy;
use exec_core::kernel::Exact;
use exec_ipc::arm::{ArmBlocker, ArmCommand, ArmReply, ArmRequest, ArmResult};
use exec_svc::arm_control::{ArmEvidence, PolicyFile};
use exec_svc::offline_recovery::AuditStatus;
use exec_svc::owner_evidence::OwnerEvidence;
use std::{
    fs::{File, OpenOptions},
    io::{self, Write},
    path::Path,
};

pub(super) struct NativeBackup {
    generation: [u8; 16],
    made_at_ms: u64,
    _leases: Vec<File>,
}

fn read_lease(path: &Path) -> io::Result<File> {
    use std::os::windows::fs::OpenOptionsExt;
    use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
    OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .open(path)
}

impl Vault {
    pub fn bind_gate(&mut self, gate: std::sync::Arc<exec_svc::StopGate>) {
        self.gate = Some(gate);
    }

    pub(crate) fn disarm(&mut self) {
        if let Some(gate) = &self.gate {
            self.arm_controller.disarm(gate);
        }
        self.owner_review = None;
    }
    pub fn mark_fault(&mut self) {
        self.native_incident = true;
        self.disarm();
    }
    pub fn poll_plan(
        &mut self,
    ) -> io::Result<Option<(Vec<exec_ipc::provision::AccountResource>, Vec<String>)>> {
        use exec_ipc::provision::AccountResource;
        if self.journal.credential_metadata().is_none() {
            return Ok(None);
        }
        if let Some(ledger) = self.limits.as_mut() {
            exec_svc::native_settlement::recover_unsent(ledger)
                .map_err(|_| io::Error::other("native unsent recovery failed"))?;
        }
        let mut resources = vec![AccountResource::Fees];
        if let Some(ledger) = &self.limits {
            resources.extend(
                ledger
                    .pending_ids()
                    .into_iter()
                    .take(100)
                    .map(|id| AccountResource::KnownClientOrder(id.into())),
            );
        }
        resources.push(AccountResource::OpenOrders {
            page: 1,
            per_page: 100,
        });
        resources.extend([AccountResource::Balances, AccountResource::Balances]);
        let symbols = self
            .observation_policy
            .as_ref()
            .map(|policy| policy.symbols.clone())
            .unwrap_or_else(|| vec!["BTCUSDT".into()]);
        Ok(Some((resources, symbols)))
    }
    pub fn record_native_market(
        &mut self,
        symbol: &str,
        raw: Option<&[u8]>,
        started: u64,
        received: u64,
    ) -> bool {
        match raw.and_then(|raw| {
            exec_svc::native_market::MarketObservation::from_response(
                symbol, raw, started, received,
            )
            .ok()
        }) {
            Some(book) => {
                self.native_markets.insert(symbol.into(), book);
                true
            }
            None => {
                self.native_markets.remove(symbol);
                self.mark_fault();
                false
            }
        }
    }
    pub fn observation_cycle_complete(&mut self) -> io::Result<()> {
        let generation = self.journal.credential_metadata().map(|key| key.generation);
        let epoch = self.gate.as_ref().map(|gate| gate.runtime_epoch());
        let clean = if let (Some(ledger), Some(generation), Some(epoch)) =
            (self.limits.as_mut(), generation, epoch)
        {
            exec_svc::native_settlement::reconcile(
                ledger,
                &self.balances,
                generation,
                epoch,
                now_ms()?,
            )
            .map_err(|_| io::Error::other("native reconciliation journal failed"))?
        } else {
            false
        };
        self.native_incident = !clean;
        if !clean {
            self.disarm();
        }
        Ok(())
    }

    fn local_backup(&mut self, at: u64) -> io::Result<()> {
        let metadata = self
            .journal
            .credential_metadata()
            .cloned()
            .ok_or_else(|| io::Error::other("no credential for backup"))?;
        let cipher = Secret(self.load_ciphertext(&metadata)?);
        let id: String = random_id()?
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        let credentials = self.root.join(format!("backup-{id}-credentials.sqlite"));
        let execution = self.root.join(format!("backup-{id}-execution.sqlite"));
        let sealed = self.root.join(format!("backup-{id}-credential.sealed"));
        let credential_tip = self
            .journal
            .backup_to(&credentials)
            .map_err(|_| io::Error::other("credential backup failed"))?;
        let execution_tip = self
            .limits
            .as_mut()
            .ok_or_else(|| io::Error::other("execution journal missing"))?
            .backup_to(&execution)
            .map_err(|_| io::Error::other("execution backup failed"))?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&sealed)?;
        file.write_all(&cipher.0)?;
        file.sync_all()?;
        drop(file);
        drop(cipher);
        let manifest = self.root.join(format!("backup-{id}-receipt.json"));
        let mut receipt = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&manifest)?;
        let raw=serde_json::to_vec(&serde_json::json!({"schema":1,"made_at_ms":at,
            "credential_generation":metadata.generation,"ciphertext_digest":metadata.ciphertext_digest,
            "credentials":{"file":credentials.file_name().and_then(|name|name.to_str()),"tip":credential_tip},
            "execution":{"file":execution.file_name().and_then(|name|name.to_str()),"tip":execution_tip},
            "sealed":sealed.file_name().and_then(|name|name.to_str())})).map_err(io::Error::other)?;
        receipt.write_all(&raw)?;
        receipt.sync_all()?;
        drop(receipt);
        self.native_backup = Some(NativeBackup {
            generation: metadata.generation,
            made_at_ms: at,
            _leases: vec![
                read_lease(&credentials)?,
                read_lease(&execution)?,
                read_lease(&sealed)?,
                read_lease(&manifest)?,
            ],
        });
        Ok(())
    }

    pub fn arm_evidence(
        &self,
        policy: &ArmPolicy,
        at: u64,
        gate: &exec_svc::StopGate,
    ) -> io::Result<ArmEvidence> {
        let mut evidence = ArmEvidence::missing(at, gate.runtime_epoch());
        let generation = self.journal.credential_metadata().map(|key| key.generation);
        evidence.credential_generation = generation;
        let audits = self.journal.audit_status() == AuditStatus::Verified
            && self
                .limits
                .as_ref()
                .is_some_and(|ledger| ledger.audit_status() == AuditStatus::Verified);
        if let (Some(generation), Some(ledger)) = (generation, self.limits.as_ref()) {
            if self
                .balances
                .matches_context(generation, gate.runtime_epoch())
            {
                if let Some((_, limit)) = ledger.installation_ceiling().filter(|(_, limit)| {
                    limit.ceiling.currency == policy.quote_asset && limit.ceiling.capital_quanta > 0
                }) {
                    evidence.available = self
                        .balances
                        .available(
                            &policy.quote_asset,
                            limit.ceiling.decimals,
                            ledger.reserved("main", &policy.quote_asset),
                            at,
                            u64::from(policy.stale_data_seconds) * 1000,
                        )
                        .ok();
                }
            }
            let mut oldest = None;
            let complete =
                policy.symbols.iter().all(|symbol| {
                    let Some(book) = self.native_markets.get(symbol).filter(|book| {
                        book.is_fresh(at, u64::from(policy.stale_data_seconds) * 1000)
                    }) else {
                        return false;
                    };
                    oldest = Some(oldest.map_or(book.received_at_ms(), |old: u64| {
                        old.min(book.received_at_ms())
                    }));
                    true
                });
            if complete {
                evidence.market_received_at_ms = oldest;
            }
            if let Some(risk) = self.measured_risk(policy, generation, gate.runtime_epoch(), at) {
                evidence.loss_quote = Some(risk.loss_quote);
                evidence.open_orders = Some(risk.open_orders);
                evidence.orders_today = Some(risk.orders_today);
                evidence.reconciliation_clean = audits;
            }
            if self.owner_review.as_ref().is_some_and(|review| {
                review
                    .verify(policy, generation, gate.runtime_epoch(), at)
                    .is_ok()
            }) {
                evidence.blockers.retain(|item| {
                    !matches!(
                        item,
                        ArmBlocker::TradePermission | ArmBlocker::ProspectiveEvidence
                    )
                });
            }
            if self.native_backup.as_ref().is_some_and(|backup| {
                backup.generation == generation
                    && at >= backup.made_at_ms
                    && at - backup.made_at_ms <= 36 * 3_600_000
            }) {
                evidence
                    .blockers
                    .retain(|item| *item != ArmBlocker::RecentBackup);
            }
        }
        if audits && evidence.reconciliation_clean && !self.native_incident {
            evidence
                .blockers
                .retain(|item| *item != ArmBlocker::OpenIncident);
        }
        Ok(evidence)
    }

    pub(super) fn measured_risk(
        &self,
        policy: &ArmPolicy,
        generation: [u8; 16],
        epoch: u64,
        at: u64,
    ) -> Option<exec_svc::native_risk::NativeRisk> {
        use exec_svc::account_observation::AccountKind;
        let ledger = self.limits.as_ref()?;
        if !ledger.reconciliation_ready() {
            return None;
        }
        let fee =
            self.journal
                .account_observation(AccountKind::Fees, generation, epoch, at, 30_000)?;
        let open = self.journal.order_page_observation(
            &exec_ipc::provision::AccountResource::OpenOrders {
                page: 1,
                per_page: 100,
            },
            generation,
            epoch,
            at,
            30_000,
        )?;
        let orders = ledger.reviewed_risk_orders(generation, epoch, at)?;
        let mut highest = Exact {
            mantissa: 0,
            scale: 0,
        };
        for symbol in &policy.symbols {
            for field in ["makerFeeRate", "takerFeeRate"] {
                let rate = fee.data()["result"][symbol][field]
                    .as_str()
                    .and_then(Exact::parse)?;
                if rate.cmp_value(highest)? == std::cmp::Ordering::Greater {
                    highest = rate;
                }
            }
        }
        exec_svc::native_risk::measure(
            &orders,
            open,
            &self.native_markets,
            &policy.quote_asset,
            highest,
            at,
        )
        .ok()
    }

    pub fn safety_tick(&mut self) -> io::Result<()> {
        let Some(gate) = self.gate.clone() else {
            return Err(io::Error::other("native gate missing"));
        };
        if self.journal.audit_failed()
            || self
                .limits
                .as_ref()
                .is_some_and(|ledger| ledger.audit_failed())
        {
            self.disarm();
            return Err(io::Error::other("independent journal audit failed"));
        }
        if let Some(policy) = self.arm_controller.policy().cloned() {
            let at = now_ms()?;
            let evidence = self.arm_evidence(&policy, at, &gate)?;
            if self
                .arm_controller
                .safety_tick(&gate, &evidence, at)
                .is_err()
            {
                self.owner_review = None;
            }
        }
        Ok(())
    }

    pub fn arm(
        &mut self,
        request: &ArmRequest,
        user: &str,
        logon: &str,
        operator_user: &str,
        operator_logon: &str,
        gate: &exec_svc::StopGate,
    ) -> io::Result<ArmReply> {
        require_service_identity()?;
        let at = now_ms()?;
        let mut reply = ArmReply {
            result: ArmResult::Status,
            mode: gate.mode(),
            correlation: request.correlation,
            runtime_epoch: gate.runtime_epoch(),
            revision: gate.revision(),
            blockers: 0,
            record_digest: [0; 32],
            expires_at_ms: 0,
            policy_sha256: [0; 32],
        };
        if self.mode != exec_ipc::provision::StartupMode::Normal
            || user != operator_user
            || logon != operator_logon
        {
            reply.result = ArmResult::Blocked;
            reply.blockers = ArmBlocker::PrivilegedFault.bit();
            return Ok(reply);
        }
        match &request.command {
            ArmCommand::Status => {
                self.safety_tick()?;
            }
            ArmCommand::Disarm { runtime_epoch } => {
                if *runtime_epoch != gate.runtime_epoch() {
                    reply.result = ArmResult::Blocked;
                    reply.blockers = ArmBlocker::RuntimeChanged.bit();
                } else {
                    self.disarm();
                    reply.result = ArmResult::Disarmed;
                }
            }
            ArmCommand::Approve {
                runtime_epoch,
                revision,
                policy_sha256,
                evidence_sha256,
                policy_path,
            } => {
                let result = (|| -> Result<_, u64> {
                    let snapshot = gate
                        .approval_snapshot()
                        .map_err(|_| ArmBlocker::Stopped.bit())?;
                    if *runtime_epoch != gate.runtime_epoch() || snapshot.revision() != *revision {
                        return Err(ArmBlocker::ApprovalChanged.bit());
                    }
                    let policy = PolicyFile::open(Path::new(policy_path), *policy_sha256)
                        .map_err(|_| ArmBlocker::Policy.bit())?;
                    self.observation_policy = Some(policy.policy().clone());
                    let generation = self
                        .journal
                        .credential_metadata()
                        .map(|key| key.generation)
                        .ok_or(ArmBlocker::CredentialsMissing.bit())?;
                    let review = OwnerEvidence::open(
                        Path::new(policy_path),
                        *evidence_sha256,
                        policy.policy(),
                        generation,
                        gate.runtime_epoch(),
                        at,
                    )
                    .map_err(|_| {
                        ArmBlocker::TradePermission.bit() | ArmBlocker::ProspectiveEvidence.bit()
                    })?;
                    self.owner_review = Some(review);
                    if self.native_backup.as_ref().is_none_or(|copy| {
                        copy.generation != generation
                            || at < copy.made_at_ms
                            || at - copy.made_at_ms > 36 * 3_600_000
                    }) {
                        self.local_backup(at)
                            .map_err(|_| ArmBlocker::RecentBackup.bit())?;
                    }
                    let at = now_ms().map_err(|_| ArmBlocker::PrivilegedFault.bit())?;
                    let evidence = self
                        .arm_evidence(policy.policy(), at, gate)
                        .map_err(|_| ArmBlocker::PrivilegedFault.bit())?;
                    let _owner_lease = self
                        .owner_review
                        .as_ref()
                        .ok_or(ArmBlocker::ProspectiveEvidence.bit())?
                        .verify(policy.policy(), generation, gate.runtime_epoch(), at)
                        .map_err(|_| ArmBlocker::ProspectiveEvidence.bit())?;
                    let path = self.root.join(format!(
                        "arm-{}-{}.json",
                        gate.runtime_epoch(),
                        snapshot.revision()
                    ));
                    let owner = self
                        .owner_review
                        .as_ref()
                        .ok_or(ArmBlocker::ProspectiveEvidence.bit())?;
                    self.arm_controller
                        .approve_committed(gate, snapshot, policy, &evidence, user, at, |record| {
                            let raw = serde_json::to_vec(&serde_json::json!({"schema":1,
                            "record":record.canonical(),"digest":record.digest(),
                            "credential_generation":generation,"evidence_sha256":evidence_sha256}))
                            .map_err(io::Error::other)?;
                            let mut file =
                                OpenOptions::new().write(true).create_new(true).open(path)?;
                            file.write_all(&raw)?;
                            file.sync_all()?;
                            let committed_at_ms = now_ms()?;
                            let _evidence_lease = owner.verify(
                                &record.policy,
                                generation,
                                gate.runtime_epoch(),
                                committed_at_ms,
                            )?;
                            Ok(committed_at_ms)
                        })
                        .map_err(|error| error.blocker_mask())
                })();
                match result {
                    Ok(record) => {
                        reply.result = ArmResult::Approved;
                        reply.record_digest = record.digest();
                        reply.expires_at_ms = record.expires_at_ms;
                        reply.policy_sha256 = record.policy.policy_sha256;
                    }
                    Err(blockers) => {
                        self.disarm();
                        reply.result = ArmResult::Blocked;
                        reply.blockers = blockers;
                    }
                }
            }
        }
        if let Some(record) = self.arm_controller.record() {
            reply.record_digest = record.digest();
            reply.expires_at_ms = record.expires_at_ms;
            reply.policy_sha256 = record.policy.policy_sha256;
        }
        reply.mode = gate.mode();
        reply.revision = gate.revision();
        Ok(reply)
    }
}
