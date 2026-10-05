"""Built-in update check + user-initiated installer download (stdlib only: urllib + ssl).

Flow: ask GitHub Releases for a newer version -> UI banner -> user clicks -> download the Inno Setup installer,
verify SHA-256 against the release's SHA256SUMS.txt -> lock + re-hash -> run it -> app quits so Setup can replace
files. Installers are unsigned, so nothing here ever installs silently or without a click. A checksum proves
integrity of the download, not authenticity of the publisher.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .version import VERSION

log = logging.getLogger("scribsalmon.updater")

REPO = "akirasane/ScribSalmon"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
RELEASES_PREFIX = f"https://github.com/{REPO}/releases/"
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                 "objects.githubusercontent.com"}
USER_AGENT = f"ScribSalmon/{VERSION} (+https://github.com/{REPO})"
TIMEOUT = 15
MAX_JSON = 1 << 20
MAX_SUMS = 64 << 10
MAX_SETUP = 1 << 30
THROTTLE = 24 * 3600
MAX_REDIRECTS = 5
MUTEX = "ScribSalmonAppMutex"
INSTALLER_ARGS = ["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE", "/RELAUNCH"]
TEMP_PREFIX = "ScribSalmon-update-"
SUMS_NAME = "SHA256SUMS.txt"
LOG_NAME = "install.log"

_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")
_DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_SUMS_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](\S.*?)\s*$")


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    notes_url: str
    setup_name: Optional[str]
    setup_url: Optional[str]
    setup_size: Optional[int]
    setup_digest: Optional[str]
    sums_url: Optional[str]


# ---------------------------------------------------------------- versions

def parse_version(s) -> Optional[tuple]:
    if not isinstance(s, str):
        return None
    m = _SEMVER.match(s.strip())
    if not m:
        return None
    pre = ()
    if m.group(4) is not None:
        ids = m.group(4).split(".")
        for i in ids:
            if not i or (i.isdigit() and len(i) > 1 and i[0] == "0"):
                return None
        pre = tuple(ids)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre)


def _pre_key(pre: tuple):
    # numeric ids < alphanumeric ids; numeric compare as ints; shorter set < longer when prefix equal
    return [(0, int(i), "") if i.isdigit() else (1, 0, i) for i in pre]


def is_newer(remote, local) -> bool:
    r, l = parse_version(remote), parse_version(local)
    if r is None or l is None:
        return False
    if r[:3] != l[:3]:
        return r[:3] > l[:3]
    rp, lp = r[3], l[3]
    if rp == lp:
        return False
    if not rp:      # remote is a full release, local a prerelease
        return True
    if not lp:
        return False
    return _pre_key(rp) > _pre_key(lp)


# ---------------------------------------------------------------- network

def check_url(url) -> None:
    if not isinstance(url, str):
        raise UpdateError("Blocked URL")
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise UpdateError("Blocked URL") from None
    if u.scheme != "https":
        raise UpdateError("Blocked URL: https required")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise UpdateError("Blocked URL: credentials not allowed")
    host = (u.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise UpdateError(f"Blocked URL: host {host!r} not allowed")
    if port not in (None, 443):
        raise UpdateError("Blocked URL: port not allowed")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self):
        self._count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        self._count += 1
        if self._count > MAX_REDIRECTS:
            raise UpdateError("Too many redirects")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, max_bytes, accept):
    """GET `url` and return the response (caller reads/closes). Declared Content-Length is checked up front."""
    check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect(),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept}, method="GET")
    resp = opener.open(req, timeout=TIMEOUT)
    try:
        check_url(resp.geturl())
        cl = resp.headers.get("Content-Length")
        if cl is not None and cl.isdigit() and int(cl) > max_bytes:
            raise UpdateError("Response too large")
    except BaseException:
        resp.close()
        raise
    return resp


def _read_all(url, max_bytes, accept) -> bytes:
    with contextlib.closing(_open(url, max_bytes, accept)) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UpdateError("Response too large")
    return data


# ---------------------------------------------------------------- parsing

def parse_release(data) -> Optional[Release]:
    if not isinstance(data, dict):
        return None
    if data.get("draft") is not False or data.get("prerelease") is not False:
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        return None
    ver = tag[1:]
    if parse_version(ver) is None:
        return None
    html = data.get("html_url")
    if not isinstance(html, str) or not html.startswith(RELEASES_PREFIX):
        return None
    base = f"{DOWNLOAD_PREFIX}{tag}/"
    setup_name = setup_url = setup_digest = sums_url = None
    setup_size = None
    want = f"ScribSalmon-Setup-{ver}.exe"
    assets = data.get("assets")
    for a in assets if isinstance(assets, list) else []:
        if not isinstance(a, dict):
            continue
        name, url = a.get("name"), a.get("browser_download_url")
        if name == want and url == base + want:
            setup_name, setup_url = name, url
            size = a.get("size")
            if size is not None:
                if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_SETUP:
                    return None
                setup_size = size
            dg = a.get("digest")
            if dg is not None:
                m = _DIGEST.match(dg) if isinstance(dg, str) else None
                if not m:
                    return None
                setup_digest = m.group(1).lower()
        elif name == SUMS_NAME and url == base + SUMS_NAME:
            sums_url = url
    return Release(version=ver, tag=tag, notes_url=html, setup_name=setup_name, setup_url=setup_url,
                   setup_size=setup_size, setup_digest=setup_digest, sums_url=sums_url)


def parse_sums(text) -> dict:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.lstrip("﻿")
    out: dict = {}
    for line in text.splitlines():
        m = _SUMS_LINE.match(line)
        if not m:
            continue
        h, name = m.group(1).lower(), m.group(2)
        if name in out and out[name] != h:
            raise UpdateError(f"Conflicting checksums for {name}")
        out[name] = h
    return out


def install_mode() -> str:
    if not getattr(sys, "frozen", False):
        return "source"
    if (Path(sys.executable).parent / "unins000.exe").is_file():
        return "installed"
    return "portable"


def should_check(last, now, enabled, force) -> bool:
    if force:
        return True
    if not enabled:
        return False
    try:
        last = float(last)
    except (TypeError, ValueError):
        return True
    if last > now + 86400:      # clock skew / bogus value
        return True
    return now - last >= THROTTLE


def fetch_latest() -> Optional[Release]:
    raw = _read_all(API_LATEST, MAX_JSON, "application/vnd.github+json")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise UpdateError(f"Bad response from GitHub: {e}") from None
    return parse_release(data)


# ---------------------------------------------------------------- download

_verified: dict = {}      # str(path) -> expected sha256 (set by download(), consumed by Updater.install)


def _rm_tree(d: Path) -> None:
    shutil.rmtree(d, ignore_errors=True)


def download(rel: Release, on_progress=None, cancel: Optional[threading.Event] = None) -> Path:
    if not rel.setup_url or not rel.setup_name:
        raise UpdateError("This release has no installer.")
    if rel.setup_name != f"ScribSalmon-Setup-{rel.version}.exe":
        raise UpdateError("Unexpected installer name.")
    check_url(rel.setup_url)
    sums_url = rel.sums_url or f"{DOWNLOAD_PREFIX}{rel.tag}/{SUMS_NAME}"
    sums = parse_sums(_read_all(sums_url, MAX_SUMS, "text/plain, application/octet-stream"))
    expected = sums.get(rel.setup_name)
    if not expected:
        raise UpdateError("Installer is not listed in SHA256SUMS.txt.")
    if rel.setup_digest and rel.setup_digest.lower() != expected:
        raise UpdateError("Checksum sources disagree; refusing to download.")

    limit = min(rel.setup_size, MAX_SETUP) if rel.setup_size else MAX_SETUP
    d = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    dest = d / rel.setup_name
    try:
        h = hashlib.sha256()
        received = 0
        last_pct, last_t = -1, 0.0
        with contextlib.closing(_open(rel.setup_url, limit, "application/octet-stream")) as resp, \
                open(dest, "xb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Download cancelled.")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                received += len(chunk)
                if received > limit:
                    raise UpdateError("Download is larger than expected.")
                h.update(chunk)
                f.write(chunk)
                if on_progress:
                    total = rel.setup_size or 0
                    pct = int(received * 100 / total) if total else 0
                    now = time.monotonic()
                    if pct - last_pct >= 1 or now - last_t >= 0.25:
                        last_pct, last_t = pct, now
                        on_progress(received, total)
        if rel.setup_size is not None and received != rel.setup_size:
            raise UpdateError("Download is incomplete.")
        if h.hexdigest() != expected:
            raise UpdateError("Checksum mismatch; the download was discarded.")
        if on_progress:
            on_progress(received, rel.setup_size or received)
    except BaseException as e:
        _rm_tree(d)
        if isinstance(e, (UpdateError, KeyboardInterrupt, SystemExit)):
            raise
        raise UpdateError(f"Download failed: {e}") from e
    _verified[str(dest)] = expected
    return dest


# ---------------------------------------------------------------- lock + launch

_lock_file = None     # held open until exit: deny-write between verification and Setup start


def _release_lock() -> None:
    global _lock_file
    f, _lock_file = _lock_file, None
    if f is not None:
        with contextlib.suppress(Exception):
            f.close()


def _hash_file(f) -> str:
    h = hashlib.sha256()
    while True:
        b = f.read(1 << 20)
        if not b:
            return h.hexdigest()
        h.update(b)


def _open_locked(path: Path):
    if sys.platform != "win32":
        return open(path, "rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, ATTR_NORMAL = 0x80000000, 1, 3, 0x80
    h = k32.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, ATTR_NORMAL, None)
    if h is None or h == ctypes.c_void_p(-1).value:
        raise UpdateError(f"Could not open the installer: {ctypes.WinError(ctypes.get_last_error())}")
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY)
    except BaseException:
        k32.CloseHandle(h)
        raise
    return os.fdopen(fd, "rb")


def _lock_and_rehash(path, expected):
    global _lock_file
    _release_lock()
    f = _open_locked(Path(path))
    try:
        if _hash_file(f) != expected:
            raise UpdateError("The downloaded installer changed on disk; refusing to run it.")
    except BaseException:
        f.close()
        raise
    _lock_file = f
    return f


def _temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def launch_installer(path, log_path) -> None:
    path = Path(path)
    if not path.is_absolute():
        raise UpdateError("Installer path must be absolute.")
    parent = path.resolve().parent
    if not parent.name.startswith(TEMP_PREFIX) or parent.parent != _temp_root():
        raise UpdateError("Installer is not in the update folder.")
    argv = [str(path), *INSTALLER_ARGS, f"/LOG={log_path}"]
    kw = dict(shell=False, cwd=str(path.parent), close_fds=True, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(argv, creationflags=base | _CREATE_BREAKAWAY_FROM_JOB, **kw)
    except OSError:
        try:
            subprocess.Popen(argv, creationflags=base, **kw)
        except OSError as e:
            raise UpdateError(f"Could not start the installer: {e}") from e


def cleanup_stale(max_age=86400) -> None:
    """Remove old update temp dirs from previous runs (only files we create)."""
    try:
        root = _temp_root()
        now = time.time()
        for d in root.glob(TEMP_PREFIX + "*"):
            try:
                if d.is_symlink() or not d.is_dir() or now - d.stat().st_mtime < max_age:
                    continue
                for f in d.iterdir():
                    if f.is_file() and not f.is_symlink() and (
                            f.name == LOG_NAME or re.fullmatch(r"ScribSalmon-Setup-.+\.exe", f.name)):
                        with contextlib.suppress(OSError):
                            f.unlink()
                with contextlib.suppress(OSError):
                    d.rmdir()
            except OSError:
                continue
    except Exception:
        log.info("cleanup_stale failed", exc_info=True)


# ---------------------------------------------------------------- orchestration

def _get(s, key, default):
    if isinstance(s, dict):
        return s.get(key, default)
    return getattr(s, key, default)


class Updater:
    def __init__(self, emit, get_settings, save_fields, is_idle):
        self._emit, self._get_settings, self._save, self._is_idle = emit, get_settings, save_fields, is_idle
        self.quitting = False
        self._lock = threading.Lock()
        self._release: Optional[Release] = None
        self._ready: Optional[tuple] = None       # (Release, Path)
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    def _fire(self, event, payload):
        try:
            self._emit(event, payload)
        except Exception:
            log.info("emit failed", exc_info=True)

    def _result(self, rel: Optional[Release], available: bool, skipped: bool) -> dict:
        mode = install_mode()
        return {"current": VERSION, "latest": rel.version if rel else None, "available": available,
                "notes_url": rel.notes_url if rel else None, "size": rel.setup_size if rel else None,
                "install_mode": mode, "skipped": skipped,
                "can_install": bool(rel and rel.setup_url and mode != "source")}

    def check(self, force: bool = False) -> dict:
        if parse_version(VERSION) is None:
            return self._result(None, False, False)
        s = self._get_settings()
        if not should_check(_get(s, "last_update_check", 0.0), time.time(),
                            bool(_get(s, "check_updates", True)), force):
            return self._result(None, False, False)
        try:
            rel = fetch_latest()
            self._save({"last_update_check": time.time()})
        except Exception as e:
            if force:
                raise UpdateError(f"Could not reach GitHub: {e}") from e
            log.info("update check failed: %s", e)
            return self._result(None, False, False)
        available = bool(rel and is_newer(rel.version, VERSION))
        with self._lock:
            self._release = rel if available else None
        skipped = bool(available and _get(s, "skipped_version", "") == rel.version)
        if available and (force or not skipped):
            self._fire("update_available", {"version": rel.version, "notes_url": rel.notes_url,
                                            "size": rel.setup_size, "install_mode": install_mode()})
        return self._result(rel, available, skipped)

    def start_download(self) -> bool:
        with self._lock:
            rel = self._release
            if rel is None or not rel.setup_url or install_mode() == "source":
                return False
            if self._thread is not None and self._thread.is_alive():
                return False
            self._cancel = cancel = threading.Event()
            self._ready = None
            self._thread = threading.Thread(target=self._run_download, args=(rel, cancel), daemon=True)
            self._thread.start()
        return True

    def _run_download(self, rel: Release, cancel: threading.Event) -> None:
        def prog(received, total):
            pct = min(100, int(received * 100 / total)) if total else 0
            self._fire("update_progress", {"pct": pct, "received": received, "total": total})
        try:
            path = download(rel, prog, cancel)
        except Exception as e:
            if not cancel.is_set():
                log.info("update download failed: %s", e)
                self._fire("update_error", {"message": str(e) or "Download failed."})
            return
        with self._lock:
            self._ready = (rel, path)
        self._fire("update_ready", {"version": rel.version})

    def cancel_download(self) -> bool:
        t = self._thread
        if t is not None and t.is_alive():
            self._cancel.set()
            return True
        return False

    def skip(self, version: str) -> None:
        if parse_version(version) is None:
            raise UpdateError("Invalid version.")
        self._save({"skipped_version": version})

    def install(self) -> bool:
        with self._lock:
            ready = self._ready
        if install_mode() == "source":
            raise UpdateError("Updates are only installed from the packaged app.")
        if ready is None or not ready[1].is_file():
            raise UpdateError("No downloaded update is ready.")
        rel, path = ready
        if not is_newer(rel.version, VERSION):
            raise UpdateError("This update is not newer than the running version.")
        if not self._is_idle():
            raise UpdateError("Stop recording / wait for transcription first.")
        expected = _verified.get(str(path))
        if not expected:
            raise UpdateError("The downloaded installer was not verified.")
        _lock_and_rehash(path, expected)
        try:
            launch_installer(path, path.parent / LOG_NAME)
        except BaseException:
            _release_lock()
            raise
        self.quitting = True
        return True
