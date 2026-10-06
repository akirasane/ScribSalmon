import threading
import time

import numpy as np
import pytest

from app import core, sessions
from app.errors import Cancelled


class Rec:
    """Recording emit(): keeps every (event, payload)."""

    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, name, payload):
        with self.lock:
            self.events.append((name, payload))

    def of(self, name):
        with self.lock:
            return [p for n, p in self.events if n == name]

    def last(self, name):
        v = self.of(name)
        return v[-1] if v else None


class FakeEngine:
    def __init__(self, text="hello", gate=None):
        self.text, self.gate, self.calls = text, gate, []

    def transcribe(self, audio, language, prompt=None, long_form=False, should_stop=None):
        self.calls.append({"long_form": long_form, "should_stop": should_stop})
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if should_stop and should_stop():
                    raise Cancelled()
        return self.text


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def ctl(data_dirs):
    rec = Rec()
    c = core.Controller(rec)
    c.engine = FakeEngine()
    return c, rec


def note_with_audio(c, wav_file):
    n = c.create_note()
    src = wav_file(seconds=1.0)
    (sessions.SESSIONS_DIR / n["id"] / "rec_001.wav").write_bytes(src.read_bytes())
    return n["id"]


def test_retranscribe_refused_while_pending(ctl, wav_file):
    c, _ = ctl
    nid = note_with_audio(c, wav_file)
    c._pending[nid] = 2
    with pytest.raises(ValueError, match="Wait for transcription to finish"):
        c.retranscribe(nid)
    assert not c._tasks


def test_retranscribe_refused_when_already_refining(ctl, wav_file):
    c, rec = ctl
    gate = threading.Event()
    c.engine = FakeEngine(gate=gate)
    nid = note_with_audio(c, wav_file)
    c.retranscribe(nid)
    assert wait_for(lambda: c.engine.calls)
    with pytest.raises(ValueError):
        c.retranscribe(nid)
    with pytest.raises(ValueError, match="Refine"):
        c.start_recording(nid, {"system": False, "mic": True})
    with pytest.raises(ValueError, match="Refine"):
        c.import_wav(nid, "whatever.wav")
    gate.set()
    assert wait_for(lambda: not c._tasks)
    assert rec.last("tasks") == {"id": nid, "tasks": []}
    assert rec.last("busy") is False


def test_refine_cancel_keeps_old_transcript(ctl, wav_file):
    c, rec = ctl
    c.engine = FakeEngine(text="new text", gate=threading.Event())
    nid = note_with_audio(c, wav_file)
    c.get_note(nid)
    sessions.load(sessions.SESSIONS_DIR / nid).write("transcript.txt", "old\n")
    c.retranscribe(nid)
    assert wait_for(lambda: c.engine.calls)
    assert c.cancel("refine", nid) is True
    assert wait_for(lambda: not c._tasks)
    assert c.get_note(nid)["transcript"] == "old\n"
    assert rec.last("status") == "Cancelled"
    assert rec.of("error") == []
    assert rec.of("transcript") == []


def test_busy_stays_true_while_summary_runs_after_queue_drains(ctl, monkeypatch):
    c, rec = ctl
    release = threading.Event()

    def slow_summary(*a, **kw):
        release.wait(5)
        return "# done"

    monkeypatch.setattr(core, "summarize", slow_summary)
    nid = c.create_note()["id"]
    c.summarize(nid, "text")
    assert rec.last("tasks") == {"id": nid, "tasks": ["summary"]}
    c._ensure_worker()
    c._enqueue(nid, np.zeros(16000 * 6, np.float32))
    assert rec.last("backlog")["seconds_behind"] == 6.0
    c._enqueue(nid, None)
    assert wait_for(lambda: c._pending.get(nid, 0) == 0)
    assert wait_for(lambda: rec.last("backlog")["pending"] == 0)
    time.sleep(0.1)
    assert rec.last("busy") is True  # queue drained, summary still running
    release.set()
    assert wait_for(lambda: rec.last("busy") is False)
    assert rec.last("tasks") == {"id": nid, "tasks": []}
    assert c.get_note(nid)["summary"] == "# done"


