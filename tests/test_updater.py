"""Updater tests. No network: `updater._open` is faked, subprocess.Popen is faked."""
import hashlib
import io
import threading
import urllib.error
import urllib.request

import pytest

from app import updater
from app.updater import UpdateError

SETUP = b"MZ-fake-installer" * 1000
SETUP_SHA = hashlib.sha256(SETUP).hexdigest()
V = "1.4.0"
BASE = f"https://github.com/akirasane/ScribSalmon/releases/download/v{V}/"


def api_json(**over):
    d = {
        "tag_name": f"v{V}", "draft": False, "prerelease": False,
        "html_url": f"https://github.com/akirasane/ScribSalmon/releases/tag/v{V}",
        "assets": [
            {"name": f"ScribSalmon-v{V}-windows-x64.zip", "size": 5,
             "browser_download_url": BASE + f"ScribSalmon-v{V}-windows-x64.zip",
             "digest": "sha256:" + "a" * 64},
            {"name": f"ScribSalmon-Setup-{V}.exe", "size": len(SETUP),
             "browser_download_url": BASE + f"ScribSalmon-Setup-{V}.exe", "digest": "sha256:" + SETUP_SHA},
            {"name": "SHA256SUMS.txt", "size": 200, "browser_download_url": BASE + "SHA256SUMS.txt"},
        ],
    }
    d.update(over)
    return d


def make_rel(**over):
    r = updater.parse_release(api_json())
    assert r
    from dataclasses import replace
    return replace(r, **over)


# ---------------------------------------------------------------- versions

@pytest.mark.parametrize("remote,local,expected", [
    ("1.3.1", "1.3.0", True), ("1.10.0", "1.9.9", True), ("1.3.0", "1.3.0", False),
    ("1.2.9", "1.3.0", False), ("1.4.0", "1.4.0-rc.1", True), ("1.4.0-rc.1", "1.4.0", False),
    ("1.4.0-rc.2", "1.4.0-rc.10", False), ("1.4.0-rc.10", "1.4.0-rc.2", True),
    ("1.4.0+b2", "1.4.0+b1", False), ("1.4.1+b2", "1.4.0", True),
    ("1.4.0", "dev", False), ("1.4.0", "junk", False), ("junk", "1.0.0", False),
    ("01.2.3", "1.0.0", False), ("2.0.0", "1.99.99", True),
])
def test_is_newer(remote, local, expected):
    assert updater.is_newer(remote, local) is expected


def test_parse_version():
    assert updater.parse_version("1.2.3") == (1, 2, 3, ())
    assert updater.parse_version("1.2.3-rc.1+x") == (1, 2, 3, ("rc", "1"))
    for bad in ("01.2.3", "1.2", "v1.2.3", "1.2.3-01", "1.2.3-", "", None, "dev"):
        assert updater.parse_version(bad) is None


# ---------------------------------------------------------------- parse_release

def test_parse_release_ok():
    r = updater.parse_release(api_json())
    assert r.version == V and r.tag == f"v{V}"
    assert r.setup_url == BASE + f"ScribSalmon-Setup-{V}.exe"
    assert r.setup_digest == SETUP_SHA and r.setup_size == len(SETUP)
    assert r.sums_url == BASE + "SHA256SUMS.txt"
    assert r.notes_url.startswith("https://github.com/akirasane/ScribSalmon/releases/")


def test_parse_release_rejects():
    assert updater.parse_release(api_json(draft=True)) is None
    assert updater.parse_release(api_json(prerelease=True)) is None
    assert updater.parse_release(api_json(tag_name="1.4.0")) is None
    assert updater.parse_release(api_json(tag_name="v1.4")) is None
    assert updater.parse_release(api_json(html_url="https://github.com/evil/x/releases/tag/v1.4.0")) is None
    assert updater.parse_release(api_json(html_url="http://github.com/akirasane/ScribSalmon/releases/x")) is None
    assert updater.parse_release([]) is None


