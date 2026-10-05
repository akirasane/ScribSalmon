"""Notes-folder resolution (pure function; never touches the real machine)."""
from pathlib import Path

from app import settings


def _note(d: Path):
    (d / "2026-01-01_10-00-00").mkdir(parents=True)
    (d / "2026-01-01_10-00-00" / "meta.json").write_text("{}", encoding="utf-8")


def test_env_override_used_directly(tmp_path):
    out = settings.resolve_notes_dir({"SCRIBSALMON_DATA_DIR": str(tmp_path / "x")}, tmp_path / "k", tmp_path)
    assert out == tmp_path / "x"


def test_new_default_uses_known_folder(tmp_path):
    known = tmp_path / "OneDrive" / "Documents"
    assert settings.resolve_notes_dir({}, known, tmp_path) == known / "ScribSalmon"


def test_legacy_kept_when_populated_and_new_missing(tmp_path):
    old = tmp_path / "Documents" / "ScribSalmon"
    _note(old)
    known = tmp_path / "OneDrive" / "Documents"
    assert settings.resolve_notes_dir({}, known, tmp_path) == old


def test_legacy_not_kept_when_empty_or_new_exists(tmp_path):
    old = tmp_path / "Documents" / "ScribSalmon"
    old.mkdir(parents=True)
    known = tmp_path / "OneDrive" / "Documents"
    assert settings.resolve_notes_dir({}, known, tmp_path) == known / "ScribSalmon"
    _note(old)
    (known / "ScribSalmon").mkdir(parents=True)
    assert settings.resolve_notes_dir({}, known, tmp_path) == known / "ScribSalmon"


def test_same_path_is_new(tmp_path):
    known = tmp_path / "Documents"
    _note(known / "ScribSalmon")
    assert settings.resolve_notes_dir({}, known, tmp_path) == known / "ScribSalmon"
