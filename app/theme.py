"""Dark, minimal, futuristic theme: palette constants + global QSS + window helpers."""
import sys

BG = "#0d0907"
SURFACE = "#130d0b"
CARD = "#1a1210"
CARD_HI = "#271a16"
BORDER = "#2c201b"
TEXT = "#f7ede9"
MUTED = "#a08f88"
ACCENT = "#ff8a73"
ACCENT2 = "#ffc65c"
DANGER = "#ff3b5c"
OK = "#3ddc97"

FONT_UI = '"Segoe UI Variable Text", "Segoe UI", "Leelawadee UI", sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'

QSS = f"""
* {{ font-family: {FONT_UI}; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog, QMessageBox {{ background: {BG}; }}
QWidget#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QWidget#main {{ background: {BG}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}

QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#h {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
QLabel#brand {{ font-size: 17px; font-weight: 600; }}
QLabel#timer {{ color: {MUTED}; font-family: {FONT_MONO}; font-size: 14px; }}
QLabel#status {{ color: {MUTED}; font-size: 12px; }}
QLabel#emptyTitle {{ font-size: 20px; font-weight: 600; }}
QLabel#glyph {{ color: {ACCENT}; font-size: 54px; }}

QLineEdit {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 8px 12px; selection-background-color: rgba(255,138,115,70);
}}
QLineEdit:hover {{ border-color: #3d2c25; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit#title {{
    background: transparent; border: none; border-bottom: 1px solid transparent;
    border-radius: 0; font-size: 26px; font-weight: 600; padding: 2px 0;
}}
QLineEdit#title:hover {{ border-bottom: 1px solid {BORDER}; }}
QLineEdit#title:focus {{ border-bottom: 1px solid {ACCENT}; }}

QPlainTextEdit, QTextEdit {{
    background: transparent; border: none; font-size: 14px;
    selection-background-color: rgba(255,138,115,70);
}}

QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #35261f; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #54392f; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #35261f; border-radius: 3px; min-width: 36px; }}

QComboBox {{
    background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 6px 12px; min-height: 22px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
    selection-background-color: #2e201b; outline: 0;
}}

QListWidget {{ background: transparent; border: none; outline: 0; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}

QDialogButtonBox QPushButton, QMessageBox QPushButton {{
    background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 7px 18px; min-width: 70px;
}}
QDialogButtonBox QPushButton:hover, QMessageBox QPushButton:hover {{ border-color: {ACCENT}; }}
QDialogButtonBox QPushButton:default, QMessageBox QPushButton:default {{
    background: {ACCENT}; color: #07090d; border-color: {ACCENT};
}}
"""


def apply(app) -> None:
    app.setStyleSheet(QSS)


def dark_titlebar(widget) -> None:
    dark_titlebar_hwnd(int(widget.winId()))


def dark_titlebar_hwnd(hwnd: int) -> None:
    """Windows 10/11: dark title bar tinted to the app background."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)  # immersive dark
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(0x0007090D)), 4)  # caption = BG (BGR)
    except Exception:
        pass
