"""NVIDIA GPU diagnostics and cuBLAS 12 activation for the CTranslate2 engine (Windows).

CTranslate2 (CUDA_DYNAMIC_LOADING) only needs `cublas64_12.dll` (+ the NVIDIA driver). We never set CUDA_PATH
(CT2 would SetDllDirectory it and override the bundled folder). Instead our downloaded DLLs are loaded by
absolute path before the model loads, so Windows hands the already-loaded module to CT2's bare-name LoadLibrary.
Nothing here loads a model or needs a GPU context.
"""
import csv
import ctypes
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import gpuconst

log = logging.getLogger(__name__)

MIN_DRIVER = (528, 33)  # CUDA 12 on Windows
CUBLAS13 = "cublas64_13.dll"
_CACHE_TTL = 30.0
_CREATE_NO_WINDOW = 0x08000000

_lock = threading.RLock()
_activated = False
_preloaded = False
_dll_dir_handle = None
_loaded_dlls: list = []  # keep ctypes handles alive
_cache: Optional[tuple] = None


def _home_short(p) -> str:
    s = str(p)
    home = str(Path.home())
    if home and s.lower().startswith(home.lower()):
        return "~" + s[len(home):]
    return s


def _system32() -> Path:
    return Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows") / "System32"


# ---------------------------------------------------------------- installed libraries

def _ver_key(v: str):
    return tuple(int(part) if part.isdigit() else 0 for part in str(v).split("."))


def _valid_manifest(folder: Path) -> Optional[dict]:
    try:
        m = json.loads((folder / gpuconst.MANIFEST_NAME).read_text(encoding="utf-8"))
        if not isinstance(m, dict) or not isinstance(m.get("package"), str) or not isinstance(m.get("version"), str):
            return None
        files = m.get("files")
        if not isinstance(files, dict):
            return None
        for name in gpuconst.REQUIRED_DLLS:
            if name not in files:
                return None
        for name, rec in files.items():
            if not isinstance(rec, dict) or not isinstance(rec.get("size"), int):
                return None
            if "/" in name or "\\" in name or (folder / name).stat().st_size != rec["size"]:
                return None
        return m
    except (OSError, ValueError):
        return None


def installed_libs() -> Optional[tuple]:
    """(folder, version) of the newest valid install under libs_root(), else None."""
    root = gpuconst.libs_root()
    try:
        entries = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return None
    best = None
    for p in entries:
        m = _valid_manifest(p)
        if m is None:
            continue
        key = _ver_key(m["version"])
        if best is None or key > best[0]:
            best = (key, p, m["version"])
    return (best[1], best[2]) if best else None


# ---------------------------------------------------------------- DLL lookup

def search_dirs() -> list:
    """Directories in the order LoadLibrary would try for our purposes."""
    dirs = []
    inst = installed_libs()
    if inst:
        dirs.append(inst[0])
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        dirs.append(Path(cuda_path) / "bin")
    dirs.append(_system32())
    dirs.append(_system32().parent)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if entry:
            dirs.append(Path(entry))
    seen, out = set(), []
    for d in dirs:
        k = os.path.normcase(str(d))
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


def find_dll(name: str, dirs=None) -> Optional[Path]:
    for d in (search_dirs() if dirs is None else dirs):
        try:
            p = Path(d) / name
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def missing_dlls(dirs=None) -> list:
    dirs = search_dirs() if dirs is None else dirs
    return [n for n in gpuconst.REQUIRED_DLLS if find_dll(n, dirs) is None]


# ---------------------------------------------------------------- activation

