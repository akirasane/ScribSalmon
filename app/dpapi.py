"""Windows DPAPI (current-user scope) via ctypes, used to keep API keys encrypted at rest.

Values look like "dpapi:v1:<base64>". Only the same Windows account on the same machine can decrypt them.
"""
import base64
import ctypes
import sys
from ctypes import POINTER, Structure, byref, c_char, c_void_p, c_wchar_p
from ctypes import wintypes

PREFIX = "dpapi:v1:"
_ENTROPY = b"ScribSalmon/apikey/v1"
_UI_FORBIDDEN = 0x1


class DpapiError(Exception):
    pass


class DATA_BLOB(Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_char))]


def available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, POINTER(c_char))), buf


def _apis():
    if not available():
        raise DpapiError("DPAPI is only available on Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [POINTER(DATA_BLOB), c_wchar_p, POINTER(DATA_BLOB), c_void_p,
                                         c_void_p, wintypes.DWORD, POINTER(DATA_BLOB)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [POINTER(DATA_BLOB), POINTER(c_wchar_p), POINTER(DATA_BLOB), c_void_p,
                                           c_void_p, wintypes.DWORD, POINTER(DATA_BLOB)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [c_void_p]
    kernel32.LocalFree.restype = c_void_p
    return crypt32, kernel32


def _run(fn_name: str, data: bytes) -> bytes:
    crypt32, kernel32 = _apis()
    inb, _keep = _blob(data)
    ent, _keep2 = _blob(_ENTROPY)
    out = DATA_BLOB()
    if fn_name == "protect":
        ok = crypt32.CryptProtectData(byref(inb), "ScribSalmon", byref(ent), None, None, _UI_FORBIDDEN, byref(out))
    else:
        ok = crypt32.CryptUnprotectData(byref(inb), None, byref(ent), None, None, _UI_FORBIDDEN, byref(out))
    if not ok:
        raise DpapiError(f"{fn_name} failed (GetLastError={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, c_void_p))


def protect(s: str) -> str:
    return PREFIX + base64.b64encode(_run("protect", s.encode("utf-8"))).decode("ascii")


def unprotect(s: str) -> str:
    if not isinstance(s, str) or not s.startswith(PREFIX):
        raise DpapiError("Not a DPAPI value.")
    try:
        raw = base64.b64decode(s[len(PREFIX):], validate=True)
    except ValueError as e:
        raise DpapiError(f"Bad base64: {e}") from e
    return _run("unprotect", raw).decode("utf-8")