def test_summary_cancel_flow(ctl, monkeypatch):
    c, rec = ctl
    started = threading.Event()

    def fake_summarize(*a, cancel=None, **kw):
        started.set()
        assert cancel.wait(5)
        raise Cancelled()

    monkeypatch.setattr(core, "summarize", fake_summarize)
    nid = c.create_note()["id"]
    c.summarize(nid, "text")
    assert started.wait(5)
    assert c.cancel("summary", nid) is True
    assert wait_for(lambda: not c._tasks)
    assert rec.last("status") == "Cancelled"
    assert rec.of("error") == []
    assert rec.last("summary") == {"id": nid, "markdown": None}
    assert rec.last("busy") is False
    assert c.cancel("summary", nid) is False  # nothing left to cancel


def test_review_cancel_and_result(ctl, monkeypatch):
    c, rec = ctl
    monkeypatch.setattr(core, "review", lambda *a, cancel=None, **kw: (_ for _ in ()).throw(Cancelled()))
    nid = c.create_note()["id"]
    c.review(nid, "text")
    assert wait_for(lambda: not c._tasks)
    assert rec.last("review") == {"id": nid, "items": None}
    assert rec.of("error") == []


def test_cancel_validates_input(ctl):
    c, _ = ctl
    with pytest.raises(ValueError):
        c.cancel("bogus", "abc")
    with pytest.raises(ValueError):
        c.cancel("summary", "../x")


def test_duplicate_summary_rejected(ctl, monkeypatch):
    c, _ = ctl
    release = threading.Event()
    monkeypatch.setattr(core, "summarize", lambda *a, **kw: release.wait(5) and "x")
    nid = c.create_note()["id"]
    c.summarize(nid, "t")
    with pytest.raises(ValueError):
        c.summarize(nid, "t")
    release.set()
    assert wait_for(lambda: not c._tasks)


def test_get_settings_has_version(ctl):
    from app.version import VERSION
    assert ctl[0].get_settings()["version"] == VERSION


def test_import_wav_validates_before_queueing(ctl, monkeypatch, tmp_path):
    c, _ = ctl
    nid = c.create_note()["id"]

    def bad(src, dest):
        raise ValueError("Unsupported audio file.")

    monkeypatch.setattr(core._transcribe, "import_audio", bad, raising=False)
    with pytest.raises(ValueError, match="Unsupported"):
        c.import_wav(nid, str(tmp_path / "x.mp3"))
    assert not c._pending


def test_list_notes_search_uses_cached_matches(data_dirs):
    from app import core, sessions

    c = core.Controller(lambda *a: None)
    n = c.create_note()
    s = sessions.load(sessions.SESSIONS_DIR / n["id"])
    s.write("transcript.txt", "hello budget meeting\n")
    assert [x["id"] for x in c.list_notes("budget")] == [n["id"]]
    assert c.list_notes("nonexistent-term") == []
    assert len(c.list_notes("")) == 1


def test_backlog_fallback_stops_live_feed_and_transcribes_rest(ctl, wav_file, monkeypatch):
    c, rec = ctl
    nid = c.create_note()["id"]
    path = wav_file(seconds=3.0)
    state = {"fallback": False, "fed": 0.0}
    chunk = np.zeros(16000, np.float32)
    calls = []
    monkeypatch.setattr(c, "_enqueue", lambda n, a: calls.append(a))
    c._live_chunk(nid, state, chunk)
    assert state["fed"] == 1.0 and len(calls) == 1
    c._behind[nid] = 121.0
    c._live_chunk(nid, state, chunk)
    c._live_chunk(nid, state, chunk)
    assert state["fallback"] and len(calls) == 1 and state["fed"] == 1.0
    assert any("fell behind" in s for s in rec.of("status"))
    assert not rec.of("error")

    class R:
        def stop(self):
            pass

    got = {}
    monkeypatch.setattr(c, "_transcribe_file",
                        lambda n, p, start_seconds=0.0: got.update(n=n, p=p, s=start_seconds))
    c.recorder, c.rec_session, c.rec_path, c.rec_live, c.rec_state = R(), c._session(nid), path, True, state
    c.stop_recording()
    assert got == {"n": nid, "p": path, "s": 1.0}


