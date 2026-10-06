"""One-click download of the NVIDIA cuBLAS 12 runtime that CTranslate2 needs for GPU transcription (Windows).

ScribSalmon does NOT redistribute these DLLs. At the user's click we fetch NVIDIA's own PyPI wheel
(`nvidia-cublas-cu12`, pinned in app.gpuconst: URL, size, SHA-256), verify it, and extract only three
pinned members (two DLLs + the licence text) into %LOCALAPPDATA%/ScribSalmon/gpu-libs/<pkg>-<version>/.
Nothing is parsed from the network at runtime: no PyPI JSON, no redirects to unknown hosts.

Safety properties: https + host allow-list (also on redirects), exact size + SHA-256 of the wheel and of every
extracted file, member names are looked up by exact name and written to file names WE choose (zip-slip is
impossible), per-file byte caps (zip bombs are impossible), staging folder on the same drive with an atomic
os.replace into the final folder, and everything is removed on failure or cancel.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import gpuconst, updater

log = logging.getLogger("scribsalmon.gpulibs")

STAGING_PREFIX = ".staging-"
CHUNK = 1 << 20
_active = threading.Event()      # set while an install runs in this process (cleanup_stale must not race it)


class GpuLibsError(Exception):
    pass


class GpuLibsCancelled(GpuLibsError):
    pass


# ---------------------------------------------------------------- helpers

def _fmt_bytes(n: float) -> str:
    return f"{n / (1024 ** 3):.2f} GB" if n >= 1024 ** 3 else f"{n / (1024 ** 2):.0f} MB"


def required_free_bytes() -> int:
    return int(gpuconst.REQUIRED_FREE_BYTES)


def check_disk(root: Path) -> None:
    """Raise GpuLibsError if the drive holding `root` can't take the wheel + the extracted files."""
    probe = Path(root)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as e:
        raise GpuLibsError(f"Could not check free disk space: {e}") from e
    need = required_free_bytes()
    if free < need:
        raise GpuLibsError(f"Not enough free disk space: {_fmt_bytes(need)} needed on the drive holding "
                           f"{root}, {_fmt_bytes(free)} available. Free some space and try again.")


