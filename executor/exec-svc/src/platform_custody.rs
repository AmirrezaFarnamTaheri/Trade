//! Cross-platform custody & disaster-recovery abstraction traits (ARCH-03 / F-06).
//!
//! Defines platform-agnostic interfaces for IPC transport, secret sealing, venue HTTP
//! enforcement, and encrypted off-host ledger backup verification so `exec-svc` can
//! port cleanly from Windows (Named Pipes / DPAPI / WinHTTP) to hardened Linux
//! (Unix Domain Sockets + `SO_PEERCRED` / KMS-HSM / rustls) without altering custody
//! invariants. `TradingGYMExecutor` remains `DISARMED` ($0 funded budget) by default.
use sha2::{Digest, Sha256};

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let mut out = String::with_capacity(64);
    for b in hasher.finalize() {
        use std::fmt::Write;
        let _ = write!(&mut out, "{b:02x}");
    }
    out
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CustodyPlatform {
    WindowsScmDpapi,
    LinuxSystemdUds,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PeerIdentity {
    pub platform: CustodyPlatform,
    pub principal_id: String,
    pub pid: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CustodyError {
    UnauthorizedPeer,
    ForbiddenVenuePath(String),
    VaultFailure(String),
    BackupDigestMismatch,
    Disarmed,
}

/// Platform-neutral IPC peer authenticator (Windows Named Pipe token vs Linux `SO_PEERCRED`).
pub trait IpcPeerAuthenticator {
    fn authenticate_peer(&self, peer: &PeerIdentity) -> Result<(), CustodyError>;
}

/// Platform-neutral secret sealing boundary (Windows DPAPI vs Linux KMS/HSM/systemd-creds).
pub trait SecretVaultBackend {
    fn seal(&self, purpose: &str, plaintext: &[u8]) -> Result<Vec<u8>, CustodyError>;
    fn unseal(&self, purpose: &str, ciphertext: &[u8]) -> Result<Vec<u8>, CustodyError>;
}

/// Platform-neutral venue HTTP path guard (shared across WinHTTP and future Linux TLS clients).
pub fn enforce_venue_path_policy(path: &str) -> Result<(), CustodyError> {
    let lower = path.to_ascii_lowercase();
    if lower.contains("/withdraw")
        || lower.contains("/address-book")
        || lower.contains("/wallet/transfer")
    {
        return Err(CustodyError::ForbiddenVenuePath(path.to_string()));
    }
    Ok(())
}

/// Manifest describing an encrypted off-host ledger backup (expanding the B3 pipeline).
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct EncryptedBackupManifest {
    pub schema_version: u32,
    pub ledger_tip_sequence: u64,
    pub ledger_tip_hash_hex: String,
    pub ciphertext_sha256_hex: String,
    pub ciphertext_bytes: u64,
    pub created_at_ms: u64,
}

impl EncryptedBackupManifest {
    pub fn from_ciphertext(
        ledger_tip_sequence: u64,
        ledger_tip_hash_hex: String,
        ciphertext: &[u8],
        created_at_ms: u64,
    ) -> Self {
        Self {
            schema_version: 1,
            ledger_tip_sequence,
            ledger_tip_hash_hex,
            ciphertext_sha256_hex: sha256_hex(ciphertext),
            ciphertext_bytes: ciphertext.len() as u64,
            created_at_ms,
        }
    }

    pub fn verify_ciphertext(&self, ciphertext: &[u8]) -> Result<(), CustodyError> {
        if ciphertext.len() as u64 != self.ciphertext_bytes {
            return Err(CustodyError::BackupDigestMismatch);
        }
        if sha256_hex(ciphertext) != self.ciphertext_sha256_hex {
            return Err(CustodyError::BackupDigestMismatch);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn venue_path_policy_blocks_withdrawals_and_allows_spot_reads() {
        assert!(enforce_venue_path_policy("/v3/orderbook/BTCUSDT").is_ok());
        assert!(enforce_venue_path_policy("/v1/account/balances").is_ok());
        assert!(matches!(
            enforce_venue_path_policy("/v1/account/withdraw"),
            Err(CustodyError::ForbiddenVenuePath(_))
        ));
        assert!(matches!(
            enforce_venue_path_policy("/v1/address-book/create"),
            Err(CustodyError::ForbiddenVenuePath(_))
        ));
        assert!(matches!(
            enforce_venue_path_policy("/v2/wallet/transfer"),
            Err(CustodyError::ForbiddenVenuePath(_))
        ));
    }

    #[test]
    fn encrypted_backup_manifest_detects_tampering_and_truncation() {
        let ciphertext = b"age-encrypted-synthetic-ledger-payload";
        let manifest = EncryptedBackupManifest::from_ciphertext(
            42,
            "a".repeat(64),
            ciphertext,
            1_700_000_000_000,
        );
        assert!(manifest.verify_ciphertext(ciphertext).is_ok());
        assert_eq!(
            manifest.verify_ciphertext(b"age-encrypted-synthetic-ledger-payloaX"),
            Err(CustodyError::BackupDigestMismatch)
        );
        assert_eq!(
            manifest.verify_ciphertext(b"short"),
            Err(CustodyError::BackupDigestMismatch)
        );
    }
}
