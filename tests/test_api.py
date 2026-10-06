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


# ---------------------------------------------------------------- GPU / diagnostics bridge
def test_gpu_methods_wrap_controller(api, monkeypatch):
    monkeypatch.setattr(api._c, "gpu_status", lambda: {"state": "no_gpu"})
    monkeypatch.setattr(api._c.gpulibs, "start", lambda: True)
    monkeypatch.setattr(api._c.gpulibs, "cancel", lambda: False)
    assert api.gpu_status() == {"ok": True, "data": {"state": "no_gpu"}}
    assert api.download_gpu_libs() == {"ok": True, "data": True}
    assert api.cancel_gpu_download() == {"ok": True, "data": False}


def test_safe_logs_expected_at_info_and_unexpected_with_traceback(api, monkeypatch, caplog):
    def bad():
        raise ValueError("nope")

    def worse():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(api._c, "gpu_status", bad)
    with caplog.at_level("INFO", logger="app.api"):
        assert api.gpu_status() == {"ok": False, "error": "nope"}
    assert [r.levelname for r in caplog.records] == ["INFO"]
    caplog.clear()
    monkeypatch.setattr(api._c, "gpu_status", worse)
    with caplog.at_level("INFO", logger="app.api"):
        assert api.gpu_status()["ok"] is False
    assert caplog.records[-1].levelname == "ERROR" and caplog.records[-1].exc_info


def test_safe_never_logs_arguments(api, caplog):
    with caplog.at_level("INFO", logger="app.api"):
        api.cancel("summary", "../ARGSECRET")
    assert "ARGSECRET" not in caplog.text


def test_open_log_folder_opens_only_log_dir(api, monkeypatch, data_dirs):
    from app import logsetup, settings
    started = []
    monkeypatch.setattr(api_mod.os, "startfile", lambda p: started.append(p), raising=False)
    logs = settings.APP_DIR / "logs"
    monkeypatch.setattr(logsetup, "LOG_DIR", logs)
    assert api.open_log_folder() == {"ok": True, "data": True}
    assert started == [str(logs)] and logs.is_dir()


def test_open_log_folder_rejects_outside_app_dir(api, monkeypatch, data_dirs):
    from app import logsetup, settings
    started = []
    monkeypatch.setattr(api_mod.os, "startfile", lambda p: started.append(p), raising=False)
    monkeypatch.setattr(logsetup, "LOG_DIR", data_dirs / "elsewhere")
    assert api.open_log_folder()["ok"] is False
    monkeypatch.setattr(logsetup, "LOG_DIR", settings.APP_DIR)  # the app dir itself is not the log dir
    assert api.open_log_folder()["ok"] is False
    monkeypatch.setattr(logsetup, "LOG_DIR", settings.APP_DIR / ".." / "outside")
    assert api.open_log_folder()["ok"] is False
    assert started == []


def test_copy_diagnostics_no_secrets_no_transcript(api, monkeypatch):
    from app import sessions
    copied = []
    monkeypatch.setattr(api_mod.winutil, "set_clipboard_text", lambda t: copied.append(t) or True)
    monkeypatch.setattr(api._c, "gpu_status", lambda: {"state": "no_gpu"})
    api._c.s.anthropic_key = "sk-ant-api03-" + "Qq1w2E3r" * 4
    api._c.s.openai_key = "sk-OPENAIFAKEKEY1234567890"
    n = api._c.create_note()
    sessions.load(sessions.SESSIONS_DIR / n["id"]).write("transcript.txt", "TOP SECRET MEETING WORDS")
    res = api.copy_diagnostics()
    assert res["ok"] and res["data"]["copied"] is True and res["data"]["chars"] == len(copied[0])
    for bad in ("Qq1w2E3r", "OPENAIFAKEKEY", "TOP SECRET MEETING"):
        assert bad not in copied[0]


def test_copy_diagnostics_reports_failure(api, monkeypatch):
    monkeypatch.setattr(api_mod.winutil, "set_clipboard_text", lambda t: False)
    monkeypatch.setattr(api._c, "gpu_status", lambda: {})
    assert api.copy_diagnostics()["data"]["copied"] is False


def test_restart_app_refused_while_recording(api, monkeypatch):
    timers = []
    monkeypatch.setattr(api_mod.threading, "Timer", lambda *a: timers.append(a))
    api._window = object()
    api._c.recorder = object()
    assert api.restart_app()["ok"] is False
    assert api._restart_requested is False and not timers
    api._c.recorder = None
    api._c._pending["n"] = 1
    assert api.restart_app()["ok"] is False
    assert not timers


def test_restart_app_sets_flag_and_closes_window(api, monkeypatch):
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
    assert api.restart_app() == {"ok": True, "data": True}
    assert api._restart_requested is True and api._c.restart_requested is True
    assert fired[0][0] == 0.3 and fired[0][1] == api._window.destroy and fired[1] == "started"