def test_transcribe_file_start_seconds_skips_audio(ctl, wav_file):
    c, rec = ctl
    seen = []

    class E(FakeEngine):
        def transcribe(self, audio, language, prompt=None, **kw):
            seen.append(len(audio))
            return ""

    c.engine = E()
    nid = c.create_note()["id"]
    c._transcribe_file(nid, wav_file(seconds=3.0), start_seconds=1.0)
    assert wait_for(lambda: seen)
    assert seen == [32000]


def test_save_settings_ignores_internal_fields(ctl):
    c, _ = ctl
    c.save_settings({"last_update_check": 123.0, "skipped_version": "9.9.9", "check_updates": False})
    assert c.s.last_update_check == 0.0
    assert c.s.skipped_version == ""
    assert c.s.check_updates is False


def test_save_update_fields_only_touches_internal(ctl):
    c, _ = ctl
    c._save_update_fields({"last_update_check": 42, "skipped_version": "1.5.0", "language": "th", "engine": "openai"})
    assert c.s.last_update_check == 42.0
    assert c.s.skipped_version == "1.5.0"
    assert c.s.language == "auto" and c.s.engine == "local"
    from app.settings import Settings
    assert Settings.load().skipped_version == "1.5.0"


def test_get_settings_reports_install_mode(ctl):
    c, _ = ctl
    assert c.get_settings()["install_mode"] in ("installed", "portable", "source")


def test_updater_is_idle_tracks_recording_and_work(ctl):
    c, _ = ctl
    assert c._is_idle() is True
    c._add_pending("n1", 1)
    assert c._is_idle() is False
    c._add_pending("n1", -1)
    assert c._is_idle() is True
    c.recorder = object()
    assert c._is_idle() is False
    c.recorder = None


def test_start_recording_refused_when_quitting(ctl):
    c, _ = ctl
    c.updater.quitting = True
    with pytest.raises(ValueError, match="update"):
        c.start_recording("whatever", {})


# ---------------------------------------------------------------- GPU bridge
class FbEngine(FakeEngine):
    def __init__(self, reason, device="cpu"):
        super().__init__()
        self.fallback_reason, self.device = reason, device


def test_gpu_fallback_emitted_once_per_reason(ctl, monkeypatch):
    c, rec = ctl
    c.engine = None
    reasons = ["Library cublas64_12.dll is not found or cannot be loaded", "other failure"]
    seq = iter(reasons + reasons)
    monkeypatch.setattr(core, "make_engine", lambda s: FbEngine(next(seq)))
    for _ in range(4):
        c._get_engine()
        c._reset_engine()
    ev = rec.of("gpu_fallback")
    assert len(ev) == 2
    assert ev[0]["detail"] == reasons[0] and "cuBLAS" in ev[0]["reason"]
    assert ev[1]["reason"] == "other failure"
    assert not [e for e in rec.of("error") if "GPU unavailable" in str(e)]


def test_engine_log_has_no_secrets(ctl, monkeypatch, caplog):
    c, _ = ctl
    c.engine = None
    c.s.openai_key = "sk-SECRETSECRETSECRET1234"
    c.s.vocabulary = "TOPSECRETWORD"
    monkeypatch.setattr(core, "make_engine", lambda s: FbEngine(None))
    with caplog.at_level("INFO", logger="app.core"):
        c._get_engine()
    assert "engine ready" in caplog.text
    assert "SECRETSECRET" not in caplog.text and "TOPSECRETWORD" not in caplog.text