@pytest.mark.parametrize("url", [
    "https://github.com/evil/ScribSalmon/releases/download/v1.4.0/ScribSalmon-Setup-1.4.0.exe",
    "http://github.com/akirasane/ScribSalmon/releases/download/v1.4.0/ScribSalmon-Setup-1.4.0.exe",
    "https://github.com/akirasane/ScribSalmon/releases/download/v1.3.0/ScribSalmon-Setup-1.4.0.exe",
])
def test_parse_release_bad_setup_url_ignored(url):
    d = api_json()
    d["assets"][1]["browser_download_url"] = url
    r = updater.parse_release(d)
    assert r is not None and r.setup_url is None and r.setup_name is None


def test_parse_release_no_setup_asset():
    d = api_json()
    del d["assets"][1]
    r = updater.parse_release(d)
    assert r.version == V and r.setup_url is None and r.setup_size is None and r.setup_digest is None


@pytest.mark.parametrize("digest", ["sha1:" + "a" * 40, "sha256:xyz", "sha256:" + "a" * 63, "a" * 64, 5])
def test_parse_release_bad_digest(digest):
    d = api_json()
    d["assets"][1]["digest"] = digest
    assert updater.parse_release(d) is None


def test_parse_release_missing_digest_ok():
    d = api_json()
    del d["assets"][1]["digest"]
    assert updater.parse_release(d).setup_digest is None


# ---------------------------------------------------------------- parse_sums

H1, H2 = "a" * 64, "B" * 64


def test_parse_sums_variants():
    real = f"{H1}  ScribSalmon-v1.3.0-windows-x64.zip\r\n".encode()
    assert updater.parse_sums(real) == {"ScribSalmon-v1.3.0-windows-x64.zip": H1}
    assert updater.parse_sums(f"{H1}  a.zip\n{H2}  b.exe\n") == {"a.zip": H1, "b.exe": "b" * 64}
    assert updater.parse_sums("﻿" + f"{H1}  a.zip\n") == {"a.zip": H1}
    assert updater.parse_sums(f"{H1} *a.zip\n") == {"a.zip": H1}
    assert updater.parse_sums(f"junk\n\n{H1}  my file.zip \nshort  x\n") == {"my file.zip": H1}
    assert updater.parse_sums(f"{H1}  a.zip\n{H1}  a.zip\n") == {"a.zip": H1}


def test_parse_sums_conflict():
    with pytest.raises(UpdateError):
        updater.parse_sums(f"{H1}  a.zip\n{'c' * 64}  a.zip\n")


# ---------------------------------------------------------------- check_url / redirects

@pytest.mark.parametrize("url", [
    "https://github.com/x", "https://api.github.com/repos/a/b", "HTTPS://GitHub.com/x",
    "https://release-assets.githubusercontent.com/a?b=1", "https://objects.githubusercontent.com/a",
    "https://github.com:443/x",
])
def test_check_url_allows(url):
    updater.check_url(url)


@pytest.mark.parametrize("url", [
    "http://github.com/x", "https://github.com.evil.com/x", "https://evil.com/x",
    "https://user@github.com/x", "https://user:pw@github.com/x", "https://github.com:8443/x",
    "https://gıthub.com/x", "https://xn--gthub-3ya.com/x", "ftp://github.com/x", "//github.com/x",
    "https://github.com@evil.com/x", "https://evil.com/github.com", "", None,
])
def test_check_url_denies(url):
    with pytest.raises(UpdateError):
        updater.check_url(url)


def _redirect(handler, newurl):
    req = urllib.request.Request("https://api.github.com/x")
    return handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, newurl)


def test_safe_redirect():
    h = updater._SafeRedirect()
    assert _redirect(h, "https://release-assets.githubusercontent.com/z") is not None
    for bad in ("https://evil.com/z", "http://github.com/z", "https://github.com:8443/z"):
        with pytest.raises(UpdateError):
            _redirect(h, bad)


def test_safe_redirect_limit():
    h = updater._SafeRedirect()
    for _ in range(updater.MAX_REDIRECTS):
        _redirect(h, "https://github.com/a")
    with pytest.raises(UpdateError):
        _redirect(h, "https://github.com/a")


# ---------------------------------------------------------------- download

class FakeResp(io.BytesIO):
    pass


