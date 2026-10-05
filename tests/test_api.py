import pytest

from app import api as api_mod
from app.api import Api, safe_filename


@pytest.mark.parametrize("title,expected", [
    ("Meeting 2026-10-05 16:50", "Meeting 2026-10-05 16-50"),
    ('a<b>c:d"e/f\\g|h?i*j', "a-b-c-d-e-f-g-h-i-j"),
    ("tab\there\nnl", "tab-here-nl"),
    ("trailing dots...", "trailing dots"),
    ("trailing space   ", "trailing space"),
    ("CON", "_CON"),
    ("nul.txt", "_nul.txt"),
    ("com1", "_com1"),
    ("LPT9", "_LPT9"),
    ("console", "console"),
    ("", "note"),
    ("   ", "note"),
    ("...", "note"),
    ("x" * 300, "x" * 120),
    ("สรุปประชุม", "สรุปประชุม"),
])
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_safe_filename_non_string():
    assert safe_filename(None) == "note"


@pytest.fixture
def api(data_dirs, monkeypatch):
    opened = []
    monkeypatch.setattr(api_mod.webbrowser, "open", lambda url, new=0: opened.append(url))
    a = Api()
    a.opened = opened
    return a


def test_open_external_accepts_http(api):
    assert api.open_external("http://example.com/x")["ok"] is True
    assert api.open_external("https://example.com/x?y=1")["ok"] is True
    assert len(api.opened) == 2


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "file:///C:/Windows/system32/calc.exe", "ftp://example.com/x",
    "http://", "example.com", "", None, 5, "https://x.com/" + "a" * 3000,
])
def test_open_external_rejects_others(api, url):
    res = api.open_external(url)
    assert res["ok"] is False
    assert api.opened == []


def test_cancel_is_validated_and_safe(api):
    assert api.cancel("nope", "abc")["ok"] is False
    assert api.cancel("summary", "../x")["ok"] is False
    assert api.cancel("summary", "valid-id") == {"ok": True, "data": False}


def test_install_update_not_ok_while_recording(api):
    api._c.recorder = object()
    res = api.install_update()
    assert res["ok"] is False
    assert api._c.updater.quitting is False
    api._c.recorder = None


def test_install_update_destroys_window_on_success(api, monkeypatch):
    fired = []

    class FakeTimer:
        def __init__(self, delay, fn):
            fired.append((delay, fn))

        def start(self):
            fired.append("started")

    class Win:
        def destroy(self):
            pass

    monkeypatch.setattr(api_mod.threading, "Timer", FakeTimer)
    api._window = Win()
    monkeypatch.setattr(api._c.updater, "install", lambda: True)
    assert api.install_update() == {"ok": True, "data": True}
    assert fired[0][0] == 0.3 and fired[0][1] == api._window.destroy and fired[1] == "started"


def test_update_methods_validate_and_wrap(api, monkeypatch):
    monkeypatch.setattr(api._c.updater, "check", lambda force: {"force": force})
    assert api.check_for_updates() == {"ok": True, "data": {"force": False}}
    assert api.check_for_updates(True)["data"] == {"force": True}
    assert api.check_for_updates("yes")["data"] == {"force": False}
    assert api.skip_update(5)["ok"] is False
