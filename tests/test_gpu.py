"""GPU diagnostics: parsing, DLL lookup, manifest validation, activation order, status. No GPU, no network."""
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from app import gpu, gpuconst


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    gpu._reset_for_tests()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("CUDA_PATH", raising=False)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "win"))
    monkeypatch.setenv("PATH", "")
    yield
    gpu._reset_for_tests()


def _make_install(version="12.9.2.10", dlls=gpuconst.REQUIRED_DLLS, sizes=None):
    folder = gpuconst.libs_root() / f"nvidia-cublas-cu12-{version}"
    folder.mkdir(parents=True)
    files = {}
    for n in dlls:
        data = b"x" * 10
        (folder / n).write_bytes(data)
        files[n] = {"size": (sizes or {}).get(n, len(data)), "sha256": "0" * 64}
    (folder / gpuconst.MANIFEST_NAME).write_text(json.dumps(
        {"package": gpuconst.PACKAGE, "version": version, "files": files, "installed_at": "now"}), encoding="utf-8")
    return folder


# ---- nvidia-smi parsing / query

def test_parse_smi_rtx4080():
    g = gpu.parse_smi_csv("NVIDIA GeForce RTX 4080, 616.92, 16376, 8.9\r\n")
    assert g == [{"name": "NVIDIA GeForce RTX 4080", "driver": "616.92", "vram_mb": 16376, "compute_cap": "8.9"}]


def test_parse_smi_multi_and_na():
    g = gpu.parse_smi_csv("GPU A, 535.1, 8192, 7.5\nGPU B, 535.1, [N/A], [Not Supported]\n\n")
    assert [x["name"] for x in g] == ["GPU A", "GPU B"]
    assert g[1]["vram_mb"] is None and g[1]["compute_cap"] is None
    assert gpu.parse_smi_csv("") == []


def test_parse_smi_without_compute_cap():
    assert gpu.parse_smi_csv("GPU A, 535.1, 8192")[0]["compute_cap"] is None


def _fake_smi_exe(monkeypatch, tmp_path):
    exe = tmp_path / "win" / "System32" / "nvidia-smi.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    return exe


def test_query_smi_runs_with_safe_args(monkeypatch, tmp_path):
    exe = _fake_smi_exe(monkeypatch, tmp_path)
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "NVIDIA GeForce RTX 4080, 616.92, 16376, 8.9\r\n", "")
    monkeypatch.setattr(subprocess, "run", run)
    assert gpu.query_nvidia_smi()[0]["name"] == "NVIDIA GeForce RTX 4080"
    cmd, kw = calls[0]
    assert cmd[0] == str(exe)
    assert "--query-gpu=name,driver_version,memory.total,compute_cap" in cmd
    assert kw["timeout"] == 5 and kw["stdin"] == subprocess.DEVNULL


def test_query_smi_retries_without_compute_cap(monkeypatch, tmp_path):
    _fake_smi_exe(monkeypatch, tmp_path)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if "compute_cap" in cmd[1]:
            return subprocess.CompletedProcess(cmd, 2, "", "invalid")
        return subprocess.CompletedProcess(cmd, 0, "GPU A, 500.1, 4096\n", "")
    monkeypatch.setattr(subprocess, "run", run)
    assert gpu.query_nvidia_smi()[0]["compute_cap"] is None
    assert len(calls) == 2


def test_query_smi_timeout_and_missing(monkeypatch, tmp_path):
    assert gpu.query_nvidia_smi() == []  # no exe anywhere
    _fake_smi_exe(monkeypatch, tmp_path)

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)
    monkeypatch.setattr(subprocess, "run", boom)
    assert gpu.query_nvidia_smi() == []


def test_driver_cuda_version_format(monkeypatch):
    import ctypes

    class FakeFn:
        argtypes = restype = None

        def __call__(self, ref):
            ref._obj.value = 13040
            return 0

    class FakeDll:
        cuDriverGetVersion = FakeFn()
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(ctypes, "WinDLL", lambda p: FakeDll(), raising=False)
    assert gpu.driver_cuda_version() == "13.4"


# ---- DLL lookup

