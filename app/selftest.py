"""Headless packaging self-test:  ScribSalmon.exe --selftest [out.json]

Imports everything the frozen app needs (including the pythonnet/WinForms bits that crashed 1.0.0 when
ScribSalmon.exe.config was missing) WITHOUT opening a window. Writes {ok, failures, version} and returns 0/1.
"""
import importlib
import json
import pkgutil
import sys
import traceback
from pathlib import Path

THIRD_PARTY = ("faster_whisper", "ctranslate2", "av", "onnxruntime", "sounddevice", "soundcard")
KNOWN_APP_MODULES = ("api", "audio", "core", "gpu", "gpuconst", "gpulibs", "logsetup", "sessions", "settings", "summarize", "transcribe", "updater", "version")


def _root() -> Path:
    return Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent.parent)


def _import(name: str) -> None:
    importlib.import_module(name)


def _app_modules() -> list:
    names = []
    try:
        import app
        names = [m.name for m in pkgutil.iter_modules(app.__path__)]
    except Exception:
        pass
    names = sorted(set(names) | set(KNOWN_APP_MODULES))  # frozen builds may not enumerate the PYZ
    return [f"app.{n}" for n in names if n != "selftest"]


def _check_ui() -> None:
    p = _root() / "web" / "dist" / "index.html"
    if not p.is_file():
        raise FileNotFoundError(str(p))


def _check_ssl() -> None:
    import ssl
    ssl.create_default_context()


def _check_winforms() -> None:
    # exactly where 1.0.0 crashed: needs ScribSalmon.exe.config next to the exe
    import clr  # noqa: F401
    from System import Action  # noqa: F401
    import webview.platforms.winforms  # noqa: F401


def _check_gpu_status() -> None:
    from app import gpu
    st = gpu.status()
    if st.get("state") not in {"no_gpu", "driver_old", "libs_missing", "ready", "active", "failed"}:
        raise ValueError(f"unexpected gpu state {st.get('state')!r}")


def _check_gpuconst() -> None:
    import re
    from urllib.parse import urlparse
    from app import gpuconst
    if not re.fullmatch(r"[0-9a-f]{64}", gpuconst.SHA256):
        raise ValueError("SHA256 pin malformed")
    u = urlparse(gpuconst.URL)
    if u.scheme != "https" or u.hostname not in gpuconst.ALLOWED_HOSTS:
        raise ValueError("download URL is not https on an allowed host")
    if gpuconst.SIZE <= 0:
        raise ValueError("SIZE must be positive")


def _check_redact() -> None:
    from app import logsetup
    key = "sk-ant-api03-" + "A1b2C3d4" * 4
    if key in logsetup.redact(f"key={key}"):
        raise ValueError("redact left a key visible")


def run(out_path=None) -> int:
    checks = [(m, m) for m in _app_modules() + list(THIRD_PARTY)]
    failures = []

    def attempt(name, fn):
        try:
            fn()
        except Exception as e:
            failures.append({"check": name, "error": f"{type(e).__name__}: {e}",
                             "trace": traceback.format_exc(limit=4)})

    for name, mod in checks:
        attempt(name, lambda mod=mod: _import(mod))
    attempt("web/dist/index.html", _check_ui)
    attempt("ssl", _check_ssl)
    attempt("gpu.status", _check_gpu_status)
    attempt("gpuconst pins", _check_gpuconst)
    attempt("logsetup.redact", _check_redact)
    attempt("clr+System+webview.winforms", _check_winforms)

    try:
        from app.version import VERSION
    except Exception:
        VERSION = "unknown"
    result = {"ok": not failures, "failures": failures, "version": VERSION}
    if out_path:
        try:
            Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            traceback.print_exc()
            return 1
    return 0 if result["ok"] else 1
