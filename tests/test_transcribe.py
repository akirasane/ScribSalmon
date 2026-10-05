"""Characterization of app.transcribe helpers (current behavior), plus xfail(strict) known bugs for 1.2."""
import numpy as np
import pytest

from app import transcribe


def test_collapse_repeats_thai_loop():
    loop = "ทุกคน" * 10
    assert transcribe.collapse_repeats(f"สวัสดี {loop} ครับ") == "สวัสดี ทุกคน ครับ"


def test_collapse_repeats_leaves_normal_text_and_short_repeats():
    assert transcribe.collapse_repeats("hello world") == "hello world"
    assert transcribe.collapse_repeats("ha ha ha") == "ha ha ha"  # only 3 repeats
    assert transcribe.collapse_repeats("ab" * 6) == "ab"


@pytest.mark.xfail(strict=True, reason="known bug (fix in 1.2): repeated digits are treated as a Whisper loop")
def test_collapse_repeats_keeps_long_numbers():
    assert transcribe.collapse_repeats("100000000") == "100000000"


def test_is_silent_basic():
    assert transcribe.is_silent(np.zeros(0, np.float32))
    assert transcribe.is_silent(np.zeros(16000, np.float32))
    assert not transcribe.is_silent(np.full(16000, 0.1, np.float32))


@pytest.mark.xfail(strict=True, reason="known bug (fix in 1.2): fixed RMS gate drops quiet speech")
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


def test_load_wav_rejects_non_16bit(wav_file):
    with pytest.raises(ValueError):
        transcribe.load_wav(wav_file(sampwidth=3))