def test_find_dll_order_and_ours_wins(tmp_path, monkeypatch):
    ours = _make_install()
    other = tmp_path / "other"
    other.mkdir()
    (other / "cublas64_12.dll").write_bytes(b"y")
    monkeypatch.setenv("PATH", str(other))
    assert gpu.find_dll("cublas64_12.dll") == ours / "cublas64_12.dll"
    assert gpu.search_dirs()[0] == ours


def test_find_dll_cuda_path_before_path(tmp_path, monkeypatch):
    cuda = tmp_path / "cuda"
    (cuda / "bin").mkdir(parents=True)
    (cuda / "bin" / "cublas64_12.dll").write_bytes(b"y")
    other = tmp_path / "other"
    other.mkdir()
    (other / "cublas64_12.dll").write_bytes(b"y")
    monkeypatch.setenv("CUDA_PATH", str(cuda))
    monkeypatch.setenv("PATH", str(other))
    assert gpu.find_dll("cublas64_12.dll") == cuda / "bin" / "cublas64_12.dll"


def test_missing_dlls_and_cublas13_hint(tmp_path, monkeypatch):
    assert gpu.missing_dlls() == list(gpuconst.REQUIRED_DLLS)
    d13 = tmp_path / "c13"
    d13.mkdir()
    (d13 / "cublas64_13.dll").write_bytes(b"y")
    monkeypatch.setenv("PATH", str(d13))
    monkeypatch.setattr(gpu, "query_nvidia_smi", lambda: [{"name": "G", "driver": "616.92", "vram_mb": 1,
                                                          "compute_cap": "8.9"}])
    monkeypatch.setattr(gpu, "driver_cuda_version", lambda: "13.4")
    st = gpu.status(cuda_count_fn=lambda: 1)
    assert st["state"] == "libs_missing"
    assert "CUDA 13" in st["hint"] and "CUDA 12" in st["hint"]


# ---- manifest / installed_libs

def test_installed_libs_valid_and_newest():
    _make_install("12.9.2.10")
    newer = _make_install("12.10.0.1")
    assert gpu.installed_libs() == (newer, "12.10.0.1")


def test_installed_libs_rejects_bad(tmp_path):
    assert gpu.installed_libs() is None
    f = _make_install(sizes={"cublas64_12.dll": 999})
    assert gpu.installed_libs() is None  # size mismatch
    (f / gpuconst.MANIFEST_NAME).write_text("not json", encoding="utf-8")
    assert gpu.installed_libs() is None
    (f / gpuconst.MANIFEST_NAME).write_text(json.dumps({"package": "x", "version": "1", "files": {}}),
                                            encoding="utf-8")
    assert gpu.installed_libs() is None  # required dlls absent from manifest


def test_installed_libs_missing_required():
    _make_install(dlls=("cublas64_12.dll",))
    assert gpu.installed_libs() is None


# ---- activate

def test_activate_noop_without_install(monkeypatch):
    monkeypatch.setenv("PATH", "abc")
    gpu.activate(preload=True)
    assert os.environ["PATH"] == "abc"


def test_activate_path_dll_dir_and_preload_order(monkeypatch):
    import ctypes
    folder = _make_install()
    monkeypatch.setenv("PATH", "abc")
    added, loaded = [], []
    monkeypatch.setattr(os, "add_dll_directory", lambda p: added.append(p) or object(), raising=False)

    class Dll:
        pass
    monkeypatch.setattr(ctypes, "WinDLL", lambda p: loaded.append(p) or Dll(), raising=False)
    gpu.activate()
    assert os.environ["PATH"].split(os.pathsep)[0] == str(folder)
    assert added == [str(folder)] and loaded == []
    gpu.activate(preload=True)
    assert [Path(p).name for p in loaded] == ["cublasLt64_12.dll", "cublas64_12.dll"]
    assert all(Path(p).is_absolute() for p in loaded)
    gpu.activate(preload=True)  # idempotent
    assert len(loaded) == 2 and len(added) == 1
    assert os.environ["PATH"].count(str(folder)) == 1
    assert "CUDA_PATH" not in os.environ


