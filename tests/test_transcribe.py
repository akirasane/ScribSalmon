"""Characterization of app.transcribe helpers (current behavior)."""
import wave

import numpy as np
import pytest

from app import errors, transcribe


def test_collapse_repeats_thai_loop():
    loop = "ทุกคน" * 10
    assert transcribe.collapse_repeats(f"สวัสดี {loop} ครับ") == "สวัสดี ทุกคน ครับ"


def test_collapse_repeats_leaves_normal_text_and_short_repeats():
    assert transcribe.collapse_repeats("hello world") == "hello world"
    assert transcribe.collapse_repeats("ha ha ha") == "ha ha ha"  # only 3 repeats
    assert transcribe.collapse_repeats("ab" * 6) == "ab"


def test_collapse_repeats_keeps_long_numbers():
    assert transcribe.collapse_repeats("100000000") == "100000000"


def test_is_silent_basic():
    assert transcribe.is_silent(np.zeros(0, np.float32))
    assert transcribe.is_silent(np.zeros(16000, np.float32))
    assert not transcribe.is_silent(np.full(16000, 0.1, np.float32))


def test_is_silent_does_not_drop_quiet_speech():
    t = np.arange(16000) / 16000
    quiet = (0.004 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)  # rms ~0.0028 < SILENCE_RMS
    assert not transcribe.is_silent(quiet)


def test_normalize_boosts_quiet_audio_only():
    quiet = np.full(100, 0.1, np.float32)
    assert float(np.max(np.abs(transcribe.normalize(quiet)))) == pytest.approx(0.7)
    loud = np.full(100, 0.8, np.float32)
    assert np.array_equal(transcribe.normalize(loud), loud)
    assert transcribe.normalize(np.zeros(5, np.float32)).dtype == np.float32


def test_load_wav_16k_mono_passthrough(wav_file):
    a = transcribe.load_wav(wav_file(sr=16000, seconds=1.0))
    assert a.dtype == np.float32 and len(a) == 16000
    assert float(np.max(np.abs(a))) == pytest.approx(0.5, abs=0.01)


def test_load_wav_resamples_and_downmixes(wav_file):
    a = transcribe.load_wav(wav_file(sr=48000, ch=2, seconds=1.0))
    assert len(a) == 16000
    b = transcribe.load_wav(wav_file(sr=8000, seconds=1.0, name="u.wav"))
    assert len(b) == 16000


def test_load_wav_decodes_24bit(wav_file):
    a = transcribe.load_wav(wav_file(sampwidth=3, seconds=1.0))
    assert len(a) == 16000


