import json
import os
from dataclasses import asdict, dataclass, fields
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
    device: str = "auto"  # auto | cpu | cuda

    @property
    def effective_anthropic_key(self) -> str:
        return self.anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def effective_openai_key(self) -> str:
        return self.openai_key or os.environ.get("OPENAI_API_KEY", "")

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        migrate = False
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in coerce_patch(data, False).items():
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        # older versions persisted env-var keys into settings.json; drop those copies
        for attr, env in (("anthropic_key", "ANTHROPIC_API_KEY"), ("openai_key", "OPENAI_API_KEY")):
            v = getattr(s, attr)
            if v and v == os.environ.get(env, ""):
                setattr(s, attr, "")
                migrate = True
        if migrate:
            try:
                s.save()
            except OSError:
                pass
        return s

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


ENUMS = {"engine": {"local", "openai"}, "language": {"auto", "th", "en"},
         "summary_backend": {"auto", "cli", "api"}, "device": {"auto", "cpu", "cuda"}}
SECRETS = {"anthropic_key", "openai_key"}
FIELD_TYPES = {f.name: type(f.default) for f in fields(Settings)}


def coerce_patch(data, strict: bool = True) -> dict:
    """Keep only known settings with the right type/enum value. strict raises, else drops."""
    out = {}
    if not isinstance(data, dict):
        if strict:
            raise ValueError("Invalid settings.")
        return out
    for k, v in data.items():
        if k not in FIELD_TYPES:
            continue
        typ = FIELD_TYPES[k]
        ok = isinstance(v, bool) if typ is bool else (isinstance(v, typ) and not isinstance(v, bool))
        if ok and k in ENUMS and v not in ENUMS[k]:
            ok = False
        if not ok:
            if strict:
                raise ValueError(f"Invalid value for {k}")
            continue
        out[k] = v
    return out
