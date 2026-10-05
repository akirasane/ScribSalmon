"""Session storage: one folder per session under SESSIONS_DIR.

  meta.json       {"title", "created"}
  rec_001.wav ... recording parts (also imported files); legacy meeting.wav is picked up too
  transcript.txt
  summary.md
"""
import json
import shutil
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from .settings import SESSIONS_DIR


@dataclass
class Session:
    dir: Path
    title: str
    created: datetime

    @property
    def parts(self) -> List[Path]:
        return sorted(self.dir.glob("*.wav"))

    @property
    def duration(self) -> float:
        total = 0.0
        for p in self.parts:
            try:
                with wave.open(str(p), "rb") as w:
                    total += w.getnframes() / w.getframerate()
            except (wave.Error, OSError, EOFError):
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
        (self.dir / name).write_text(text, encoding="utf-8")

    def append(self, name: str, text: str) -> None:
        cur = self.read(name)
        self.write(name, (cur + "\n" if cur and not cur.endswith("\n") else cur) + text + "\n")

    def save_meta(self) -> None:
        (self.dir / "meta.json").write_text(
            json.dumps({"title": self.title, "created": self.created.isoformat()}, ensure_ascii=False),
            encoding="utf-8")


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
    try:
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        title = m.get("title", title)
        created = datetime.fromisoformat(m["created"])
    except (OSError, ValueError, KeyError):
        try:  # legacy folder named by timestamp
            created = datetime.strptime(d.name, "%Y-%m-%d_%H-%M-%S")
            title = f"Meeting {created:%Y-%m-%d %H:%M}"
        except ValueError:
            pass
    return Session(d, title, created)


def list_all() -> List[Session]:
    if not SESSIONS_DIR.exists():
        return []
    out = [load(d) for d in SESSIONS_DIR.iterdir()
           if d.is_dir() and ((d / "meta.json").exists() or any(d.glob("*.wav")))]
    return sorted(out, key=lambda s: s.created, reverse=True)


def delete(s: Session) -> None:
    # only ever remove a folder directly inside SESSIONS_DIR
    if s.dir.parent.resolve() == SESSIONS_DIR.resolve():
        shutil.rmtree(s.dir)


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