def activate(preload: bool = False):
    """Make the downloaded cuBLAS findable (PATH + add_dll_directory); with preload, load both DLLs by absolute
    path (Lt first) so CTranslate2's bare-name LoadLibraryA gets the already-loaded modules. Idempotent."""
    global _activated, _preloaded, _dll_dir_handle
    with _lock:
        inst = installed_libs()
        if inst is None:
            return
        folder = inst[0]
        if not _activated:
            cur = os.environ.get("PATH", "")
            parts = cur.split(os.pathsep) if cur else []
            if not parts or os.path.normcase(parts[0]) != os.path.normcase(str(folder)):
                os.environ["PATH"] = str(folder) + (os.pathsep + cur if cur else "")
            if hasattr(os, "add_dll_directory"):
                try:
                    _dll_dir_handle = os.add_dll_directory(str(folder))
                except OSError as e:
                    log.warning("add_dll_directory failed: %s", e)
            _activated = True
            log.info("GPU libraries activated from %s", _home_short(folder))
        if preload and not _preloaded:
            try:
                lt = ctypes.WinDLL(str(folder / "cublasLt64_12.dll"))
                cb = ctypes.WinDLL(str(folder / "cublas64_12.dll"))
            except (OSError, AttributeError) as e:
                log.warning("cuBLAS preload failed: %s", e)
                return
            _loaded_dlls.extend([lt, cb])
            _preloaded = True
            ver = _cublas_version(cb)
            log.info("cuBLAS %s loaded from %s", ver or "?", _home_short(folder))


def _cublas_version(dll) -> Optional[str]:
    try:
        fn = dll.cublasGetProperty
        fn.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        fn.restype = ctypes.c_int
        vals = []
        for prop in (0, 1, 2):  # MAJOR, MINOR, PATCH
            v = ctypes.c_int()
            if fn(prop, ctypes.byref(v)) != 0:
                return None
            vals.append(v.value)
        return ".".join(map(str, vals))
    except Exception:
        return None


def _reset_for_tests():
    global _activated, _preloaded, _dll_dir_handle, _cache
    _activated = _preloaded = False
    _dll_dir_handle = None
    _loaded_dlls.clear()
    _cache = None


# ---------------------------------------------------------------- error explanation

def explain(err) -> str:
    s = str(err)
    low = s.lower()
    if "cublas" in low and ("not found" in low or "cannot be loaded" in low or "could not load" in low):
        return ("NVIDIA cuBLAS 12 libraries are missing "
                "(Settings -> GPU -> Download GPU libraries)")
    if "driver version is insufficient" in low or "insufficient for cuda" in low:
        return "NVIDIA driver is too old for CUDA 12: update it to version 528.33 or newer"
    if "out of memory" in low:
        return "GPU ran out of memory: choose a smaller Whisper model or use CPU"
    if "float16" in low and ("not support" in low or "do not support" in low or "unsupported" in low):
        return "This GPU does not support float16 (too old): use CPU"
    return s


# ---------------------------------------------------------------- nvidia-smi / driver

def parse_smi_csv(text: str) -> list:
    """Rows 'name, driver, memory.total[, compute_cap]' -> list of dicts. Tolerates [N/A]/[Not Supported]."""
    def clean(v):
        return None if (not v or v.startswith("[")) else v

    gpus = []
    for row in csv.reader(io.StringIO(text or ""), skipinitialspace=True):
        row = [c.strip() for c in row]
        if len(row) < 3 or not row[0]:
            continue
        try:
            vram = int(float(clean(row[2]))) if clean(row[2]) else None
        except ValueError:
            vram = None
        gpus.append({"name": row[0], "driver": clean(row[1]), "vram_mb": vram,
                     "compute_cap": clean(row[3]) if len(row) > 3 else None})
    return gpus


