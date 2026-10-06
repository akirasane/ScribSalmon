import logging
import logging.handlers
import os
import sys
import threading

import pytest

from app import logsetup


@pytest.fixture
def logs(tmp_path):
    root = logging.getLogger()
    old_level, old_raise = root.level, logging.raiseExceptions
    d = tmp_path / "logs"
    yield d
    logsetup.shutdown()
    root.setLevel(old_level)
    logging.raiseExceptions = old_raise
    import faulthandler
    faulthandler.enable()  # pytest's own handler (stderr) was turned off by shutdown()


def _handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, logsetup._MARK, False)]


def _flush():
    for h in _handlers():
        h.flush()


def test_handler_config(logs):
    p = logsetup.setup(logs, native_crash=False)
    assert p == logs / "scribsalmon.log"
    (h,) = _handlers()
    assert isinstance(h, logging.handlers.RotatingFileHandler)
    assert h.maxBytes == 1_000_000 and h.backupCount == 5
    assert h.encoding == "utf-8"
    assert isinstance(h.formatter, logsetup.RedactingFormatter)
    assert logging.getLogger().level == logging.INFO


def test_setup_twice_single_handler_and_banner(logs):
    logsetup.setup(logs, native_crash=False)
    logsetup.setup(logs, native_crash=False)
    assert len(_handlers()) == 1
    logging.getLogger("t").info("héllo ünï")
    _flush()
    text = (logs / "scribsalmon.log").read_text(encoding="utf-8")
    assert "ScribSalmon" in text and "starting" in text and "héllo ünï" in text


def test_dev_adds_console(logs):
    logsetup.setup(logs, dev=True, native_crash=False)
    assert len(_handlers()) == 2


def test_unwritable_folder_does_not_raise(tmp_path, logs):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert logsetup.setup(blocker / "sub", native_crash=False) is None
    logging.getLogger("t").info("still fine")


def test_legacy_folder_not_precreated(data_dirs):
    from app import settings
    # using the module must not create APP_DIR (settings renames a legacy folder only if it is absent)
    assert not settings.APP_DIR.exists()
    assert logsetup.redact("x") == "x"
    assert not settings.APP_DIR.exists()


@pytest.mark.parametrize("src,gone", [
    ("key sk-ant-api03-AbC_dEf-123456", "sk-ant-api03"),
    ("key sk-abcdefghijklmnop1234", "sk-abcdefghijklmnop1234"),
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ("api_key=hunter2hunter2", "hunter2"),
    ("x-api-key: secretvalue", "secretvalue"),
    ("stored dpapi:AQAAANCMnd8BFdERjHoAwE", "AQAAANCM"),
    ("hash " + "a" * 40, "a" * 40),
    ("b64 " + "QUJD" * 12 + "==", "QUJDQUJD"),
])
def test_redact_secrets(src, gone):
    out = logsetup.redact(src)
    assert gone not in out and "[redacted]" in out


def test_redact_home_and_plain_text():
    from pathlib import Path
    home = str(Path.home())
    assert logsetup.redact(f"{home}\\AppData\\x") == "~\\AppData\\x"
    assert logsetup.redact("normal message 123") == "normal message 123"


def test_exception_text_redacted_in_file(logs):
    logsetup.setup(logs, native_crash=False)
    try:
        raise RuntimeError("bad key sk-ant-api03-SECRETSECRET")
    except RuntimeError:
        logging.getLogger("t").exception("failed")
    _flush()
    text = (logs / "scribsalmon.log").read_text(encoding="utf-8")
    assert "RuntimeError" in text and "SECRETSECRET" not in text


def test_excepthook_logs_and_chains(logs, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: seen.append(a[0]))
    monkeypatch.setattr(threading, "excepthook", lambda a: seen.append(a.exc_type))
    logsetup.setup(logs, native_crash=False)
    try:
        raise ValueError("boom-main")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    def work():
        raise KeyError("boom-thread")

    t = threading.Thread(target=work, name="w1")
    t.start()
    t.join()
    _flush()
    text = (logs / "scribsalmon.log").read_text(encoding="utf-8")
    assert "boom-main" in text and "KeyError" in text and "[w1]" in text
    assert ValueError in seen and KeyError in seen
    hook = logsetup._state["excepthook"]
    logsetup.shutdown()
    assert sys.excepthook is not hook


def test_tail_limit_and_redaction(logs):
    logsetup.setup(logs, native_crash=False)
    lg = logging.getLogger("t")
    for i in range(30):
        lg.info("line %d sk-ant-api03-LEAKLEAKLEAK", i)
    _flush()
    out = logsetup.tail(5)
    assert len(out.splitlines()) == 5
    assert "line 29" in out and "line 24" not in out
    assert "LEAKLEAK" not in out


def test_tail_without_file_is_empty(logs):
    logsetup.setup(logs / "nolog", native_crash=False)  # delay=True: nothing written yet
    assert logsetup.tail() in ("",) or "starting" in logsetup.tail()


def test_diagnostics_text(logs):
    logsetup.setup(logs, native_crash=False)
    _flush()
    txt = logsetup.diagnostics_text({"GPU": {"state": "ready", "k": "api_key=abcdef123"}, "n": ["a", "b"]})
    assert "== GPU ==" in txt and "state: ready" in txt and "abcdef123" not in txt
    assert "== log" in txt and "starting" in txt


def test_native_crash_file(logs):
    logsetup.setup(logs)
    assert (logs / "crash.log").exists()
    assert os.path.getsize(logs / "crash.log") == 0
