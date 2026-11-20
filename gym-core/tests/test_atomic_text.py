import pytest

from gym.adapters import atomic_text


def test_failed_publish_preserves_previous_receipt(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    path.write_text("old", encoding="utf-8")

    def fail(staged, destination):
        assert staged.read_text(encoding="utf-8") == "new"
        assert destination.read_text(encoding="utf-8") == "old"
        raise OSError("publish failed")

    with monkeypatch.context() as patch:
        patch.setattr(atomic_text.os, "replace", fail)
        with pytest.raises(OSError, match="publish failed"):
            atomic_text.write_text(path, "new")
    assert list(tmp_path.iterdir()) == [path]
    assert path.read_text(encoding="utf-8") == "old"
    atomic_text.write_text(path, "new")
    assert path.read_text(encoding="utf-8") == "new"
