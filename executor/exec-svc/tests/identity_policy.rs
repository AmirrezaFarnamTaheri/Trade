use exec_svc::is_local_service_sid;

#[test]
fn only_windows_localservice_is_a_candidate_for_the_readonly_host() {
    assert!(is_local_service_sid("S-1-5-19"));
    for sid in [
        "S-1-5-18",            // LocalSystem (too privileged)
        "S-1-5-20",            // NetworkService
        "S-1-5-32-544",        // Administrators
        "S-1-5-21-1-2-3-1001", // Interactive user
        "S-1-5-80-0",          // All services (not a user)
        "s-1-5-19",
        "",
        "S-1-5-19 ",
    ] {
        assert!(!is_local_service_sid(sid), "unexpectedly permitted {sid}");
    }
}

#[test]
fn an_incomplete_code_publication_cannot_start_the_service() {
    let root = std::env::temp_dir().join(format!(
        "gym-publication-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&root).unwrap();
    assert!(exec_svc::require_complete_publication(&root).is_ok());
    let marker = root.join("update.pending");
    std::fs::write(&marker, b"incomplete").unwrap();
    assert!(exec_svc::require_complete_publication(&root).is_err());
    std::fs::remove_file(&marker).unwrap();
    std::fs::create_dir(&marker).unwrap();
    assert!(exec_svc::require_complete_publication(&root).is_err());
    std::fs::remove_dir(&marker).unwrap();
    assert!(exec_svc::require_complete_publication(&root).is_ok());
    std::fs::remove_dir(&root).unwrap();
    assert!(exec_svc::require_complete_publication(&root).is_err());
}
