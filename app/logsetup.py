"""File logging for ScribSalmon: rotating log, redaction, crash hooks, diagnostics text.

Never log transcripts, API keys, note text or prompts. Everything written passes through `redact`.
"""
import faulthandler
import logging
import logging.handlers
import os
import platform
import re
import sys
import threading
from pathlib import Path
from typing import Optional

from . import settings  # must come first: it may rename the legacy VoiceRecog folder at import

LOG_DIR = settings.APP_DIR / "logs"
LOG_NAME = "scribsalmon.log"
CRASH_NAME = "crash.log"
FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUPS = 5
TAIL_READ = 256 * 1024

_MARK = "_scribsalmon_handler"
_state = {"crash_file": None, "prev_excepthook": None, "prev_thread_hook": None,
          "excepthook": None, "thread_hook": None, "path": None}

_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]+"), "[redacted]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "[redacted]"),
    (re.compile(r"(?i)\bBearer\s+\S+"), "Bearer [redacted]"),
    (re.compile(r"(?i)\b(api[_-]?key|x-api-key|authorization)(\s*[:=]\s*)(?!\[redacted\]|Bearer \[redacted\])\S+"),
     r"\1\2[redacted]"),
    (re.compile(r"dpapi:\S+"), "[redacted]"),
    (re.compile(r"(?<![A-Za-z0-9+_=-])[A-Za-z0-9+_=-]{32,}(?![A-Za-z0-9+_=-])"), "[redacted]"),
]


def _home_regexes():
    out = []
    try:
        home = str(Path.home())
    except Exception:
        return out
    if len(home) < 4:
        return out
    for variant in {home, home.replace("\\", "/")}:
        out.append(re.compile(re.escape(variant), re.IGNORECASE))
    return out


def redact(text) -> str:
    """Mask secrets and the home folder in `text`."""
    s = str(text)
    for rx, rep in _PATTERNS:
        s = rx.sub(rep, s)
    for rx in _home_regexes():
        s = rx.sub("~", s)
    return s


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts the full output, including exception tracebacks."""

    def format(self, record) -> str:
        return redact(super().format(record))


def _banner(log: logging.Logger) -> None:
    try:
        from . import updater
        from .version import VERSION
        mode = updater.install_mode()
    except Exception:
        VERSION, mode = "?", "?"
    log.info("ScribSalmon %s starting | mode=%s frozen=%s python=%s | %s | exe=%s",
             VERSION, mode, bool(getattr(sys, "frozen", False)), platform.python_version(),
             platform.platform(), sys.executable)


def _remove_handlers(root: logging.Logger) -> None:
    for h in list(root.handlers):
        if getattr(h, _MARK, False):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass


def _install_hooks() -> None:
    log = logging.getLogger("crash")
    if _state["excepthook"] is None:
        prev = sys.excepthook

        def hook(exc_type, exc, tb):
            try:
                log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
            except Exception:
                pass
            prev(exc_type, exc, tb)

        _state["prev_excepthook"], _state["excepthook"] = prev, hook
    sys.excepthook = _state["excepthook"]

    if _state["thread_hook"] is None:
        prev_t = threading.excepthook

        def thook(args):
            try:
                name = args.thread.name if args.thread else "?"
                log.critical("Unhandled exception in thread %s", name,
                             exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            except Exception:
                pass
            prev_t(args)

        _state["prev_thread_hook"], _state["thread_hook"] = prev_t, thook
    threading.excepthook = _state["thread_hook"]


def _enable_faulthandler(d: Path) -> None:
    try:
        p = d / CRASH_NAME
        mode = "w" if (p.exists() and p.stat().st_size > 1_000_000) else "a"
        f = open(p, mode, encoding="utf-8")
        old = _state["crash_file"]
        faulthandler.enable(file=f, all_threads=True)
        _state["crash_file"] = f
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
    except Exception:
        pass


def setup(log_dir=None, dev: bool = False, native_crash: bool = True) -> Optional[Path]:
    """Configure logging; returns the log file path, or None when file logging is unavailable. Idempotent."""
    root = logging.getLogger()
    _remove_handlers(root)
    root.setLevel(logging.INFO)
    fmt = RedactingFormatter(FORMAT)
    path = None
    d = Path(log_dir) if log_dir is not None else LOG_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            d / LOG_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8", delay=True)
        fh.setFormatter(fmt)
        setattr(fh, _MARK, True)
        root.addHandler(fh)
        path = d / LOG_NAME
    except Exception as e:
        if sys.stderr is not None:
            print(f"ScribSalmon: file logging disabled ({e})", file=sys.stderr)
    if dev and sys.stderr is not None:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        setattr(ch, _MARK, True)
        root.addHandler(ch)
    if getattr(sys, "frozen", False):
        logging.raiseExceptions = False
    logging.captureWarnings(True)
    _install_hooks()
    if path is not None and native_crash:
        _enable_faulthandler(d)
    _state["path"] = path
    _banner(logging.getLogger("app"))
    return path


def shutdown() -> None:
    """Undo setup (used by tests): remove handlers/hooks, stop faulthandler, close the crash file."""
    _remove_handlers(logging.getLogger())
    if _state["excepthook"] is not None and sys.excepthook is _state["excepthook"]:
        sys.excepthook = _state["prev_excepthook"]
    if _state["thread_hook"] is not None and threading.excepthook is _state["thread_hook"]:
        threading.excepthook = _state["prev_thread_hook"]
    _state["excepthook"] = _state["thread_hook"] = None
    f = _state["crash_file"]
    if f is not None:
        try:
            faulthandler.disable()
            f.close()
        except Exception:
            pass
        _state["crash_file"] = None
    logging.captureWarnings(False)
    _state["path"] = None


def _current_log() -> Path:
    return _state["path"] or (LOG_DIR / LOG_NAME)


def tail(n: int = 200) -> str:
    """Last `n` lines of the current log (reads at most ~256 KB), redacted."""
    try:
        with open(_current_log(), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_READ))
            data = f.read()
        lines = data.decode("utf-8", errors="replace").splitlines()
        if size > TAIL_READ and lines:
            lines = lines[1:]  # first line is likely cut
        n = max(0, int(n))
        return redact("\n".join(lines[-n:] if n else []))
    except OSError:
        return ""


def diagnostics_text(sections: dict) -> str:
    """Plain-text report: each section as `== name ==` then its content, then the redacted log tail."""
    parts = []
    for name, body in sections.items():
        if isinstance(body, dict):
            body = "\n".join(f"{k}: {v}" for k, v in body.items())
        elif isinstance(body, (list, tuple)):
            body = "\n".join(str(x) for x in body)
        parts.append(f"== {name} ==\n{redact(body)}")
    parts.append(f"== log (last lines) ==\n{tail()}")
    return "\n\n".join(parts) + "\n"