@pytest.fixture
def fake_net(monkeypatch, tmp_path):
    """Temp dir isolated to tmp_path; returns a dict url->bytes that the fake _open serves."""
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(updater.tempfile, "tempdir", str(tmp))
    routes = {BASE + "SHA256SUMS.txt": f"{SETUP_SHA}  ScribSalmon-Setup-{V}.exe\n".encode(),
              BASE + f"ScribSalmon-Setup-{V}.exe": SETUP}
    calls = []

    def fake_open(url, max_bytes, accept):
        calls.append(url)
        updater.check_url(url)
        if url not in routes:
            raise urllib.error.URLError("no route")
        return FakeResp(routes[url])

    monkeypatch.setattr(updater, "_open", fake_open)
    popen = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: popen.append((a, k)))
    updater._verified.clear()
    yield type("Net", (), {"routes": routes, "calls": calls, "popen": popen, "tmp": tmp})
    updater._release_lock()


def test_download_happy(fake_net):
    seen = []
    p = updater.download(make_rel(), lambda r, t: seen.append((r, t)), threading.Event())
    assert p.read_bytes() == SETUP
    assert p.parent.name.startswith("ScribSalmon-update-") and p.parent.parent == fake_net.tmp
    assert seen and seen[-1] == (len(SETUP), len(SETUP))
    assert fake_net.calls[0].endswith("SHA256SUMS.txt")
    assert updater._verified[str(p)] == SETUP_SHA


def test_download_hash_mismatch_cleans_up(fake_net):
    fake_net.routes[BASE + f"ScribSalmon-Setup-{V}.exe"] = b"X" * len(SETUP)
    with pytest.raises(UpdateError, match="[Cc]hecksum"):
        updater.download(make_rel())
    assert list(fake_net.tmp.iterdir()) == []
    assert fake_net.popen == []


def test_download_digest_disagrees_with_sums(fake_net):
    with pytest.raises(UpdateError, match="disagree"):
        updater.download(make_rel(setup_digest="f" * 64))
    assert fake_net.calls == [BASE + "SHA256SUMS.txt"]
    assert list(fake_net.tmp.iterdir()) == []


def test_download_oversize_stream(fake_net):
    fake_net.routes[BASE + f"ScribSalmon-Setup-{V}.exe"] = SETUP + b"extra"
    with pytest.raises(UpdateError, match="larger"):
        updater.download(make_rel())
    assert list(fake_net.tmp.iterdir()) == []


def test_download_truncated(fake_net):
    fake_net.routes[BASE + f"ScribSalmon-Setup-{V}.exe"] = SETUP[:-1]
    with pytest.raises(UpdateError, match="incomplete"):
        updater.download(make_rel())
    assert list(fake_net.tmp.iterdir()) == []


def test_download_cancel(fake_net):
    ev = threading.Event()
    ev.set()
    with pytest.raises(UpdateError, match="cancel"):
        updater.download(make_rel(), None, ev)
    assert list(fake_net.tmp.iterdir()) == []


def test_download_sums_missing_entry(fake_net):
    fake_net.routes[BASE + "SHA256SUMS.txt"] = f"{SETUP_SHA}  other.exe\n".encode()
    with pytest.raises(UpdateError, match="SHA256SUMS"):
        updater.download(make_rel())
    assert list(fake_net.tmp.iterdir()) == []


def test_download_no_setup_asset(fake_net):
    with pytest.raises(UpdateError):
        updater.download(make_rel(setup_url=None, setup_name=None))


# ---------------------------------------------------------------- install

class Box:
    def __init__(self, monkeypatch, idle=True, ver="1.3.0", mode="installed"):
        self.saved, self.emitted = [], []
        self.idle = idle
        monkeypatch.setattr(updater, "VERSION", ver)
        monkeypatch.setattr(updater, "install_mode", lambda: mode)
        self.u = updater.Updater(lambda e, p: self.emitted.append((e, p)),
                                 lambda: {"check_updates": True, "last_update_check": 0.0, "skipped_version": ""},
                                 self.saved.append, lambda: self.idle)


def ready_updater(fake_net, monkeypatch, **kw):
    box = Box(monkeypatch, **kw)
    rel = make_rel()
    p = updater.download(rel)
    box.u._ready = (rel, p)
    return box, p


