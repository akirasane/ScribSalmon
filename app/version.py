"""App version: read from the bundled VERSION file (PyInstaller) or the repo root; "dev" if unavailable."""
import sys
from pathlib import Path


def _read() -> str:
    roots = []
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS))
    roots.append(Path(__file__).resolve().parent.parent)
    for r in roots:
        try:
            v = (r / "VERSION").read_text(encoding="utf-8").strip()
            if v:
                return v
        except OSError:
            continue
    return "dev"


VERSION = _read()
