"""GPU libraries downloader tests. No network: updater._open is faked; the wheel is a tiny zipfile."""
import hashlib
import io
import json
import threading
import types
import urllib.request
import zipfile
from collections import namedtuple

import pytest

from app import gpuconst, gpulibs, updater
from app.gpulibs import GpuLibsError
from tools import pin_gpu_libs

MEMBER_DATA = {
    "nvidia/cublas/bin/cublas64_12.dll": ("cublas64_12.dll", b"MZcublas" * 100),
    "nvidia/cublas/bin/cublasLt64_12.dll": ("cublasLt64_12.dll", b"MZcublasLt" * 300),
    "pkg.dist-info/licenses/License.txt": ("License.txt", b"NVIDIA EULA " * 20),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def build_wheel(extra=None, members=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for m, (_, data) in (members or MEMBER_DATA).items():
            z.writestr(m, data)
        z.writestr("nvidia/cublas/bin/other.dll", b"not allowed")
        for n, d in (extra or {}).items():
            z.writestr(n, d)
    return buf.getvalue()


class FakeResp:
    def __init__(self, data, content_length=None, chunk_hook=None):
        self._io = io.BytesIO(data)
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}
        self.hook = chunk_hook
        self.closed = False

    def read(self, n=-1):
        if self.hook:
            self.hook()
        return self._io.read(n)

    def close(self):
        self.closed = True

    def geturl(self):
        return gpuconst.URL


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Patched pins pointing at a fake wheel; returns a namespace with .wheel (bytes) and .opened (calls)."""
    wheel = build_wheel()
    members = {m: (n, len(d), sha(d)) for m, (n, d) in MEMBER_DATA.items()}
    root = tmp_path / "gpu-libs"
    monkeypatch.setattr(gpuconst, "URL", "https://files.pythonhosted.org/packages/x/fake.whl")
    monkeypatch.setattr(gpuconst, "SIZE", len(wheel))
    monkeypatch.setattr(gpuconst, "SHA256", sha(wheel))
    monkeypatch.setattr(gpuconst, "MEMBERS", members)
    monkeypatch.setattr(gpuconst, "REQUIRED_FREE_BYTES", 1000)
    monkeypatch.setattr(gpuconst, "libs_root", lambda: root)
    state = types.SimpleNamespace(wheel=wheel, root=root, opened=[])

    def set_wheel(data, pin=True):
        state.wheel = data
        if pin:
            monkeypatch.setattr(gpuconst, "SIZE", len(data))
            monkeypatch.setattr(gpuconst, "SHA256", sha(data))
    state.set_wheel = set_wheel

    def fake_open(url, max_bytes, accept, hosts=updater.ALLOWED_HOSTS, timeout=updater.TIMEOUT):
        updater.check_url(url, hosts)
        state.opened.append((url, max_bytes, hosts))
        return FakeResp(state.wheel, len(state.wheel))

    monkeypatch.setattr(updater, "_open", fake_open)
    return state


def leftovers(root):
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def test_install_success_atomic(env):
    events = []
    final = gpulibs.install(lambda *a: events.append(a))
    assert final == env.root / gpuconst.FOLDER_NAME
    assert leftovers(env.root) == [gpuconst.FOLDER_NAME]          # staging and wheel are gone
    assert sorted(p.name for p in final.iterdir()) == ["License.txt", "cublas64_12.dll",
                                                       "cublasLt64_12.dll", "manifest.json"]
    assert (final / "cublas64_12.dll").read_bytes() == MEMBER_DATA["nvidia/cublas/bin/cublas64_12.dll"][1]
    man = json.loads((final / "manifest.json").read_text())
    assert man["package"] == gpuconst.PACKAGE and man["version"] == gpuconst.VERSION and man["installed_at"]
    assert man["files"]["cublas64_12.dll"]["size"] == len(MEMBER_DATA["nvidia/cublas/bin/cublas64_12.dll"][1])
    # the pinned host list is what is passed to the opener
    assert env.opened[0][2] == gpuconst.ALLOWED_HOSTS


def test_progress_events_order(env):
    events = []
    gpulibs.install(lambda *a: events.append(a))
    phases = [e[0] for e in events]
    order = {"download": 0, "verify": 1, "extract": 2}
    assert [order[p] for p in phases] == sorted(order[p] for p in phases)
    assert set(phases) == {"download", "verify", "extract"}
    for ph in order:
        pcts = [e[1] for e in events if e[0] == ph]
        assert pcts == sorted(pcts) and pcts[-1] == 100


def test_reinstall_replaces_existing(env):
    gpulibs.install()
    gpulibs.install()
    assert leftovers(env.root) == [gpuconst.FOLDER_NAME]


def test_hash_mismatch_aborts_and_leaves_nothing(env, monkeypatch):
    bad = bytearray(env.wheel)
    bad[100] ^= 0xFF
    env.set_wheel(bytes(bad), pin=False)
    with pytest.raises(GpuLibsError, match="Checksum mismatch"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_wheel_too_large(env, monkeypatch):
    big = env.wheel + b"x" * 50
    monkeypatch.setattr(updater, "_open", lambda *a, **k: FakeResp(big))   # no Content-Length: caught while streaming
    with pytest.raises(GpuLibsError, match="larger than expected"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_truncated(env, monkeypatch):
    monkeypatch.setattr(updater, "_open", lambda *a, **k: FakeResp(env.wheel[:-10]))
    with pytest.raises(GpuLibsError, match="incomplete"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_content_length_mismatch(env, monkeypatch):
    monkeypatch.setattr(updater, "_open", lambda *a, **k: FakeResp(env.wheel, len(env.wheel) + 1))
    with pytest.raises(GpuLibsError, match="unexpected file size"):
        gpulibs.install()
    assert leftovers(env.root) == []


@pytest.mark.parametrize("url", [
    "http://files.pythonhosted.org/x.whl",
    "https://evil.example.com/x.whl",
    "https://user:pw@files.pythonhosted.org/x.whl",
    "https://files.pythonhosted.org:8443/x.whl",
])
def test_blocked_urls(env, monkeypatch, url):
    monkeypatch.setattr(gpuconst, "URL", url)
    with pytest.raises(GpuLibsError, match="Blocked URL"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_redirect_to_blocked_host_refused():
    h = updater._SafeRedirect(gpuconst.ALLOWED_HOSTS)
    req = urllib.request.Request("https://files.pythonhosted.org/a")
    with pytest.raises(updater.UpdateError):
        h.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/a")
    with pytest.raises(updater.UpdateError):
        h.redirect_request(req, None, 302, "Found", {}, "http://files.pythonhosted.org/a")
    # the update-check host list is NOT accepted for the GPU download
    with pytest.raises(updater.UpdateError):
        h.redirect_request(req, None, 302, "Found", {}, "https://github.com/a")
    # default behaviour of the updater is unchanged
    updater.check_url("https://github.com/x")
    with pytest.raises(updater.UpdateError):
        updater.check_url("https://files.pythonhosted.org/x")


@pytest.mark.parametrize("name", ["../x.dll", "/abs/x.dll", "C:\\x.dll"])
def test_zip_slip_names_never_written(env, tmp_path, name):
    # a malicious wheel contains path-traversal entries plus the legit members: only pinned members are written
    env.set_wheel(build_wheel(extra={name: b"evil"}))
    gpulibs.install()
    assert leftovers(env.root) == [gpuconst.FOLDER_NAME]
    assert not (tmp_path / "x.dll").exists() and not (env.root.parent / "x.dll").exists()
    assert not (env.root / gpuconst.FOLDER_NAME / "other.dll").exists()
    assert not (env.root / gpuconst.FOLDER_NAME / "x.dll").exists()


def test_pinned_member_missing_from_wheel(env):
    env.set_wheel(build_wheel(members={k: v for k, v in list(MEMBER_DATA.items())[:2]}))
    with pytest.raises(GpuLibsError, match="missing from the package"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_member_size_mismatch_fails(env, monkeypatch):
    m = dict(gpuconst.MEMBERS)
    k = "nvidia/cublas/bin/cublas64_12.dll"
    n, size, h = m[k]
    m[k] = (n, size + 1, h)
    monkeypatch.setattr(gpuconst, "MEMBERS", m)
    with pytest.raises(GpuLibsError, match="Unexpected size"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_member_hash_mismatch_fails(env, monkeypatch):
    m = dict(gpuconst.MEMBERS)
    k = "nvidia/cublas/bin/cublas64_12.dll"
    n, size, h = m[k]
    m[k] = (n, size, "0" * 64)
    monkeypatch.setattr(gpuconst, "MEMBERS", m)
    with pytest.raises(GpuLibsError, match="Checksum mismatch for cublas64_12.dll"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_not_a_zip(env, monkeypatch):
    data = b"this is not a zip" * 10
    monkeypatch.setattr(gpuconst, "SIZE", len(data))
    monkeypatch.setattr(gpuconst, "SHA256", sha(data))
    env.set_wheel(data)
    with pytest.raises(GpuLibsError, match="not a valid wheel"):
        gpulibs.install()
    assert leftovers(env.root) == []


def test_disk_space_refusal(env, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(gpulibs.shutil, "disk_usage", lambda p: Usage(10 ** 12, 10 ** 12 - 10, 10))
    with pytest.raises(GpuLibsError, match="Not enough free disk space"):
        gpulibs.install()
    assert not env.opened                                            # refused before any network access
    assert leftovers(env.root) == []


def test_check_disk_ok(env):
    gpulibs.check_disk(env.root / "does" / "not" / "exist")           # walks up to an existing parent


def test_cancel_cleans_staging(env, monkeypatch):
    cancel = threading.Event()
    calls = {"n": 0}

    def hook():
        calls["n"] += 1
        if calls["n"] == 1:
            cancel.set()
    monkeypatch.setattr(updater, "_open", lambda *a, **k: FakeResp(env.wheel, len(env.wheel), hook))
    with pytest.raises(gpulibs.GpuLibsCancelled):
        gpulibs.install(None, cancel)
    assert leftovers(env.root) == []


def test_cancel_during_extract_cleans_staging(env):
    cancel = threading.Event()

    def on_progress(phase, *a):
        if phase == "extract":
            cancel.set()
    with pytest.raises(gpulibs.GpuLibsCancelled):
        gpulibs.install(on_progress, cancel)
    assert leftovers(env.root) == []


def test_cleanup_stale(env):
    import os
    import time

    env.root.mkdir(parents=True)
    dead = env.root / ".staging-dead"
    dead.mkdir()
    (dead / "w.whl").write_bytes(b"x")
    old = time.time() - 2 * gpulibs.STALE_AFTER
    os.utime(dead, (old, old))
    fresh = env.root / ".staging-running"  # e.g. another window mid-download: must survive
    fresh.mkdir()
    keep = env.root / "nvidia-cublas-cu12-1.0"
    keep.mkdir()
    gpulibs.cleanup_stale()
    assert sorted(leftovers(env.root)) == sorted([keep.name, fresh.name])


def test_installer_class_events_and_on_installed_first(env):
    events = []
    order = []

    def emit(ev, payload):
        order.append(ev)
        events.append((ev, payload))
    done = threading.Event()

    def on_installed():
        order.append("on_installed")
        return {"state": "ready"}

    def emit2(ev, p):
        emit(ev, p)
        if ev == "gpu_ready":
            done.set()
    inst = gpulibs.GpuLibsInstaller(emit2, on_installed)
    assert inst.start() is True
    assert done.wait(20)
    assert order.index("on_installed") < order.index("gpu_ready")
    ready = [p for e, p in events if e == "gpu_ready"][0]
    assert ready == {"status": {"state": "ready"}}
    prog = [p for e, p in events if e == "gpu_progress"]
    assert prog and set(prog[0]) == {"pct", "received", "total", "phase"}
    inst._thread.join(5)
    assert not inst.in_progress


def test_installer_class_error_and_single_flight(env, monkeypatch):
    gate = threading.Event()

    def slow_open(*a, **k):
        gate.wait(10)
        return FakeResp(env.wheel[:-5], len(env.wheel))
    monkeypatch.setattr(updater, "_open", slow_open)
    events = []
    done = threading.Event()

    def emit(ev, p):
        events.append((ev, p))
        if ev == "gpu_error":
            done.set()
    inst = gpulibs.GpuLibsInstaller(emit, lambda: None)
    assert inst.start() is True
    assert inst.in_progress and inst.start() is False                 # one download at a time
    gate.set()
    assert done.wait(20)
    assert "message" in [p for e, p in events if e == "gpu_error"][0]
    inst._thread.join(5)
    assert leftovers(env.root) == []
    assert not any(e == "gpu_ready" for e, _ in events)
    assert inst.start() is True                                       # retry is a fresh start
    inst._thread.join(20)


def test_installer_cancel_emits_no_error(env, monkeypatch):
    started = threading.Event()

    def hook():
        started.set()
        import time
        time.sleep(0.05)
    monkeypatch.setattr(updater, "_open", lambda *a, **k: FakeResp(env.wheel * 1, len(env.wheel), hook))
    events = []
    inst = gpulibs.GpuLibsInstaller(lambda e, p: events.append(e), None)
    inst.start()
    assert started.wait(10)
    assert inst.cancel() is True
    inst._thread.join(10)
    assert "gpu_error" not in events and "gpu_ready" not in events
    assert leftovers(env.root) == []
    assert inst.cancel() is False


def test_real_pins_are_consistent():
    c = gpuconst
    assert c.URL.startswith("https://files.pythonhosted.org/") and c.URL.endswith(c.WHEEL_NAME)
    assert len(c.SHA256) == 64 and c.SIZE > 0
    assert {m[0] for m in c.MEMBERS.values()} >= set(c.REQUIRED_DLLS)


# ---------------------------------------------------------------- tools/pin_gpu_libs.py

def pypi_json(**file_over):
    f = {"filename": "nvidia_cublas_cu12-1.0-py3-none-win_amd64.whl", "yanked": False,
         "url": "https://files.pythonhosted.org/packages/ab/cd/x.whl", "size": 5, "digests": {"sha256": "A" * 64}}
    f.update(file_over)
    other = {"filename": "nvidia_cublas_cu12-1.0-py3-none-manylinux_x86_64.whl", "url": "https://x/y", "size": 1,
             "digests": {"sha256": "b" * 64}}
    return {"info": {"version": "1.0"}, "urls": [other, f]}


def test_parse_pypi_json_ok():
    r = pin_gpu_libs.parse_pypi_json(pypi_json(), "1.0")
    assert r["size"] == 5 and r["sha256"] == "a" * 64 and r["url"].startswith("https://files.pythonhosted.org/")


@pytest.mark.parametrize("over", [{"yanked": True}, {"url": "https://evil.example.com/x.whl"},
                                  {"url": "http://files.pythonhosted.org/x.whl"}, {"digests": {}}, {"size": 0}])
def test_parse_pypi_json_rejects(over):
    with pytest.raises(ValueError):
        pin_gpu_libs.parse_pypi_json(pypi_json(**over), "1.0")


def test_parse_pypi_json_wrong_version_or_no_wheel():
    with pytest.raises(ValueError):
        pin_gpu_libs.parse_pypi_json(pypi_json(), "2.0")
    d = pypi_json()
    d["urls"] = d["urls"][:1]
    with pytest.raises(ValueError):
        pin_gpu_libs.parse_pypi_json(d, "1.0")


def test_record_entries_and_render():
    import base64
    data = b"hello"
    b64 = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("p-1.0.dist-info/RECORD", f"nvidia/cublas/bin/cublas64_12.dll,sha256={b64},{len(data)}\n"
                                              "nvidia/cublas/bin/other.dll,sha256=AAAA,3\n")
    with zipfile.ZipFile(buf) as z:
        m = pin_gpu_libs.record_entries(z)
    assert m == {"nvidia/cublas/bin/cublas64_12.dll": (5, hashlib.sha256(data).hexdigest())}
    text = pin_gpu_libs.render("1.0", {"url": "https://files.pythonhosted.org/x", "size": 5, "sha256": "a" * 64,
                                      "filename": "w.whl"}, m)
    assert 'VERSION = "1.0"' in text and hashlib.sha256(data).hexdigest() in text
