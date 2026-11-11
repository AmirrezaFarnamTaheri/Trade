//! Provisioned SID files are trusted only when SYSTEM, Administrators or TrustedInstaller own and solely write them.
use exec_svc::config_trust::{check, Ace, Untrusted, ADMINISTRATORS, SYSTEM, TRUSTED_INSTALLER};

fn ace(kind: u8, flags: u8, mask: u32, sid: &str) -> Ace {
    Ace {
        kind,
        flags,
        mask,
        sid: sid.into(),
    }
}
const READ: u32 = 0x0012_0089;
const FULL: u32 = 0x001F_01FF;
const USERS: &str = "S-1-5-32-545";
const OPERATOR: &str = "S-1-5-21-1-2-3-1001";

#[test]
fn the_installer_shape_is_trusted() {
    let dacl = [
        ace(0, 0, FULL, SYSTEM),
        ace(0, 0, FULL, ADMINISTRATORS),
        ace(0, 0, READ, USERS),
        ace(0, 0, FULL, TRUSTED_INSTALLER),
        ace(0, 0x08 | 0x01, FULL, "S-1-3-0"),
    ];
    assert_eq!(check(ADMINISTRATORS, Some(&dacl)), Ok(()));
    assert_eq!(check(TRUSTED_INSTALLER, Some(&dacl)), Ok(()));
}

#[test]
fn a_user_owner_a_user_writer_or_a_null_dacl_is_refused() {
    let readable = [ace(0, 0, FULL, SYSTEM), ace(0, 0, READ, USERS)];
    assert_eq!(
        check(OPERATOR, Some(&readable)),
        Err(Untrusted::Owner(OPERATOR.into()))
    );
    for mask in [
        0x0002,
        0x0004,
        0x0001_0000,
        0x0004_0000,
        0x0008_0000,
        0x1000_0000,
        0x4000_0000,
    ] {
        let dacl = [ace(0, 0, FULL, SYSTEM), ace(0, 0, READ | mask, USERS)];
        assert_eq!(
            check(SYSTEM, Some(&dacl)),
            Err(Untrusted::Writer(USERS.into())),
            "mask {mask:#x}"
        );
    }
    assert_eq!(check(SYSTEM, None), Err(Untrusted::NullDacl));
    assert_eq!(
        check(SYSTEM, Some(&[ace(5, 0, READ, USERS)])),
        Err(Untrusted::UnknownAce(5))
    );
    // A deny entry never grants anything.
    assert_eq!(check(SYSTEM, Some(&[ace(1, 0, FULL, USERS)])), Ok(()));
}

#[cfg(windows)]
#[test]
fn a_file_the_current_user_created_is_refused() {
    let path = std::env::temp_dir().join(format!("gym-sid-{}.sid", std::process::id()));
    std::fs::write(&path, "S-1-5-5-0-12345").unwrap();
    let error = exec_svc::windows_identity::verify_trusted_config_file(&path).unwrap_err();
    std::fs::remove_file(&path).unwrap();
    assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied);
    assert!(
        error.to_string().contains("untrusted configuration file"),
        "{error}"
    );
}
