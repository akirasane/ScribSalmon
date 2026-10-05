"""Small Windows helpers. Import-safe on any OS: ctypes.windll is only touched inside functions."""
import sys


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


def set_app_user_model_id(app_id: str) -> None:
    """Own taskbar identity (otherwise Windows groups us under python.exe)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass
