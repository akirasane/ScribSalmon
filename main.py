"""ScribSalmon - React/Tailwind UI in a pywebview (WebView2) window.

    python main.py          run the built UI (web/dist)
    python main.py --dev    use the Vite dev server (http://127.0.0.1:5173) with devtools
Old PySide6 UI: python main_qt.py
"""
import sys
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
    window.events.closing += lambda: api.shutdown()
    webview.start(debug=dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
