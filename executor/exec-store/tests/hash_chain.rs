use exec_store::{hash_event, verify_chain};

#[test]
fn canonical_genesis_event_uses_exact_stored_bytes() {
    let event = include_bytes!("../../../contracts/v1/fixtures/genesis-event.json");
    let hash = hash_event(&[0; 32], event);
    let actual = hash.iter().map(|byte| format!("{byte:02x}")).collect::<String>();
    assert_eq!(actual, "d180d43ebb90c9d8f4d9d1ea683f9baa019a328f619b94ef0011968ea6dcd6db");
}

#[test]
fn event_byte_change_changes_digest() {
    let prev = [0; 32];
    let a = hash_event(&prev, br#"{"sequence":1}"#);
    let b = hash_event(&prev, br#"{"sequence":1} "#);
    assert_ne!(a, b);
    assert_ne!(a, hash_event(&[1; 32], br#"{"sequence":1}"#));
}

#[test]
fn verifies_complete_ordered_chain_and_rejects_tampering() {
    let events: [&[u8]; 2] = [b"intent", b"observation"];
    let first = hash_event(&[0; 32], events[0]);
    let head = hash_event(&first, events[1]);
    assert!(verify_chain([0; 32], events, head));
    assert!(!verify_chain([0; 32], [b"intent".as_slice(), b"changed".as_slice()], head));
    assert!(!verify_chain([0; 32], [b"observation".as_slice(), b"intent".as_slice()], head));
}