def _read(p):
    with wave.open(str(p), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()


def test_import_audio_fast_path(wav_file, tmp_path):
    dest = tmp_path / "out" / "a.wav"
    dest.parent.mkdir()
    dur = transcribe.import_audio(wav_file(seconds=1.5), dest)
    assert dur == pytest.approx(1.5)
    assert _read(dest) == (16000, 1, 2, 24000)
    assert [p.name for p in dest.parent.iterdir()] == ["a.wav"]


def test_import_audio_44k_stereo(wav_file, tmp_path):
    dest = tmp_path / "a.wav"
    dur = transcribe.import_audio(wav_file(sr=44100, ch=2, seconds=1.0, name="s.wav"), dest)
    assert dur == pytest.approx(1.0, abs=0.05)
    assert _read(dest)[:3] == (16000, 1, 2)


def test_import_audio_24bit(wav_file, tmp_path):
    dest = tmp_path / "a.wav"
    dur = transcribe.import_audio(wav_file(sampwidth=3, seconds=1.0, name="w.wav"), dest)
    assert dur == pytest.approx(1.0, abs=0.05)
    assert _read(dest)[:3] == (16000, 1, 2)


def test_import_audio_garbage_leaves_nothing(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"this is not audio at all" * 50)
    dest = tmp_path / "note" / "a.wav"
    dest.parent.mkdir()
    with pytest.raises(ValueError):
        transcribe.import_audio(bad, dest)
    assert list(dest.parent.iterdir()) == []


def test_collapse_repeats_digits_dots_and_words():
    assert transcribe.collapse_repeats("100000000") == "100000000"
    assert transcribe.collapse_repeats("wait......") == "wait......"
    assert transcribe.collapse_repeats("hahahahaha") == "ha"
    assert transcribe.collapse_repeats("ทุกคน" * 6) == "ทุกคน"


def test_is_silent_local_vs_strict():
    t = np.arange(16000) / 16000
    quiet = (0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)  # peak 0.01, rms ~0.007
    assert not transcribe.is_silent(quiet)
    assert not transcribe.is_silent(quiet, strict=True)
    assert transcribe.is_silent(quiet * 0.3, strict=True)  # rms ~0.002
    assert not transcribe.is_silent(quiet * 0.3)
    assert transcribe.is_silent(np.full(16000, 0.002, np.float32))
    assert transcribe.is_silent(np.zeros(16000, np.float32))


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def transcribe(self, audio, **kw):
        def gen():
            yield _Seg("one")
            yield _Seg("two")
        return gen(), type("I", (), {"duration_after_vad": 2.0})()


def _local():
    e = transcribe.LocalWhisper.__new__(transcribe.LocalWhisper)
    e.model, e.device, e.requested, e.fallback_reason = _FakeModel(), "cpu", "cpu", None
    return e


def test_local_transcribe_should_stop_raises_cancelled():
    audio = np.full(16000, 0.1, np.float32)
    assert _local().transcribe(audio, "en", long_form=True) == "one\ntwo"
    calls = []

    def stop():
        calls.append(1)
        return len(calls) > 1  # let the pre-check pass, stop after the first segment

    with pytest.raises(errors.Cancelled):
        _local().transcribe(audio, "en", should_stop=stop)
    with pytest.raises(errors.Cancelled):
        _local().transcribe(audio, "en", should_stop=lambda: True)


# ---- GPU / CUDA selection (fake WhisperModel, no GPU)

def _fake_whisper(monkeypatch, calls, fail_cuda=False):
    import sys
    import types

    class FakeWM:
        def __init__(self, name, device="cpu", compute_type="int8"):
            calls.append((device, compute_type))
            if device == "cuda" and fail_cuda:
                raise RuntimeError("CUDA failed with error out of memory")

        def transcribe(self, *a, **k):
            return iter([]), None
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeWM
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)


def test_auto_with_missing_dlls_skips_cuda(monkeypatch):
    calls = []
    _fake_whisper(monkeypatch, calls)
    monkeypatch.setattr(transcribe, "_cuda_count", lambda: 1)
    monkeypatch.setattr(transcribe.gpu, "activate", lambda preload=False: None)
    monkeypatch.setattr(transcribe.gpu, "missing_dlls", lambda: ["cublas64_12.dll"])
    e = transcribe.LocalWhisper("tiny", "auto")
    assert calls == [("cpu", "int8")]  # no model loaded into VRAM
    assert e.device == "cpu" and "cuBLAS 12" in e.fallback_reason


def test_cuda_with_missing_dlls_raises_clear_error(monkeypatch):
    calls = []
    _fake_whisper(monkeypatch, calls)
    monkeypatch.setattr(transcribe, "_cuda_count", lambda: 1)
    monkeypatch.setattr(transcribe.gpu, "activate", lambda preload=False: None)
    monkeypatch.setattr(transcribe.gpu, "missing_dlls", lambda: ["cublas64_12.dll"])
    with pytest.raises(RuntimeError, match="cuBLAS 12"):
        transcribe.LocalWhisper("tiny", "cuda")
    assert calls == []


def test_auto_cuda_ready_and_runtime_failure_falls_back(monkeypatch):
    calls = []
    _fake_whisper(monkeypatch, calls, fail_cuda=True)
    monkeypatch.setattr(transcribe, "_cuda_count", lambda: 1)
    monkeypatch.setattr(transcribe.gpu, "activate", lambda preload=False: None)
    monkeypatch.setattr(transcribe.gpu, "missing_dlls", lambda: [])
    e = transcribe.LocalWhisper("tiny", "auto")
    assert calls[0][0] == "cuda" and calls[-1] == ("cpu", "int8")
    assert "smaller" in e.fallback_reason
    with pytest.raises(RuntimeError, match="not usable"):
        transcribe.LocalWhisper("tiny", "cuda")


def test_activate_called_before_cuda_attempt(monkeypatch):
    order = []
    _fake_whisper(monkeypatch, order)
    monkeypatch.setattr(transcribe, "_cuda_count", lambda: 1)
    monkeypatch.setattr(transcribe.gpu, "activate", lambda preload=False: order.append(("activate", preload)))
    monkeypatch.setattr(transcribe.gpu, "missing_dlls", lambda: [])
    transcribe.LocalWhisper("tiny", "auto")
    assert order[0] == ("activate", True) and order[1][0] == "cuda"
