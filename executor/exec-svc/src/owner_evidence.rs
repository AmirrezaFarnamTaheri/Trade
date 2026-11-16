//! Hash-bound elevated owner review, separate from venue-issued permission or profitability proof.
use exec_core::arming::ArmPolicy;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};

pub const PROSPECTIVE_CHECKPOINT_MS: u64 = 1_802_044_800_000; // 2027-02-08T00:00:00Z
const MAX_EVIDENCE_BYTES: u64 = 16_384;
const MAX_ARTIFACT_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Claims {
    schema: u8,
    policy_sha256: String,
    credential_generation: String,
    runtime_epoch: u64,
    reviewed_at_ms: u64,
    valid_until_ms: u64,
    trade_permission: String,
    prospective: Prospective,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Prospective {
    checkpoint: String,
    decision: String,
    artifact_path: PathBuf,
    artifact_sha256: String,
}

fn invalid() -> io::Error {
    io::Error::other("owner review evidence invalid, expired or changed")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn read_local(path: &Path, limit: u64) -> io::Result<(File, Vec<u8>)> {
    if !path.is_absolute()
        || path.components().any(|part| part == Component::ParentDir)
        || path.to_string_lossy().starts_with("\\\\")
    {
        return Err(invalid());
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > limit {
        return Err(invalid());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::{MetadataExt, OpenOptionsExt};
        use windows_sys::Win32::Storage::FileSystem::{
            FILE_ATTRIBUTE_REPARSE_POINT, FILE_FLAG_OPEN_REPARSE_POINT, FILE_SHARE_READ,
        };
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(invalid());
        }
        options
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let mut file = options.open(path)?;
    if !file.metadata()?.is_file() {
        return Err(invalid());
    }
    let mut raw = Vec::new();
    (&mut file).take(limit + 1).read_to_end(&mut raw)?;
    if raw.is_empty() || raw.len() as u64 > limit {
        return Err(invalid());
    }
    Ok((file, raw))
}

#[must_use = "hold the owner evidence and artifact leases through approval or the venue effect"]
pub struct EvidenceLease {
    _evidence: File,
    _artifact: File,
}

pub struct OwnerEvidence {
    path: PathBuf,
    expected_sha256: [u8; 32],
}

impl OwnerEvidence {
    /// The expected hash must come from the authenticated elevated approval request.
    pub fn open(
        policy_path: &Path,
        expected_sha256: [u8; 32],
        policy: &ArmPolicy,
        generation: [u8; 16],
        runtime_epoch: u64,
        now_ms: u64,
    ) -> io::Result<Self> {
        if expected_sha256 == [0; 32]
            || !policy_path
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.eq_ignore_ascii_case("arm-policy.json"))
        {
            return Err(invalid());
        }
        let review = Self {
            path: policy_path.with_file_name("arm-evidence.json"),
            expected_sha256,
        };
        let _lease = review.verify(policy, generation, runtime_epoch, now_ms)?;
        Ok(review)
    }

    pub fn verify(
        &self,
        policy: &ArmPolicy,
        generation: [u8; 16],
        runtime_epoch: u64,
        now_ms: u64,
    ) -> io::Result<EvidenceLease> {
        let (evidence, raw) = read_local(&self.path, MAX_EVIDENCE_BYTES)?;
        if <[u8; 32]>::from(Sha256::digest(&raw)) != self.expected_sha256 {
            return Err(invalid());
        }
        let claims: Claims = serde_json::from_slice(&raw).map_err(|_| invalid())?;
        let expires = u64::from(policy.expires_days)
            .checked_mul(86_400_000)
            .and_then(|span| claims.reviewed_at_ms.checked_add(span))
            .ok_or_else(invalid)?;
        if claims.schema != 1
            || generation == [0; 16]
            || runtime_epoch == 0
            || claims.policy_sha256 != hex(&policy.policy_sha256)
            || claims.credential_generation != hex(&generation)
            || claims.runtime_epoch != runtime_epoch
            || claims.trade_permission != "owner_reviewed_trade_no_withdraw"
            || claims.prospective.checkpoint != "2027-02-08"
            || claims.prospective.decision != "proceed_with_bounded_probe"
            || claims.reviewed_at_ms < PROSPECTIVE_CHECKPOINT_MS
            || now_ms < PROSPECTIVE_CHECKPOINT_MS
            || claims.reviewed_at_ms > now_ms
            || claims.valid_until_ms <= now_ms
            || claims.valid_until_ms > expires
        {
            return Err(invalid());
        }
        let (artifact, raw) = read_local(&claims.prospective.artifact_path, MAX_ARTIFACT_BYTES)?;
        if claims.prospective.artifact_sha256 != hex(&Sha256::digest(raw)) {
            return Err(invalid());
        }
        Ok(EvidenceLease {
            _evidence: evidence,
            _artifact: artifact,
        })
    }
}
