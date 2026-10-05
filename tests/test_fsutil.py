import os

import pytest

from app import fsutil


def test_atomic_write_leaves_no_temp(tmp_path):
    p = tmp_path / "a.txt"
    fsutil.atomic_write_text(p, "hello ไทย")
    fsutil.atomic_write_text(p, "second")
    assert p.read_text(encoding="utf-8") == "second"
    assert [x.name for x in tmp_path.iterdir()] == ["a.txt"]


def test_retries_permission_error(tmp_path, monkeypatch):
    real = os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("busy")
        return real(a, b)

    monkeypatch.setattr(fsutil.os, "replace", flaky)
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    p = tmp_path / "b.txt"
    fsutil.atomic_write_text(p, "x")
    assert calls["n"] == 3 and p.read_text() == "x"
    assert [x.name for x in tmp_path.iterdir()] == ["b.txt"]


def test_gives_up_and_cleans_temp(tmp_path, monkeypatch):
    def always(a, b):
        raise PermissionError("busy")

    monkeypatch.setattr(fsutil.os, "replace", always)
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        fsutil.atomic_write_text(tmp_path / "c.txt", "x")
    assert list(tmp_path.iterdir()) == []
