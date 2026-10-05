"""ScribSalmon - React/Tailwind UI in a pywebview (WebView2) window.

    python main.py          run the built UI (web/dist)
    python main.py --dev    use the Vite dev server (http://127.0.0.1:5173) with devtools
Old PySide6 UI: python main_qt.py
"""
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

import webview

from app import theme
from app.api import Api

# PyInstaller unpacks bundled data under sys._MEIPASS; from source it is the folder of this file
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DIST = ROOT / "web" / "dist" / "index.html"
ICON = ROOT / "assets" / "icon.ico"
APP_ID = "OmeletteSalmon.ScribSalmon"  # own taskbar identity (otherwise Windows groups us under python.exe)


def _set_window_icon(window) -> None:
    """pywebview ignores `icon=` on WinForms/WebView2, so set it on the native form."""
    try:
        from System import Action
        from System.Drawing import Icon

        form = window.native
        ico = Icon(str(ICON))
        form.Invoke(Action(lambda: setattr(form, "Icon", ico)))
    except Exception:
        pass


def _origin_prefix(url: str) -> str:
    """URL prefix the app itself may navigate within: scheme://host:port/ (http) or the folder (file)."""
    from urllib.parse import urlparse
    p = urlparse(url)
    if p.scheme in ("http", "https"):
        return f"{p.scheme}://{p.netloc}/".lower()
    return url.rsplit("/", 1)[0].lower() + "/"


def _harden(window, allowed: str) -> None:
    """Block navigation away from the app (and external drops) in the WebView2 control.

    pywebview re-injects window.pywebview.api on every NavigationCompleted for ANY url, so a page
    that navigated elsewhere would get the whole backend API. External http(s) links go to the
    system browser instead.
    """
    try:
        from System import Action

        wv = window.native.webview  # BrowserForm.webview = the WebView2 control

        def on_nav(sender, args):
            try:
                uri = str(args.Uri)
                if uri.lower().startswith(allowed):
                    return
                args.Cancel = True
                if uri.lower().startswith(("http://", "https://")):
                    webbrowser.open(uri, new=2)
            except Exception:
                traceback.print_exc()

        def setup():
            try:
                wv.CoreWebView2.NavigationStarting += on_nav
                try:
                    wv.AllowExternalDrop = False
                except Exception:
                    pass
            except Exception:
                traceback.print_exc()

        window.native.Invoke(Action(setup))
    except Exception:
        traceback.print_exc()


def main() -> int:
    dev = "--dev" in sys.argv
    if dev:
        url = "http://127.0.0.1:5173"
    elif DIST.exists():
        url = str(DIST)
    else:
        print("UI not built. Run:  cd web && npm install && npm run build", file=sys.stderr)
        return 1

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    api = Api()
    window = webview.create_window(
        "ScribSalmon", url, js_api=api, width=1360, height=860, min_size=(1040, 680),
        background_color="#0d0907", text_select=True,
    )
    api._bind(window)

    def on_shown():
        _set_window_icon(window)
        try:
            theme.dark_titlebar_hwnd(int(window.native.Handle.ToInt64()))
        except Exception:
            pass

    window.events.shown += on_shown

    hardened = {"done": False}

    def on_loaded():
        if hardened["done"]:
            return
        hardened["done"] = True
        try:
            allowed = _origin_prefix(window.get_current_url() or url)
        except Exception:
            allowed = _origin_prefix(url)
        _harden(window, allowed)

    window.events.loaded += on_loaded

    # Closing: let the UI flush unsaved edits first. The closing handler runs while the GUI thread
    # waits, so it must not call evaluate_js itself; do it in a worker, then destroy() the window.
    state = {"done": False, "busy": False}

    def on_closing():
        if state["done"]:
            (getattr(api, "_shutdown", None) or api.shutdown)()
            return True
        if state["busy"]:
            return False
        state["busy"] = True

        def run():
            ev = threading.Event()
            try:
                # callback fires only for Promises (and on rejection); always hand it one
                window.evaluate_js(
                    "Promise.resolve(window.__flushNow ? window.__flushNow() : null).then(()=>true)",
                    lambda _r: ev.set(),
                )
            except Exception:
                ev.set()
            ev.wait(3)
            state["done"] = True
            window.destroy()

        threading.Thread(target=run, daemon=True).start()
        return False

    window.events.closing += on_closing
    # never let target=_blank / window.open load in-app; NavigationStarting guard sends http(s) to the browser
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.start(debug=dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
