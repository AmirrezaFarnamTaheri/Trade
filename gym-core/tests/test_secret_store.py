import os

import pytest

from gym.adapters import secret_store

pytestmark = pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")


def test_dpapi_round_trip_never_stores_plaintext(tmp_path):
    key = "12345|abcdefghijABCDEFGHIJ0123456789"
    path = secret_store.save("read", key, tmp_path)
    assert key.encode() not in path.read_bytes()
    assert secret_store.load("read", tmp_path) == key
    assert secret_store.masked(key) == "12345|…6789"


def test_rejects_bad_role_garbage_and_missing(tmp_path):
    with pytest.raises(ValueError):
        secret_store.save("withdraw", "1|abcdefghijABCDEFGHIJ0123", tmp_path)
    with pytest.raises(ValueError):
        secret_store.save("read", "not a key", tmp_path)
    with pytest.raises(ValueError, match="no trade key"):
        secret_store.load("trade", tmp_path)


def test_blobs_are_purpose_bound_and_legacy_blobs_migrate(tmp_path):
    key = "12345|abcdefghijABCDEFGHIJ0123456789"
    read = secret_store.save("read", key, tmp_path)
    # A read-key blob renamed into the trade slot does not open: entropy binds it to its purpose.
    trade = tmp_path / "wallex-trade.dpapi"
    trade.write_bytes(read.read_bytes())
    with pytest.raises(OSError):
        secret_store.load("trade", tmp_path)
    with pytest.raises(OSError):
        secret_store._crypt(read.read_bytes(), False)  # no entropy: refused
    # A blob sealed before entropy existed still loads, and is re-sealed with entropy on first read.
    read.write_bytes(secret_store._crypt(key.encode(), True))
    assert secret_store.load("read", tmp_path) == key
    assert secret_store._crypt(read.read_bytes(), False, "wallex-read").decode() == key


def test_linked_key_paths_are_refused(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "keys"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation needs Developer Mode or admin rights")
    with pytest.raises(ValueError, match="linked"):
        secret_store.save("read", "12345|abcdefghijABCDEFGHIJ0123456789", link)


def test_key_file_gets_a_protected_single_user_dacl_and_a_foreign_owner_is_refused(tmp_path, monkeypatch):
    import subprocess

    path = secret_store.save("read", "123|" + "a" * 32, tmp_path)
    acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout
    entries = [line.split(":", 1)[-1].strip() for line in acl.splitlines()[:-2] if line.strip()]
    assert len([e for e in entries if "(F)" in e or "(M)" in e or "(R" in e]) == 1, acl  # one ACE: this user
    assert "(I)" not in acl  # nothing inherited from the folder
    assert secret_store.load("read", tmp_path) == "123|" + "a" * 32
    monkeypatch.setattr(secret_store, "_owner", lambda _path: "S-1-5-18")  # e.g. planted by SYSTEM
    with pytest.raises(ValueError, match="owned by another account"):
        secret_store.load("read", tmp_path)
