"""pywebview JS bridge. Public methods are callable from JS as window.pywebview.api.<name>(...).

Each call returns {"ok": true, "data": ...} or {"ok": false, "error": "..."} so the UI never
has to deal with Python tracebacks.
"""
import json
import logging
import os
import re
import threading
import webbrowser
from typing import Optional
from urllib.parse import urlparse

import webview

from . import logsetup, settings, winutil
from .core import Controller
from .gpulibs import GpuLibsError
from .updater import UpdateError

log = logging.getLogger(__name__)


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(title, fallback: str = "note", limit: int = 120) -> str:
    """A Windows-safe file name stem for a note title (used as the export dialog's default name)."""
    name = _BAD_CHARS.sub("-", title if isinstance(title, str) else "")
    name = name[:limit].strip().rstrip(". ").strip()
    if not name or name.strip("-") == "":
        return fallback
    if name.split(".")[0].strip().upper() in _RESERVED:
        name = "_" + name
    return name


def _safe(fn):
    def wrapper(self, *a, **kw):
        try:
            return {"ok": True, "data": fn(self, *a, **kw)}
        except (ValueError, UpdateError, GpuLibsError) as e:  # expected, user-facing
            log.info("api.%s refused: %s", fn.__name__, e)  # never log call arguments
            return {"ok": False, "error": str(e)}
        except Exception as e:  # surfaced to the UI as a toast
            log.exception("api.%s failed", fn.__name__)
            return {"ok": False, "error": str(e)}
    wrapper.__name__ = fn.__name__
    return wrapper


class Api:
    def __init__(self):
        self._window: Optional[webview.Window] = None
        self._closing = False
        self._restart_requested = False  # read by main.py after webview.start() returns
        self._c = Controller(self._emit)

    def _bind(self, window: webview.Window):
        self._window = window

    def _emit(self, name, payload):
        w = self._window
        if not w or self._closing:
            return
        try:
            w.evaluate_js(f"window.__pyEmit && window.__pyEmit({json.dumps(name)}, {json.dumps(payload)})")
        except Exception:
            pass  # window closing

    # ---- notes
    @_safe
    def list_notes(self, query=""):
        return self._c.list_notes(query)

    @_safe
    def get_note(self, note_id):
        return self._c.get_note(note_id)

    @_safe
    def create_note(self):
        return self._c.create_note()

    @_safe
    def save_note(self, note_id, patch=None, *legacy):
        if isinstance(patch, str):
            patch = {"title": patch, "transcript": legacy[0] if len(legacy) > 0 else None,
                     "summary": legacy[1] if len(legacy) > 1 else None}
            patch = {k: v for k, v in patch.items() if v is not None}
        if not isinstance(patch, dict):
            raise ValueError("Invalid note data.")
        return self._c.save_note(note_id, patch)

    @_safe
    def delete_note(self, note_id):
        return self._c.delete_note(note_id)

    @_safe
    def export_note(self, note_id):
        note = self._c.get_note(note_id)
        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"{safe_filename(note['title'])}.md",
                                              file_types=("Markdown (*.md)",))
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        return self._c.export_note(note_id, path)

    # ---- recording
    @_safe
    def start_recording(self, note_id, opts):
        return self._c.start_recording(note_id, opts or {})

    @_safe
    def stop_recording(self):
        return self._c.stop_recording()

    @_safe
    def add_wav(self, note_id):
        res = self._window.create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Audio (*.wav;*.mp3;*.m4a;*.flac;*.ogg;*.mp4)",))
        if not res:
            return None
        return self._c.import_wav(note_id, res[0])

    # ---- summary
    @_safe
    def summarize(self, note_id, transcript):
        self._c.summarize(note_id, transcript)
        return True

    @_safe
    def retranscribe(self, note_id):
        return self._c.retranscribe(note_id)

    @_safe
    def review(self, note_id, transcript):
        return self._c.review(note_id, transcript)

    @_safe
    def cancel(self, kind, note_id):
        return self._c.cancel(kind, note_id)

    # ---- settings
    @_safe
    def get_settings(self):
        return self._c.get_settings()

    @_safe
    def save_settings(self, data):
        return self._c.save_settings(data)

    # ---- updates
    @_safe
    def check_for_updates(self, force=False):
        return self._c.updater.check(force is True)

    @_safe
    def download_update(self):
        return self._c.updater.start_download()

    @_safe
    def cancel_update(self):
        return self._c.updater.cancel_download()

    @_safe
    def skip_update(self, version):
        if not isinstance(version, str):
            raise ValueError("Invalid version.")
        self._c.updater.skip(version)
        return True

    @_safe
    def install_update(self):
        ok = self._c.updater.install()
        if ok and self._window:
            threading.Timer(0.3, self._window.destroy).start()  # let the UI flush, then the close flow runs
        return ok

    # ---- GPU / diagnostics
    @_safe
    def gpu_status(self):
        return self._c.gpu_status()

    @_safe
    def download_gpu_libs(self):
        return self._c.gpulibs.start()

    @_safe
    def cancel_gpu_download(self):
        return self._c.gpulibs.cancel()

    @_safe
    def open_log_folder(self):
        d = logsetup.LOG_DIR
        app_dir = settings.APP_DIR.resolve()
        d.mkdir(parents=True, exist_ok=True)
        real = d.resolve()
        if app_dir not in real.parents or not real.is_dir():
            raise ValueError("The log folder is not available.")
        os.startfile(str(d))  # type: ignore[attr-defined]  # Windows only
        return True

    @_safe
    def copy_diagnostics(self):
        text = self._c.diagnostics()
        return {"copied": bool(winutil.set_clipboard_text(text)), "chars": len(text)}

    @_safe
    def restart_app(self):
        ok = self._c.restart_app()
        self._restart_requested = True
        if self._window:
            threading.Timer(0.3, self._window.destroy).start()  # UI flushes, close flow runs, main relaunches
        return ok

    @_safe
    def open_external(self, url):
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError("Only http(s) links can be opened.")
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            raise ValueError("Only http(s) links can be opened.")
        webbrowser.open(p.geturl(), new=2)
        return True

    def _shutdown(self):
        self._closing = True  # stop pushing events into a closing window
        self._c.shutdown()
