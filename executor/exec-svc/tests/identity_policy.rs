use exec_svc::is_local_service_sid;

#[test]
fn only_windows_localservice_is_a_candidate_for_the_readonly_host() {
    assert!(is_local_service_sid("S-1-5-19"));
    for sid in [
        "S-1-5-18",           // LocalSystem (too privileged)
        "S-1-5-20",           // NetworkService
        "S-1-5-32-544",       // Administrators
        "S-1-5-21-1-2-3-1001", // Interactive user
        "S-1-5-80-0",         // All services (not a user)
        "s-1-5-19", "", "S-1-5-19 ",
    ] {
        assert!(!is_local_service_sid(sid), "unexpectedly permitted {sid}");
    }
}