def test_install_happy(fake_net, monkeypatch):
    box, p = ready_updater(fake_net, monkeypatch)
    assert box.u.install() is True
    assert box.u.quitting is True
    (args, kw), = fake_net.popen
    assert args[0] == [str(p), *updater.INSTALLER_ARGS, f"/LOG={p.parent / 'install.log'}"]
    assert kw["shell"] is False and kw["cwd"] == str(p.parent)


def test_install_not_idle(fake_net, monkeypatch):
    box, _ = ready_updater(fake_net, monkeypatch, idle=False)
    with pytest.raises(UpdateError, match="Stop recording"):
        box.u.install()
    assert fake_net.popen == [] and not box.u.quitting


def test_install_source_mode(fake_net, monkeypatch):
    box, _ = ready_updater(fake_net, monkeypatch, mode="source")
    with pytest.raises(UpdateError):
        box.u.install()
    assert fake_net.popen == []


def test_install_not_newer(fake_net, monkeypatch):
    box, _ = ready_updater(fake_net, monkeypatch, ver="1.4.0")
    with pytest.raises(UpdateError, match="not newer"):
        box.u.install()
    assert fake_net.popen == []


def test_install_nothing_ready(fake_net, monkeypatch):
    box = Box(monkeypatch)
    with pytest.raises(UpdateError):
        box.u.install()


def test_install_tampered_after_download(fake_net, monkeypatch):
    box, p = ready_updater(fake_net, monkeypatch)
    p.write_bytes(SETUP[:-1] + b"!")
    with pytest.raises(UpdateError, match="changed"):
        box.u.install()
    assert fake_net.popen == [] and not box.u.quitting


def test_launch_rejects_foreign_path(fake_net, tmp_path):
    f = tmp_path / "evil.exe"
    f.write_bytes(b"x")
    with pytest.raises(UpdateError):
        updater.launch_installer(f, tmp_path / "l.log")
    with pytest.raises(UpdateError):
        updater.launch_installer("relative.exe", "l.log")
    assert fake_net.popen == []


def test_launch_falls_back_without_breakaway(fake_net, monkeypatch):
    d = fake_net.tmp / "ScribSalmon-update-x"
    d.mkdir()
    exe = d / "ScribSalmon-Setup-1.4.0.exe"
    exe.write_bytes(b"x")
    flags = []

    def popen(argv, **kw):
        flags.append(kw["creationflags"])
        if kw["creationflags"] & updater._CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError("job")

    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.launch_installer(exe, d / "install.log")
    assert len(flags) == 2 and not flags[1] & updater._CREATE_BREAKAWAY_FROM_JOB


def test_cleanup_stale(fake_net):
    import os
    import time
    old, new = fake_net.tmp / "ScribSalmon-update-old", fake_net.tmp / "ScribSalmon-update-new"
    other = fake_net.tmp / "unrelated"
    for d in (old, new, other):
        d.mkdir()
        (d / "ScribSalmon-Setup-1.4.0.exe").write_bytes(b"x")
    (old / "keep.txt").write_text("not ours")
    t = time.time() - 3 * 86400
    os.utime(old, (t, t))
    updater.cleanup_stale()
    assert not (old / "ScribSalmon-Setup-1.4.0.exe").exists() and (old / "keep.txt").exists()
    assert (new / "ScribSalmon-Setup-1.4.0.exe").exists() and (other / "ScribSalmon-Setup-1.4.0.exe").exists()


# ---------------------------------------------------------------- should_check

NOW = 1_000_000_000.0


@pytest.mark.parametrize("last,enabled,force,expected", [
    (NOW - 3600, True, False, False),
    (NOW - 25 * 3600, True, False, True),
    (NOW - 24 * 3600, True, False, True),
    (NOW + 10 * 86400, True, False, True),
    (NOW + 3600, True, False, False),
    (0.0, True, False, True),
    (0.0, False, False, False),
    (NOW - 3600, False, True, True),
    (NOW - 3600, True, True, True),
])
def test_should_check(last, enabled, force, expected):
    assert updater.should_check(last, NOW, enabled, force) is expected


# ---------------------------------------------------------------- check()

def test_check_dev_never_touches_network(monkeypatch):
    box = Box(monkeypatch, ver="dev")
    monkeypatch.setattr(updater, "_open", lambda *a: pytest.fail("network used"))
    for force in (False, True):
        r = box.u.check(force)
        assert r["available"] is False and r["current"] == "dev"
    assert box.saved == [] and box.emitted == []


