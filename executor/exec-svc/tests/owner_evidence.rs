use exec_core::arming::ArmPolicy;
use exec_core::kernel::Exact;
use exec_svc::owner_evidence::{OwnerEvidence, PROSPECTIVE_CHECKPOINT_MS};
use sha2::{Digest, Sha256};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
fn policy() -> ArmPolicy {
    ArmPolicy {
        policy_sha256: [8; 32],
        venue: "wallex".into(),
        quote_asset: "USDT".into(),
        symbols: vec!["BTCUSDT".into()],
        loss_cap_quote: Exact::parse("50").unwrap(),
        max_order_quote: Exact::parse("10").unwrap(),
        max_orders_per_day: 10,
        kill_max_loss_quote: Exact::parse("20").unwrap(),
        stale_data_seconds: 120,
        max_open_orders: 2,
        expires_days: 7,
    }
}
fn fixture() -> (PathBuf, serde_json::Value) {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let dir = std::env::temp_dir().join(format!(
        "gym-owner-evidence-{}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&dir).unwrap();
    let artifact = dir.join("prospective-journal.json");
    std::fs::write(&artifact, b"synthetic-test-only").unwrap();
    let claims = serde_json::json!({"schema":1,"policy_sha256":hex(&[8;32]),
        "credential_generation":hex(&[3;16]), "runtime_epoch":10,
        "reviewed_at_ms": PROSPECTIVE_CHECKPOINT_MS, "valid_until_ms":PROSPECTIVE_CHECKPOINT_MS+86_400_000,
        "trade_permission":"owner_reviewed_trade_no_withdraw",
        "prospective":{"checkpoint":"2027-02-08","decision":"proceed_with_bounded_probe",
            "artifact_path":artifact,"artifact_sha256":hex(&Sha256::digest(b"synthetic-test-only"))}});
    (dir.join("arm-policy.json"), claims)
}
fn write(policy: &std::path::Path, claims: &serde_json::Value) -> [u8; 32] {
    let raw = serde_json::to_vec(claims).unwrap();
    std::fs::write(policy.with_file_name("arm-evidence.json"), &raw).unwrap();
    Sha256::digest(raw).into()
}

#[test]
fn exact_owner_review_is_bound_to_artifact_policy_credential_epoch_and_time() {
    let (path, claims) = fixture();
    let hash = write(&path, &claims);
    let review = OwnerEvidence::open(
        &path,
        hash,
        &policy(),
        [3; 16],
        10,
        PROSPECTIVE_CHECKPOINT_MS + 1,
    )
    .unwrap();
    let _lease = review
        .verify(&policy(), [3; 16], 10, PROSPECTIVE_CHECKPOINT_MS + 1)
        .unwrap();
    for (generation, epoch, time) in [
        ([4; 16], 10, PROSPECTIVE_CHECKPOINT_MS + 1),
        ([3; 16], 11, PROSPECTIVE_CHECKPOINT_MS + 1),
        ([3; 16], 10, PROSPECTIVE_CHECKPOINT_MS - 1),
        ([3; 16], 10, PROSPECTIVE_CHECKPOINT_MS + 86_400_001),
    ] {
        assert!(review.verify(&policy(), generation, epoch, time).is_err());
    }
    let mut changed = policy();
    changed.policy_sha256 = [9; 32];
    assert!(review
        .verify(&changed, [3; 16], 10, PROSPECTIVE_CHECKPOINT_MS + 1)
        .is_err());
}

#[test]
fn later_evidence_or_artifact_edits_revoke_the_review() {
    for edit_evidence in [false, true] {
        let (path, mut claims) = fixture();
        let hash = write(&path, &claims);
        let review = OwnerEvidence::open(
            &path,
            hash,
            &policy(),
            [3; 16],
            10,
            PROSPECTIVE_CHECKPOINT_MS + 1,
        )
        .unwrap();
        if edit_evidence {
            claims["reviewed_at_ms"] = serde_json::json!(PROSPECTIVE_CHECKPOINT_MS + 1);
            write(&path, &claims);
        } else {
            std::fs::write(
                claims["prospective"]["artifact_path"].as_str().unwrap(),
                b"edited",
            )
            .unwrap();
        }
        assert!(review
            .verify(&policy(), [3; 16], 10, PROSPECTIVE_CHECKPOINT_MS + 2)
            .is_err());
    }
}

#[test]
fn booleans_unknown_claims_unregistered_dates_and_future_review_times_are_refused() {
    for (field, value) in [
        ("trade_permission", serde_json::json!(true)),
        ("trade_permission", serde_json::json!("venue_verified")),
        ("unknown", serde_json::json!(true)),
        (
            "reviewed_at_ms",
            serde_json::json!(PROSPECTIVE_CHECKPOINT_MS + 2),
        ),
        (
            "valid_until_ms",
            serde_json::json!(PROSPECTIVE_CHECKPOINT_MS + 8 * 86_400_000),
        ),
    ] {
        let (path, mut claims) = fixture();
        claims[field] = value;
        let hash = write(&path, &claims);
        assert!(OwnerEvidence::open(
            &path,
            hash,
            &policy(),
            [3; 16],
            10,
            PROSPECTIVE_CHECKPOINT_MS + 1
        )
        .is_err());
    }
    let (path, mut claims) = fixture();
    claims["prospective"]["checkpoint"] = serde_json::json!("2026-11-16");
    let hash = write(&path, &claims);
    assert!(OwnerEvidence::open(
        &path,
        hash,
        &policy(),
        [3; 16],
        10,
        PROSPECTIVE_CHECKPOINT_MS + 1
    )
    .is_err());
}

#[test]
fn hash_mismatch_and_remote_or_parent_paths_are_refused() {
    let (path, mut claims) = fixture();
    let hash = write(&path, &claims);
    assert!(OwnerEvidence::open(
        &path,
        [0; 32],
        &policy(),
        [3; 16],
        10,
        PROSPECTIVE_CHECKPOINT_MS + 1
    )
    .is_err());
    assert!(OwnerEvidence::open(
        &path,
        [9; 32],
        &policy(),
        [3; 16],
        10,
        PROSPECTIVE_CHECKPOINT_MS + 1
    )
    .is_err());
    for artifact in ["../journal.json", r"\\server\share\journal.json"] {
        claims["prospective"]["artifact_path"] = serde_json::json!(artifact);
        let changed_hash = write(&path, &claims);
        assert!(OwnerEvidence::open(
            &path,
            changed_hash,
            &policy(),
            [3; 16],
            10,
            PROSPECTIVE_CHECKPOINT_MS + 1
        )
        .is_err());
    }
    assert_ne!(hash, [0; 32]);
}