def test_activate_preload_failure_tolerated(monkeypatch):
    import ctypes
    _make_install()

    def boom(p):
        raise OSError("bad dll")
    monkeypatch.setattr(ctypes, "WinDLL", boom, raising=False)
    gpu.activate(preload=True)  # must not raise


# ---- explain / status

@pytest.mark.parametrize("raw,needle", [
    ("Library cublas64_12.dll is not found or cannot be loaded", "cuBLAS 12 libraries are missing"),
    ("CUDA driver version is insufficient for CUDA runtime version", "driver"),
    ("CUDA failed with error out of memory", "smaller"),
    ("Requested float16 compute type, but the target device do not support efficient float16", "float16"),
])
def test_explain_mapping(raw, needle):
    assert needle in gpu.explain(raw)


def test_explain_passthrough():
    assert gpu.explain("weird thing") == "weird thing"


def _smi(monkeypatch, driver="616.92", gpus=True):
    monkeypatch.setattr(gpu, "query_nvidia_smi", lambda: (
        [{"name": "NVIDIA GeForce RTX 4080", "driver": driver, "vram_mb": 16376, "compute_cap": "8.9"}]
        if gpus else []))
    monkeypatch.setattr(gpu, "driver_cuda_version", lambda: "13.4")


def test_status_no_gpu(monkeypatch):
    _smi(monkeypatch, gpus=False)
    st = gpu.status(cuda_count_fn=lambda: 0)
    assert st["state"] == "no_gpu" and not st["gpu_present"] and st["gpu_name"] is None


def test_status_driver_old(monkeypatch):
    _smi(monkeypatch, driver="472.12")
    assert gpu.status(cuda_count_fn=lambda: 1)["state"] == "driver_old"


def test_status_libs_missing_then_ready(monkeypatch):
    _smi(monkeypatch)
    st = gpu.status(cuda_count_fn=lambda: 1)
    assert st["state"] == "libs_missing" and st["missing_dlls"] == list(gpuconst.REQUIRED_DLLS)
    _make_install()
    st = gpu.status(cuda_count_fn=lambda: 1)
    assert st["state"] == "ready" and st["cuda_ok"] and st["libs_installed_version"] == "12.9.2.10"
    assert st["gpu_name"] == "NVIDIA GeForce RTX 4080" and st["driver_cuda"] == "13.4"
    assert st["vram_mb"] == 16376 and st["compute_cap"] == "8.9" and st["cuda_device_count"] == 1
    assert gpu.status(cuda_count_fn=lambda: 0)["state"] == "failed"


def test_status_cached(monkeypatch):
    n = []
    monkeypatch.setattr(gpu, "query_nvidia_smi", lambda: n.append(1) or [])
    gpu.status()
    gpu.status()
    assert len(n) == 1
    gpu.invalidate_cache()
    gpu.status()
    assert len(n) == 2


def test_with_engine():
    base = {"state": "ready", "message": "GPU ready.", "hint": ""}
    assert gpu.with_engine(base, "cuda")["state"] == "active"
    f = gpu.with_engine(base, "cpu", "Library cublas64_12.dll is not found")
    assert f["state"] == "failed" and "cuBLAS 12" in f["message"]
    assert gpu.with_engine(base, "cpu")["state"] == "ready"
    assert base["state"] == "ready"  # input not mutated
    assert gpu.with_engine({"state": "no_gpu"}, "cpu", "x")["state"] == "no_gpu"


# ---- guard: CTranslate2 must only need cublas64_12.dll

def test_ctranslate2_only_needs_cublas12():
    spec = importlib.util.find_spec("ctranslate2")
    if spec is None or not spec.submodule_search_locations:
        pytest.skip("ctranslate2 not installed")
    root = Path(list(spec.submodule_search_locations)[0])
    dll = next(iter(sorted(root.parent.glob("ctranslate2*/ctranslate2*.dll")) + sorted(root.glob("ctranslate2*.dll"))),
               None)
    if dll is None:
        pytest.skip("ctranslate2.dll not found")
    names = {m.decode().lower() for m in re.findall(rb"(?i)(?:cublas|cudnn)\w*64_\d+\.dll", dll.read_bytes())}
    assert names == {"cublas64_12.dll"}, names