def _serve_api(monkeypatch, data):
    import json
    monkeypatch.setattr(updater, "_open", lambda url, mb, acc: FakeResp(json.dumps(data).encode()))


def test_check_available_emits_and_saves(monkeypatch):
    box = Box(monkeypatch)
    _serve_api(monkeypatch, api_json())
    r = box.u.check(False)
    assert r["available"] and r["latest"] == V and r["can_install"] and not r["skipped"]
    assert box.emitted == [("update_available", {"version": V, "notes_url": r["notes_url"],
                                                 "size": len(SETUP), "install_mode": "installed"})]
    assert list(box.saved[0]) == ["last_update_check"]


def test_check_no_setup_asset_cannot_install(monkeypatch):
    box = Box(monkeypatch)
    d = api_json()
    del d["assets"][1]
    _serve_api(monkeypatch, d)
    r = box.u.check(False)
    assert r["available"] and r["can_install"] is False
    assert box.u.start_download() is False


def test_check_not_newer(monkeypatch):
    box = Box(monkeypatch, ver="1.4.0")
    _serve_api(monkeypatch, api_json())
    r = box.u.check(False)
    assert r["available"] is False and box.emitted == []
    assert box.saved  # HTTP succeeded: throttle stamp saved


def _boom(*a):
    raise urllib.error.URLError("offline")


def test_check_error_non_forced_is_silent(monkeypatch):
    box = Box(monkeypatch)
    monkeypatch.setattr(updater, "_open", _boom)
    r = box.u.check(False)
    assert r["available"] is False and box.emitted == [] and box.saved == []


def test_check_error_forced_raises(monkeypatch):
    box = Box(monkeypatch)
    monkeypatch.setattr(updater, "_open", _boom)
    with pytest.raises(UpdateError, match="Could not reach GitHub"):
        box.u.check(True)
    assert box.saved == []


def test_check_throttled_and_disabled(monkeypatch):
    import time
    box = Box(monkeypatch)
    monkeypatch.setattr(updater, "_open", lambda *a: pytest.fail("network used"))
    box.u._get_settings = lambda: {"check_updates": True, "last_update_check": time.time()}
    assert box.u.check(False)["available"] is False
    box.u._get_settings = lambda: {"check_updates": False, "last_update_check": 0.0}
    assert box.u.check(False)["available"] is False


def test_check_skipped_version(monkeypatch):
    box = Box(monkeypatch)
    box.u._get_settings = lambda: {"check_updates": True, "last_update_check": 0.0, "skipped_version": V}
    _serve_api(monkeypatch, api_json())
    r = box.u.check(False)
    assert r["available"] and r["skipped"] and box.emitted == []
    r = box.u.check(True)
    assert r["skipped"] and [e for e, _ in box.emitted] == ["update_available"]


def test_skip_validates(monkeypatch):
    box = Box(monkeypatch)
    box.u.skip("1.5.0")
    assert box.saved == [{"skipped_version": "1.5.0"}]
    with pytest.raises(UpdateError):
        box.u.skip("not-a-version")


def test_start_download_flow(fake_net, monkeypatch):
    box = Box(monkeypatch)
    _serve_api(monkeypatch, api_json())
    box.u.check(False)
    monkeypatch.setattr(updater, "_open", lambda url, mb, acc: (updater.check_url(url), FakeResp(
        fake_net.routes[url]))[1])
    assert box.u.start_download() is True
    box.u._thread.join(10)
    names = [e for e, _ in box.emitted]
    assert names[0] == "update_available" and "update_progress" in names and names[-1] == "update_ready"
    assert box.u.install() is True


def test_start_download_refused_in_source_mode(monkeypatch):
    box = Box(monkeypatch, mode="source")
    _serve_api(monkeypatch, api_json())
    box.u.check(False)
    assert box.u.start_download() is False


def test_download_error_emits(fake_net, monkeypatch):
    box = Box(monkeypatch)
    _serve_api(monkeypatch, api_json())
    box.u.check(False)
    monkeypatch.setattr(updater, "_open", _boom)
    assert box.u.start_download() is True
    box.u._thread.join(10)
    assert box.emitted[-1][0] == "update_error"
