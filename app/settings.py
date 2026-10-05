import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "ScribSalmon"
LEGACY_NAME = "VoiceRecog"  # previous name of this app; its folders are moved over once


def _resolve(new: Path, old: Path) -> Path:
    """Use `new`; if only the legacy folder exists, rename it to `new` (keeps all notes).
    If the rename fails (e.g. a file is open), keep using the legacy folder rather than losing access."""
    if not new.exists() and old.exists():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


_appdata = Path(os.environ.get("APPDATA", Path.home()))
APP_DIR = _resolve(_appdata / APP_NAME, _appdata / LEGACY_NAME)
SETTINGS_FILE = APP_DIR / "settings.json"
_docs = Path.home() / "Documents"
SESSIONS_DIR = _resolve(_docs / APP_NAME, _docs / LEGACY_NAME)


@dataclass
class Settings:
    engine: str = "local"  # local | openai
    language: str = "auto"  # auto | th | en
    whisper_model: str = "small"  # tiny/base/small/medium/large-v3(-turbo) or a preset repo id
    whisper_custom: str = ""  # optional: any faster-whisper model id / folder, overrides whisper_model
    vocabulary: str = ""  # names / terms hint passed to Whisper and the Thai review
    use_system: bool = True
    use_mic: bool = True
    live_transcript: bool = True  # False: record only, transcribe after Stop
    summary_backend: str = "auto"  # auto | cli | api
    summary_prompt: str = ""  # empty = built-in default
    anthropic_key: str = ""
    openai_key: str = ""
    claude_model: str = "claude-sonnet-5-5"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        s.anthropic_key = s.anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")
        s.openai_key = s.openai_key or os.environ.get("OPENAI_API_KEY", "")
        return s

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
