"""pywebview JS bridge. Public methods are callable from JS as window.pywebview.api.<name>(...).

Each call returns {"ok": true, "data": ...} or {"ok": false, "error": "..."} so the UI never
has to deal with Python tracebacks.
"""
import json
import traceback
import webbrowser
from typing import Optional
from urllib.parse import urlparse

import webview

from .core import Controller


def _safe(fn):
    def wrapper(self, *a, **kw):
        try:
            return {"ok": True, "data": fn(self, *a, **kw)}
        except Exception as e:  # surfaced to the UI as a toast
            traceback.print_exc()
            return {"ok": False, "error": str(e)}
    wrapper.__name__ = fn.__name__
    return wrapper


class Api:
    def __init__(self):
        self._window: Optional[webview.Window] = None
        self._closing = False
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
        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"{note['title']}.md",
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
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("WAV audio (*.wav)",))
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

    # ---- settings
    @_safe
    def get_settings(self):
        return self._c.get_settings()

    @_safe
    def save_settings(self, data):
        return self._c.save_settings(data)

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
