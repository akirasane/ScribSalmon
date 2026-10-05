"""Small filesystem helpers."""
import os
import time
from pathlib import Path


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write via a temp file in the same folder + os.replace so readers never see a half-written file.
    os.replace is retried briefly on PermissionError (antivirus / indexer holding the target)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
