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


def test_update_field_defaults(data_dirs):
    s = Settings.load()
    assert s.check_updates is True
    assert s.last_update_check == 0.0
    assert s.skipped_version == ""
    assert settings.INTERNAL == {"last_update_check", "skipped_version"}


def test_float_field_accepts_int_and_converts():
    assert settings.coerce_patch({"last_update_check": 1700000000}) == {"last_update_check": 1700000000.0}
    out = settings.coerce_patch({"last_update_check": 12})["last_update_check"]
    assert isinstance(out, float)
    assert settings.coerce_patch({"last_update_check": 1.5}) == {"last_update_check": 1.5}


@pytest.mark.parametrize("bad", ["12", True, -1, -0.5, float("nan"), float("inf"), None])
def test_float_field_rejects_bad(bad):
    with pytest.raises(ValueError):
        settings.coerce_patch({"last_update_check": bad})
    assert settings.coerce_patch({"last_update_check": bad}, strict=False) == {}


def test_check_updates_is_bool_only():
    assert settings.coerce_patch({"check_updates": False}) == {"check_updates": False}
    with pytest.raises(ValueError):
        settings.coerce_patch({"check_updates": 1})


@pytest.mark.parametrize("v", ["", "1.4.0", "10.0.1", "1.4.0-rc.1", "1.4.0+build.5"])
def test_skipped_version_accepts(v):
    assert settings.coerce_patch({"skipped_version": v}) == {"skipped_version": v}


@pytest.mark.parametrize("v", ["dev", "1.4", "01.2.3", "v1.4.0", "1.4.0 ", "1.4.0-", "x" * 100, 5, None])
def test_skipped_version_rejects(v):
    with pytest.raises(ValueError):
        settings.coerce_patch({"skipped_version": v})
