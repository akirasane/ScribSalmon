"""Characterization of app.sessions (current behavior)."""
import pytest

from app import sessions


@pytest.mark.parametrize("good", ["2026-01-01_10-00-00", "abc", "a_b-c"])
def test_valid_ids(good):
    assert sessions.is_valid_id(good)


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "../x", "a b", "a.b", None, 5])
def test_invalid_ids(bad):
    assert not sessions.is_valid_id(bad)


def test_create_and_load_roundtrip(data_dirs):
    s = sessions.create()
    assert s.dir.is_dir() and s.dir.parent == sessions.SESSIONS_DIR
    assert (s.dir / "meta.json").exists()
    assert s.title.startswith("Meeting ")
    loaded = sessions.load(s.dir)
    assert loaded.title == s.title
    assert [x.dir for x in sessions.list_all()] == [s.dir]


def test_create_twice_gets_distinct_folders(data_dirs):
    a, b = sessions.create(), sessions.create()
    assert a.dir != b.dir


def test_write_read_append(data_dirs):
    s = sessions.create()
    assert s.read("transcript.txt") == ""
    s.write("transcript.txt", "one")
    s.append("transcript.txt", "two")
    assert s.read("transcript.txt") == "one\ntwo\n"
    assert sessions.append_text("", "x") == "x\n"
    assert sessions.append_text("a\n", "b") == "a\nb\n"


def test_next_part_path_and_duration(data_dirs, wav_file):
    s = sessions.create()
    assert s.next_part_path().name == "rec_001.wav"
    src = wav_file(seconds=2.0)
    (s.dir / "rec_001.wav").write_bytes(src.read_bytes())
    assert s.next_part_path().name == "rec_002.wav"
    assert s.duration == pytest.approx(2.0, abs=0.01)


def test_delete_removes_session_folder(data_dirs):
    s = sessions.create()
    sessions.delete(s)
    assert not s.dir.exists()


def test_delete_guard_refuses_outside_notes_folder(data_dirs):
    outside = data_dirs / "elsewhere"
    outside.mkdir()
    with pytest.raises(ValueError):
        sessions.delete(sessions.Session(outside, "x", None))
    assert outside.exists()
    # the notes root itself and nested folders are refused too
    with pytest.raises(ValueError):
        sessions.delete(sessions.Session(sessions.SESSIONS_DIR, "x", None))
    nested = sessions.SESSIONS_DIR / "a" / "b"
    nested.mkdir(parents=True)
    with pytest.raises(ValueError):
        sessions.delete(sessions.Session(nested, "x", None))
    assert nested.exists()


def test_list_all_ignores_invalid_and_empty_folders(data_dirs):
    (sessions.SESSIONS_DIR / "empty").mkdir()
    (sessions.SESSIONS_DIR / "has space").mkdir()
    (sessions.SESSIONS_DIR / "has space" / "meta.json").write_text("{}", encoding="utf-8")
    s = sessions.create()
    assert [x.dir.name for x in sessions.list_all()] == [s.dir.name]


def test_load_legacy_folder_named_by_timestamp(data_dirs):
    d = sessions.SESSIONS_DIR / "2025-03-04_05-06-07"
    d.mkdir()
    s = sessions.load(d)
    assert s.title == "Meeting 2025-03-04 05:06"
