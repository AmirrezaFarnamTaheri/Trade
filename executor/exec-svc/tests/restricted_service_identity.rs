use exec_svc::{is_restricted_executor_token, TokenGroup};

const EXECUTOR_SERVICE_SID: &str = "S-1-5-80-123-456-789-111-222";

fn enabled_executor_group() -> Vec<TokenGroup> {
    vec![TokenGroup { sid: EXECUTOR_SERVICE_SID.to_string(), enabled: true }]
}

fn executor_restriction() -> Vec<String> {
    vec![EXECUTOR_SERVICE_SID.to_string()]
}

#[test]
fn requires_localservice_and_same_enabled_restricted_service_sid() {
    assert!(is_restricted_executor_token(
        "S-1-5-19", EXECUTOR_SERVICE_SID,
        &enabled_executor_group(), &executor_restriction(),
    ));
    for user_sid in ["S-1-5-18", "S-1-5-20", "S-1-5-21-1-2-3-1000", "S-1-5-19 "] {
        assert!(!is_restricted_executor_token(
            user_sid, EXECUTOR_SERVICE_SID,
            &enabled_executor_group(), &executor_restriction(),
        ));
    }
}

#[test]
fn rejects_missing_disabled_or_wrong_service_group() {
    assert!(!is_restricted_executor_token(
        "S-1-5-19", EXECUTOR_SERVICE_SID, &[], &executor_restriction(),
    ));
    assert!(!is_restricted_executor_token(
        "S-1-5-19", EXECUTOR_SERVICE_SID,
        &[TokenGroup { sid: EXECUTOR_SERVICE_SID.to_owned(), enabled: false }],
        &executor_restriction(),
    ));
    assert!(!is_restricted_executor_token(
        "S-1-5-19", EXECUTOR_SERVICE_SID,
        &[TokenGroup { sid: "S-1-5-80-222-222-222-222-222".to_owned(), enabled: true }],
        &executor_restriction(),
    ));
}

#[test]
fn rejects_missing_or_different_restricted_sid() {
    assert!(!is_restricted_executor_token(
        "S-1-5-19", EXECUTOR_SERVICE_SID, &enabled_executor_group(), &[],
    ));
    assert!(!is_restricted_executor_token(
        "S-1-5-19", EXECUTOR_SERVICE_SID, &enabled_executor_group(),
        &["S-1-1-0".to_string(), "S-1-5-80-222-222-222-222-222".to_string()],
    ));
}

#[test]
fn refuses_noncanonical_or_forged_service_sid_format() {
    for invalid in [
        "S-1-5-80", "S-1-5-80-1-2-3-4", "S-1-5-80-1-2-3-4-5-6",
        "S-1-5-80-1-2-3-4-4294967296", "S-1-5-80-1-2-3-4-x",
        "S-1-5-80-1-2-3-4-+5", "s-1-5-80-1-2-3-4-5",
    ] {
        let group = [TokenGroup { sid: invalid.to_owned(), enabled: true }];
        assert!(!is_restricted_executor_token("S-1-5-19", invalid,
            &group, &[invalid.to_owned()]), "invalid SID: {invalid}");
    }
}