def _smi_paths() -> list:
    out = [_system32() / "nvidia-smi.exe"]
    pf = os.environ.get("ProgramFiles")
    if pf:
        out.append(Path(pf) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe")
    return out


def _run_smi(exe: Path, fields: str):
    return subprocess.run(
        [str(exe), f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0)


def query_nvidia_smi() -> list:
    """List of GPUs via nvidia-smi (fixed locations only, never PATH). [] when unavailable."""
    for exe in _smi_paths():
        if not exe.is_file():
            continue
        try:
            r = _run_smi(exe, "name,driver_version,memory.total,compute_cap")
            if r.returncode != 0:
                r = _run_smi(exe, "name,driver_version,memory.total")
            if r.returncode != 0:
                log.info("nvidia-smi exited with %s", r.returncode)
                continue
            return parse_smi_csv(r.stdout)
        except (OSError, subprocess.SubprocessError) as e:
            log.info("nvidia-smi failed: %s", e)
    return []


def driver_cuda_version() -> Optional[str]:
    """CUDA version the driver supports ('13.4'), via nvcuda.dll cuDriverGetVersion (no GPU context)."""
    if os.name != "nt":
        return None
    try:
        dll = ctypes.WinDLL(str(_system32() / "nvcuda.dll"))
        v = ctypes.c_int()
        fn = dll.cuDriverGetVersion
        fn.argtypes = [ctypes.POINTER(ctypes.c_int)]
        fn.restype = ctypes.c_int
        if fn(ctypes.byref(v)) != 0:
            return None
        return f"{v.value // 1000}.{(v.value % 1000) // 10}"
    except Exception as e:
        log.info("cuDriverGetVersion failed: %s", e)
        return None


def _driver_tuple(v: Optional[str]):
    try:
        return tuple(int(x) for x in (v or "").split("."))
    except ValueError:
        return None


def _default_cuda_count() -> int:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


# ---------------------------------------------------------------- status

def _build_status(cuda_count_fn) -> dict:
    gpus = query_nvidia_smi()
    first = gpus[0] if gpus else {}
    driver = first.get("driver")
    dirs = search_dirs()
    dlls = {}
    for n in gpuconst.REQUIRED_DLLS:
        p = find_dll(n, dirs)
        dlls[n] = str(p) if p else None
    missing = [n for n, p in dlls.items() if p is None]
    inst = installed_libs()
    gpu_present = bool(gpus)
    count = 0
    if gpu_present:
        try:
            count = int((cuda_count_fn or _default_cuda_count)())
        except Exception:
            count = 0
    dtuple = _driver_tuple(driver)
    hint = ""
    if not gpu_present:
        state, message = "no_gpu", "No NVIDIA GPU detected - using CPU."
    elif dtuple is not None and dtuple < MIN_DRIVER:
        state = "driver_old"
        message = f"NVIDIA driver {driver} is too old for CUDA 12."
        hint = "Update the NVIDIA driver to 528.33 or newer."
    elif missing:
        state, message = "libs_missing", "NVIDIA cuBLAS 12 libraries are missing."
        hint = "Click Download GPU libraries."
        if find_dll(CUBLAS13, dirs):
            hint = "CUDA 13 cuBLAS was found, but CUDA 12 cuBLAS is needed. " + hint
    elif count > 0:
        state, message = "ready", "GPU ready."
    else:
        state, message = "failed", "GPU libraries found but CUDA reports no usable device."
        hint = "Update the NVIDIA driver and restart ScribSalmon."
    return {
        "state": state, "gpu_present": gpu_present, "gpus": gpus,
        "gpu_name": first.get("name"), "driver": driver,
        "driver_cuda": driver_cuda_version() if gpu_present else None,
        "vram_mb": first.get("vram_mb"), "compute_cap": first.get("compute_cap"),
        "cuda_device_count": count, "required_dlls": list(gpuconst.REQUIRED_DLLS),
        "dlls": dlls, "missing_dlls": missing,
        "libs_dir": str(inst[0]) if inst else None, "libs_installed_version": inst[1] if inst else None,
        "cuda_ok": gpu_present and not missing and count > 0, "message": message, "hint": hint,
    }


def status(cuda_count_fn: Optional[Callable[[], int]] = None) -> dict:
    """Diagnostics dict (cached 30 s unless a custom cuda_count_fn is given). Never loads a model."""
    global _cache
    with _lock:
        now = time.monotonic()
        if cuda_count_fn is None and _cache and now - _cache[0] < _CACHE_TTL:
            return dict(_cache[1])
        st = _build_status(cuda_count_fn)
        if cuda_count_fn is None:
            _cache = (now, st)
        return dict(st)


def invalidate_cache():
    global _cache
    with _lock:
        _cache = None


def with_engine(st: dict, device: Optional[str], fallback_reason: Optional[str] = None) -> dict:
    """Overlay the live engine state: device 'cuda' -> active; a CPU fallback after a ready status -> failed."""
    st = dict(st)
    if device == "cuda":
        st["state"] = "active"
        st["message"] = "GPU active."
        st["hint"] = ""
    elif fallback_reason and st.get("state") in ("ready", "failed"):
        st["state"] = "failed"
        st["message"] = "GPU unavailable, using CPU: " + explain(fallback_reason)
        st["hint"] = "See the log; restart ScribSalmon if you just installed the GPU libraries."
    return st
