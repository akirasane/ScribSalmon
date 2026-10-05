"""Small Windows helpers. Import-safe on any OS: ctypes.windll is only touched inside functions."""
import sys
from pathlib import Path
from typing import Optional


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


_app_mutex_handle = None  # kept for the process lifetime on purpose (never closed)


def create_app_mutex(name: str) -> Optional[int]:
    """Named mutex the installer (Inno AppMutex/CheckForMutexes) uses to detect a running app."""
    global _app_mutex_handle
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        create = ctypes.windll.kernel32.CreateMutexW
        create.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        handle = create(None, False, name)
        if handle:
            _app_mutex_handle = int(handle)
            return _app_mutex_handle
    except Exception:
        pass
    return None


FOLDERID_DOCUMENTS ="{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"


def known_folder(folder_id_guid: str) -> Optional[Path]:
    """Resolve a Windows Known Folder (honors OneDrive/redirected locations). None if unavailable."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID(folder_id_guid)
        guid = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        get = ctypes.windll.shell32.SHGetKnownFolderPath
        get.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                        ctypes.POINTER(ctypes.c_void_p)]
        get.restype = ctypes.HRESULT
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        ptr = ctypes.c_void_p()
        try:
            get(ctypes.byref(guid), 0, None, ctypes.byref(ptr))
            return Path(ctypes.wstring_at(ptr.value)) if ptr.value else None
        finally:
            if ptr.value:
                free(ptr)
    except Exception:
        return None


def known_documents() -> Path:
    """The user's Documents folder (may be redirected to OneDrive); falls back to ~/Documents."""
    return known_folder(FOLDERID_DOCUMENTS) or Path.home() / "Documents"
