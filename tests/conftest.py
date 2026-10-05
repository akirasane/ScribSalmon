"""Shared pytest setup.

`app.settings` resolves (and may rename legacy) data folders at import time, so APPDATA / USERPROFILE must
point at a throw-away directory BEFORE any `app` module is imported. Never touch real user data in tests.
"""
import os
import sys
import tempfile
import wave
from pathlib import Path

_SESSION_HOME = Path(tempfile.mkdtemp(prefix="scribsalmon-test-"))
os.environ["APPDATA"] = str(_SESSION_HOME / "AppData")
os.environ["USERPROFILE"] = str(_SESSION_HOME)
os.environ["HOME"] = str(_SESSION_HOME)
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    """Point every module-level data path at tmp_path. sessions.py binds SESSIONS_DIR by value, so patch both."""
    from app import sessions, settings

    app_dir = tmp_path / "cfg"
    notes = tmp_path / "docs" / "ScribSalmon"
    notes.mkdir(parents=True)
    monkeypatch.setattr(settings, "APP_DIR", app_dir)
    monkeypatch.setattr(settings, "SETTINGS_FILE", app_dir / "settings.json")
    monkeypatch.setattr(settings, "SESSIONS_DIR", notes)
    monkeypatch.setattr(sessions, "SESSIONS_DIR", notes)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return tmp_path


@pytest.fixture
def wav_file(tmp_path):
    """Factory: wav_file(sr=16000, ch=1, sampwidth=2, seconds=1.0, freq=440, amp=0.5) -> Path (PCM sine)."""
    def make(sr=16000, ch=1, sampwidth=2, seconds=1.0, freq=440.0, amp=0.5, name="t.wav"):
        t = np.arange(int(sr * seconds)) / sr
        sig = amp * np.sin(2 * np.pi * freq * t)
        if sampwidth == 2:
            raw = (sig * 32767).astype("<i2")
            frames = np.repeat(raw[:, None], ch, axis=1).tobytes()
        elif sampwidth == 3:
            i32 = (sig * 8388607).astype("<i4")
            b = i32.tobytes()
            mono = b"".join(b[i:i + 3] for i in range(0, len(b), 4))
            frames = mono if ch == 1 else b"".join(mono[i:i + 3] * ch for i in range(0, len(mono), 3))
        else:
            raise ValueError("sampwidth 2 or 3")
        p = tmp_path / name
        with wave.open(str(p), "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(sampwidth)
            w.setframerate(sr)
            w.writeframes(frames)
        return p
    return make
