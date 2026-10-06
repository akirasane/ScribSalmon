import sys

from app import winutil


def test_clipboard_skipped_when_not_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert winutil.set_clipboard_text("hello") is False


def test_clipboard_failure_returns_false(monkeypatch):
    # force the ctypes path to blow up: must be swallowed into False
    monkeypatch.setattr(sys, "platform", "win32")
    import ctypes

    class Boom:
        def __getattr__(self, name):
            raise OSError("no")

    monkeypatch.setattr(ctypes, "windll", Boom(), raising=False)
    assert winutil.set_clipboard_text("x") is False
