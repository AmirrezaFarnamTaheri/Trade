//! Negative test only: an ordinary Windows CI runner must not impersonate the
//! restricted Executor service just by invoking the same Rust functions.
#[cfg(windows)]
#[test]
fn ordinary_windows_runner_never_passes_restricted_service_identity_check() {
    use exec_svc::windows_identity::{is_restricted_executor_service, process_user_sid};
    let user = process_user_sid().expect("current Windows token must be queryable");
    if user != "S-1-5-19" {
        assert!(!is_restricted_executor_service());
    }
}