def _check_cancel(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise GpuLibsCancelled("Download cancelled.")


def _rm_tree(p: Path) -> None:
    for _ in range(3):
        shutil.rmtree(p, ignore_errors=True)
        if not Path(p).exists():
            return
        time.sleep(0.2)
    log.info("could not fully remove %s", p)


class _Throttle:
    """Calls fn(pct, done, total) at most ~4x/s and on every whole-percent change."""

    def __init__(self, fn):
        self.fn, self.last_pct, self.last_t = fn, -1, 0.0

    def __call__(self, done: int, total: int, force: bool = False) -> None:
        if self.fn is None:
            return
        pct = min(100, int(done * 100 / total)) if total else 0
        now = time.monotonic()
        if force or pct != self.last_pct or now - self.last_t >= 0.25:
            self.last_pct, self.last_t = pct, now
            self.fn(pct, done, total)


# ---------------------------------------------------------------- download

def download_wheel(dest: Path, on_progress: Optional[Callable] = None,
                   cancel: Optional[threading.Event] = None) -> str:
    """Stream the pinned wheel to `dest` (must not exist). Returns its SHA-256 after exact size + hash checks."""
    url, size, want = gpuconst.URL, int(gpuconst.SIZE), gpuconst.SHA256
    prog = _Throttle(on_progress)
    try:
        resp = updater._open(url, size, "application/octet-stream", hosts=gpuconst.ALLOWED_HOSTS)
    except updater.UpdateError as e:
        raise GpuLibsError(str(e)) from None
    except OSError as e:
        raise GpuLibsError(f"Could not reach the download server: {e}") from e
    h = hashlib.sha256()
    received = 0
    try:
        with contextlib.closing(resp):
            cl = getattr(resp, "headers", None) and resp.headers.get("Content-Length")
            if cl is not None and str(cl).isdigit() and int(cl) != size:
                raise GpuLibsError("The server reports an unexpected file size; refusing to download.")
            with open(dest, "xb") as f:
                while True:
                    _check_cancel(cancel)
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > size:
                        raise GpuLibsError("The download is larger than expected; it was discarded.")
                    h.update(chunk)
                    f.write(chunk)
                    prog(received, size)
    except (GpuLibsError, OSError) as e:
        if isinstance(e, GpuLibsError):
            raise
        raise GpuLibsError(f"Download failed: {e}") from e
    except updater.UpdateError as e:
        raise GpuLibsError(str(e)) from None
    if received != size:
        raise GpuLibsError("The download is incomplete (connection closed early). Please try again.")
    prog(received, size, force=True)
    digest = h.hexdigest()
    if digest != want:
        raise GpuLibsError("Checksum mismatch: the downloaded file does not match the pinned SHA-256; it was discarded.")
    return digest


# ---------------------------------------------------------------- extract

def extract(wheel: Path, staging: Path, on_progress: Optional[Callable] = None,
            cancel: Optional[threading.Event] = None) -> dict:
    """Extract ONLY the pinned members to `staging` under the pinned file names. Returns {name: {size, sha256}}."""
    total = sum(m[1] for m in gpuconst.MEMBERS.values())
    prog = _Throttle(on_progress)
    done = 0
    files = {}
    try:
        zf = zipfile.ZipFile(wheel)
    except (zipfile.BadZipFile, OSError) as e:
        raise GpuLibsError(f"The downloaded file is not a valid wheel: {e}") from e
    with zf:
        for member, (name, size, sha) in gpuconst.MEMBERS.items():
            try:
                info = zf.getinfo(member)
            except KeyError:
                raise GpuLibsError(f"Expected file missing from the package: {member}") from None
            if info.file_size != size:
                raise GpuLibsError(f"Unexpected size for {name} in the package; refusing to extract.")
            h = hashlib.sha256()
            n = 0
            with zf.open(info) as src, open(staging / name, "xb") as out:
                while True:
                    _check_cancel(cancel)
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > size:
                        raise GpuLibsError(f"{name} is larger than expected; refusing to extract.")
                    h.update(chunk)
                    out.write(chunk)
                    done += len(chunk)
                    prog(done, total)
            if n != size or h.hexdigest() != sha:
                raise GpuLibsError(f"Checksum mismatch for {name}; the file was discarded.")
            files[name] = {"size": size, "sha256": sha}
    prog(total, total, force=True)
    return files


# ---------------------------------------------------------------- install

def install(on_progress: Optional[Callable] = None, cancel: Optional[threading.Event] = None) -> Path:
    """Download, verify and install into libs_root()/FOLDER_NAME. on_progress(phase, pct, received, total).

    Leaves nothing behind on failure or cancel. The finished folder appears atomically (os.replace)."""
    root = gpuconst.libs_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise GpuLibsError(f"Could not create {root}: {e}") from e
    check_disk(root)
    staging = root / f"{STAGING_PREFIX}{secrets.token_hex(4)}"
    final = root / gpuconst.FOLDER_NAME

    def emit(phase):
        return (lambda pct, done, total: on_progress(phase, pct, done, total)) if on_progress else None

    t0 = time.monotonic()
    log.info("GPU libraries: installing %s %s into %s", gpuconst.PACKAGE, gpuconst.VERSION, final)
    try:
        staging.mkdir()
        wheel = staging / gpuconst.WHEEL_NAME
        out = staging / "out"
        out.mkdir()

        download_wheel(wheel, emit("download"), cancel)
        log.info("GPU libraries: downloaded %d bytes in %.1f s", gpuconst.SIZE, time.monotonic() - t0)
        if on_progress:
            on_progress("verify", 100, gpuconst.SIZE, gpuconst.SIZE)
        log.info("GPU libraries: wheel size and SHA-256 verified")

        t1 = time.monotonic()
        files = extract(wheel, out, emit("extract"), cancel)
        log.info("GPU libraries: extracted %d files in %.1f s", len(files), time.monotonic() - t1)
        wheel.unlink()

        manifest = {"package": gpuconst.PACKAGE, "version": gpuconst.VERSION, "files": files,
                    "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        (out / gpuconst.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        _check_cancel(cancel)
        if final.exists():                       # reinstall: os.replace can't overwrite a non-empty folder
            os.replace(final, staging / "old")
        os.replace(out, final)
        log.info("GPU libraries: installed to %s (total %.1f s)", final, time.monotonic() - t0)
        return final
    except GpuLibsCancelled:
        log.info("GPU libraries: install cancelled")
        raise
    except GpuLibsError as e:
        log.info("GPU libraries: install failed: %s", e)
        raise
    except Exception as e:
        log.exception("GPU libraries: install failed")
        raise GpuLibsError(f"Install failed: {e}") from e
    finally:
        _rm_tree(staging)


def cleanup_stale() -> None:
    """Remove leftover .staging-* folders (crash / power loss mid-install). Never while an install is running."""
    if _active.is_set():
        return
    try:
        root = gpuconst.libs_root()
        if not root.is_dir():
            return
        for d in root.glob(STAGING_PREFIX + "*"):
            if d.is_dir() and not d.is_symlink():
                log.info("removing stale GPU libraries staging folder %s", d.name)
                _rm_tree(d)
    except Exception:
        log.info("gpulibs cleanup_stale failed", exc_info=True)


# ---------------------------------------------------------------- orchestration

class GpuLibsInstaller:
    """One download at a time on a worker thread. Events (via emit(event, payload)):
    gpu_progress{pct, received, total, phase: download|verify|extract}, gpu_ready{status}, gpu_error{message}.
    on_installed() runs BEFORE gpu_ready; if it returns a dict that dict is the `status` payload."""

    def __init__(self, emit, on_installed=None):
        self._emit, self._on_installed = emit, on_installed
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    @property
    def in_progress(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def _fire(self, event, payload) -> None:
        try:
            self._emit(event, payload)
        except Exception:
            log.info("emit failed", exc_info=True)

    def start(self) -> bool:
        with self._lock:
            if self.in_progress:
                return False
            self._cancel = cancel = threading.Event()
            _active.set()
            self._thread = threading.Thread(target=self._run, args=(cancel,), daemon=True, name="gpu-libs")
            self._thread.start()
        return True

    def cancel(self) -> bool:
        if self.in_progress:
            self._cancel.set()
            return True
        return False

    def _run(self, cancel: threading.Event) -> None:
        def prog(phase, pct, received, total):
            self._fire("gpu_progress", {"pct": pct, "received": received, "total": total, "phase": phase})
        try:
            install(prog, cancel)
        except GpuLibsCancelled:
            _active.clear()
            return
        except Exception as e:
            _active.clear()
            if not cancel.is_set():
                self._fire("gpu_error", {"message": str(e) or "Download failed."})
            return
        _active.clear()
        status = None
        if self._on_installed is not None:
            try:
                status = self._on_installed()
            except Exception:
                log.exception("on_installed failed")
        self._fire("gpu_ready", {"status": status if isinstance(status, dict) else {}})