def test_gpu_libs_installed_resets_engine_and_returns_status(ctl, monkeypatch):
    c, rec = ctl
    calls = []
    monkeypatch.setattr(core.gpu, "activate", lambda preload=False: calls.append(("activate", preload)))
    monkeypatch.setattr(core.gpu, "invalidate_cache", lambda: calls.append("invalidate"))
    monkeypatch.setattr(core.gpu, "status", lambda *a, **k: {"state": "ready", "message": "ok"})
    gen = c._engine_gen
    st = c._on_gpu_libs_installed()
    assert c.engine is None and c._engine_gen == gen + 1
    assert calls == [("activate", True), "invalidate"]
    assert st["state"] == "ready" and st["download_bytes"] > 0 and st["disk_bytes"] > 0
    assert st["eula_url"].startswith("https://") and "gpu-libs" in st["libs_folder"]


def test_installer_gpu_ready_carries_fresh_status(ctl, monkeypatch):
    c, rec = ctl
    monkeypatch.setattr(core.gpu, "activate", lambda preload=False: None)
    monkeypatch.setattr(core.gpu, "status", lambda *a, **k: {"state": "ready"})
    monkeypatch.setattr(core.gpulibs, "install", lambda prog, cancel: None)
    assert c.gpulibs.start() is True
    assert wait_for(lambda: rec.of("gpu_ready"))
    assert rec.last("gpu_ready")["status"]["state"] == "ready"


def test_gpu_status_merges_engine_state(ctl, monkeypatch):
    c, _ = ctl
    monkeypatch.setattr(core.gpu, "status", lambda *a, **k: {"state": "ready", "message": "m", "hint": ""})
    c.engine = FbEngine(None, device="cuda")
    assert c.gpu_status()["state"] == "active"
    c.engine = FbEngine("cublas64_12.dll is not found", device="cpu")
    assert c.gpu_status()["state"] == "failed"


def test_restart_app_only_when_idle(ctl):
    c, _ = ctl
    c.recorder = object()
    with pytest.raises(ValueError):
        c.restart_app()
    c.recorder = None
    c._pending["x"] = 1
    with pytest.raises(ValueError):
        c.restart_app()
    assert c.restart_requested is False
    c._pending.clear()
    assert c.restart_app() is True and c.restart_requested is True


def test_diagnostics_has_sections_and_no_secrets(ctl, monkeypatch):
    c, _ = ctl
    monkeypatch.setattr(core.gpu, "status", lambda *a, **k: {"state": "no_gpu"})
    c.s.openai_key = "sk-SECRETSECRETSECRET1234"
    c.s.anthropic_key = "sk-ant-api03-" + "Zz9y8X7w" * 4
    c.s.vocabulary = "TOPSECRETWORD"
    n = c.create_note()
    sessions.load(sessions.SESSIONS_DIR / n["id"]).write("transcript.txt", "PRIVATE TRANSCRIPT TEXT")
    text = c.diagnostics()
    for sec in ("version", "install mode", "os", "settings", "gpu", "engine"):
        assert f"== {sec} ==" in text
    for bad in ("SECRETSECRET", "Zz9y8X7w", "TOPSECRETWORD", "PRIVATE TRANSCRIPT"):
        assert bad not in text


def test_error_wrapper_logs_and_emits(ctl, caplog):
    c, rec = ctl
    with caplog.at_level("WARNING", logger="app.core"):
        c._err("boom")
    assert rec.last("error") == "boom" and "boom" in caplog.text


def test_shutdown_cancels_gpu_download(ctl, monkeypatch):
    c, _ = ctl
    called = []
    monkeypatch.setattr(c.gpulibs, "cancel", lambda: called.append(1) or True)
    c.shutdown()
    assert called
