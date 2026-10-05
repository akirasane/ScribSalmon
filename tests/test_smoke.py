from app import sessions, settings


def test_data_dirs_are_isolated(data_dirs):
    assert str(settings.SESSIONS_DIR).startswith(str(data_dirs))
    assert sessions.SESSIONS_DIR == settings.SESSIONS_DIR


def test_is_valid_id_rejects_traversal():
    for bad in ("..", ".", "", "a/b", "a\b", "../x"):
        assert not sessions.is_valid_id(bad)
    assert sessions.is_valid_id("2026-10-05_12-00-00")
