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
