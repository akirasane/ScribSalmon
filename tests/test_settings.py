import json
import sys

import pytest

from app import settings
from app.settings import Settings

win = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
KEY = "sk-ant-PLAINTEXT-123"


def _file():
    return json.loads(settings.SETTINGS_FILE.read_text(encoding="utf-8"))


def _bak():
    return settings.SETTINGS_FILE.with_name("settings.json.bak")


@win
def test_save_encrypts_and_loads_back(data_dirs):
    s = Settings()
    s.anthropic_key = KEY
    s.save()
    assert _file()["anthropic_key"].startswith("dpapi:v1:")
    assert KEY not in settings.SETTINGS_FILE.read_text(encoding="utf-8")
    assert Settings.load().anthropic_key == KEY


@win
def test_plaintext_migrates_and_bak_has_no_plaintext(data_dirs):
    settings.APP_DIR.mkdir(parents=True)
    settings.SETTINGS_FILE.write_text(json.dumps({"anthropic_key": KEY, "language": "th"}), encoding="utf-8")
    s = Settings.load()
    assert s.anthropic_key == KEY and s.language == "th"
    assert _file()["anthropic_key"].startswith("dpapi:v1:")
    assert _bak().exists() and KEY not in _bak().read_text(encoding="utf-8")
    assert Settings.load().anthropic_key == KEY


@win
def test_unreadable_blob_survives_save(data_dirs):
    settings.APP_DIR.mkdir(parents=True)
    blob = "dpapi:v1:AAAA"
    settings.SETTINGS_FILE.write_text(json.dumps({"anthropic_key": blob, "language": "en"}), encoding="utf-8")
    s = Settings.load()
    assert s.anthropic_key == "" and s._unreadable == {"anthropic_key"}
    s.language = "th"
    s.save()
    assert _file()["anthropic_key"] == blob and _file()["language"] == "th"
    s.anthropic_key = "new-key"  # user re-enters it
    s.save()
    assert Settings.load().anthropic_key == "new-key"


def test_corrupt_file_falls_back_to_bak(data_dirs):
    s = Settings()
    s.language = "th"
    s.save()
    s.language = "en"
    s.save()  # now .bak holds the "th" version
    assert _bak().exists()
    settings.SETTINGS_FILE.write_text("{ not json", encoding="utf-8")
    assert Settings.load().language == "th"


def test_env_key_not_persisted(data_dirs, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-xyz")
    settings.APP_DIR.mkdir(parents=True)
    settings.SETTINGS_FILE.write_text(json.dumps({"anthropic_key": "env-key-xyz"}), encoding="utf-8")
    s = Settings.load()
    assert s.anthropic_key == "" and s.effective_anthropic_key == "env-key-xyz"
    assert "env-key-xyz" not in settings.SETTINGS_FILE.read_text(encoding="utf-8")


def test_encrypt_failure_falls_back_to_plaintext(data_dirs, monkeypatch):
    def boom(s):
        raise settings.dpapi.DpapiError("no")

    monkeypatch.setattr(settings.dpapi, "protect", boom)
    s = Settings()
    s.openai_key = "k"
    s.save()
    assert _file()["openai_key"] == "k"
