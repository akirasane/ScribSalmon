"""Session storage: one folder per session under SESSIONS_DIR.

  meta.json       {"title", "created", "duration", "parts_sig"}  (duration cached; see Session.duration)
  rec_001.wav ... recording parts (also imported files); legacy meeting.wav is picked up too
  transcript.txt
  summary.md
"""
import json
import re
import shutil
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from .fsutil import atomic_write_text
from .settings import SESSIONS_DIR


# search cache: folder -> (signature of transcript/summary mtimes, lowercased text)
_SEARCH_CACHE: Dict[str, Tuple[tuple, str]] = {}

VALID_ID = re.compile(r"^[\w-]+$")


def is_valid_id(x) -> bool:
    return isinstance(x, str) and x not in (".", "..") and bool(VALID_ID.match(x))


def append_text(cur: str, text: str) -> str:
    return (cur + "\n" if cur and not cur.endswith("\n") else cur) + text + "\n"


@dataclass
class Session:
    dir: Path
    title: str
    created: datetime
    meta: dict = field(default_factory=dict, repr=False, compare=False)  # raw meta.json (cache fields)

    @property
    def parts(self) -> List[Path]:
        return sorted(self.dir.glob("*.wav"))

    def _parts_sig(self) -> list:
        sig = []
        for p in self.parts:
            try:
                st = p.stat()
            except OSError:
                continue
            sig.append([p.name, st.st_size, st.st_mtime_ns])
        return sig

    @property
    def duration(self) -> float:
        """Total audio seconds. Cached in meta.json keyed by a stat-only signature of the parts, so unchanged
        notes never open the WAVs (opening hydrates OneDrive Files-On-Demand placeholders)."""
        sig = self._parts_sig()
        cached = self.meta.get("duration")
        if self.meta.get("parts_sig") == sig and isinstance(cached, (int, float)):
            return float(cached)
        total = 0.0
        for name, _size, _mt in sig:
            try:
                with wave.open(str(self.dir / name), "rb") as w:
                    total += w.getnframes() / w.getframerate()
            except (wave.Error, OSError, EOFError, ZeroDivisionError):
                pass
        self.meta["duration"] = total
        self.meta["parts_sig"] = sig
        try:
            if (self.dir / "meta.json").exists():
                self.save_meta()
        except OSError:
            pass
        return total

    def next_part_path(self, prefix: str = "rec") -> Path:
        n = len(self.parts) + 1
        while (self.dir / f"{prefix}_{n:03d}.wav").exists():
            n += 1
        return self.dir / f"{prefix}_{n:03d}.wav"

    def read(self, name: str) -> str:
        try:
            return (self.dir / name).read_text(encoding="utf-8")
        except OSError:
            return ""

    def write(self, name: str, text: str) -> None:
        atomic_write_text(self.dir / name, text)

    def append(self, name: str, text: str) -> None:
        cur = self.read(name)
        self.write(name, (cur + "\n" if cur and not cur.endswith("\n") else cur) + text + "\n")

    def save_meta(self) -> None:
        d = {"title": self.title, "created": self.created.isoformat()}
        for k in ("duration", "parts_sig"):
            if k in self.meta:
                d[k] = self.meta[k]
        atomic_write_text(self.dir / "meta.json", json.dumps(d, ensure_ascii=False))

    def search_text(self) -> str:
        """Lowercased transcript + summary, cached per folder until either file's mtime/size changes."""
        sig = []
        for n in ("transcript.txt", "summary.md"):
            try:
                st = (self.dir / n).stat()
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        key = str(self.dir)
        hit = _SEARCH_CACHE.get(key)
        if hit and hit[0] == tuple(sig):
            return hit[1]
        text = (self.read("transcript.txt") + "\n" + self.read("summary.md")).lower()
        _SEARCH_CACHE[key] = (tuple(sig), text)
        return text

    def matches(self, query: str) -> bool:
        q = (query or "").strip().lower()
        return not q or q in self.title.lower() or q in self.search_text()


def create() -> Session:
    now = datetime.now()
    base = SESSIONS_DIR / now.strftime("%Y-%m-%d_%H-%M-%S")
    d, n = base, 1
    while d.exists():
        n += 1
        d = base.with_name(f"{base.name}_{n}")
    d.mkdir(parents=True)
    s = Session(d, f"Meeting {now:%Y-%m-%d %H:%M}", now)
    s.save_meta()
    return s


def load(d: Path) -> Session:
    title, created = d.name, datetime.fromtimestamp(d.stat().st_mtime)
    meta: dict = {}
    try:
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if isinstance(m, dict):
            meta = {k: m[k] for k in ("duration", "parts_sig") if k in m}
        title = m.get("title", title)
        created = datetime.fromisoformat(m["created"])
    except (OSError, ValueError, KeyError):
        try:  # legacy folder named by timestamp
            created = datetime.strptime(d.name, "%Y-%m-%d_%H-%M-%S")
            title = f"Meeting {created:%Y-%m-%d %H:%M}"
        except ValueError:
            pass
    return Session(d, title, created, meta)


def list_all() -> List[Session]:
    if not SESSIONS_DIR.exists():
        return []
    out = [load(d) for d in SESSIONS_DIR.iterdir()
           if is_valid_id(d.name) and d.is_dir() and ((d / "meta.json").exists() or any(d.glob("*.wav")))]
    return sorted(out, key=lambda s: s.created, reverse=True)


def delete(s: Session) -> None:
    # only ever remove a folder directly inside SESSIONS_DIR
    root = SESSIONS_DIR.resolve()
    r = s.dir.resolve()
    if not is_valid_id(s.dir.name) or r.parent != root or r == root:
        raise ValueError("Refusing to delete outside the notes folder.")
    shutil.rmtree(r)

