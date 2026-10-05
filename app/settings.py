import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import dpapi
from . import winutil
from .fsutil import atomic_write_text

log = logging.getLogger(__name__)

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


def _has_notes(d: Path) -> bool:
    try:
        return any(c.is_dir() and ((c / "meta.json").exists() or any(c.glob("*.wav"))) for c in d.iterdir())
    except OSError:
        return False


def resolve_notes_dir(env, known: Path, home: Path) -> Path:
    """Where notes live. SCRIBSALMON_DATA_DIR wins; else <Documents known folder>/ScribSalmon, except that an
    existing populated ~/Documents/ScribSalmon is kept when the known folder differs and has no ScribSalmon yet
    (never moved automatically across volumes / OneDrive)."""
    override = (env.get("SCRIBSALMON_DATA_DIR") or "").strip()
    if override:
        return Path(override)
    new = (known or home / "Documents") / APP_NAME
    old = home / "Documents" / APP_NAME
    if old != new and not new.exists() and old.exists() and _has_notes(old):
        return old
    return new


def _init_notes_dir() -> Path:
    d = resolve_notes_dir(os.environ, winutil.known_documents(), Path.home())
    if os.environ.get("SCRIBSALMON_DATA_DIR", "").strip():
        return d
    return _resolve(d, d.with_name(LEGACY_NAME))


SESSIONS_DIR = _init_notes_dir()


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
    check_updates: bool = True  # look for a newer release on launch (at most once a day)
    last_update_check: float = 0.0  # internal: epoch seconds of the last successful check
    skipped_version: str = ""  # internal: release the user chose to skip ("" = none)

    @property
    def effective_anthropic_key(self) -> str:
        return self.anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def effective_openai_key(self) -> str:
        return self.openai_key or os.environ.get("OPENAI_API_KEY", "")

    def __post_init__(self):
        self._unreadable: set = set()  # secrets whose stored dpapi blob could not be decrypted
        self._raw: dict = {}  # original blobs of those secrets, written back unchanged on save

    @classmethod
    def _read_json(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        migrate = False
        data = cls._read_json(SETTINGS_FILE)
        if data is None:
            data = cls._read_json(_bak_path())
        if data is not None:
            for k, v in data.items():
                if k in SECRETS and isinstance(v, str) and v:
                    if v.startswith("dpapi:"):
                        try:
                            data[k] = dpapi.unprotect(v)
                        except Exception as e:  # noqa: BLE001 - any failure means "can't read it"
                            log.warning("Cannot decrypt saved %s: %s", k, e)
                            data[k] = ""
                            s._unreadable.add(k)
                            s._raw[k] = v
                    elif dpapi.available():
                        migrate = True  # legacy plaintext: re-save encrypted
            for k, v in coerce_patch(data, False).items():
                setattr(s, k, v)
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

    def _serialize(self) -> str:
        d = asdict(self)
        for k in SECRETS:
            v = d[k]
            if not v:
                if k in self._unreadable and k in self._raw:
                    d[k] = self._raw[k]  # keep the undecryptable blob rather than destroying it
                continue
            self._unreadable.discard(k)  # user supplied a new value
            self._raw.pop(k, None)
            try:
                d[k] = dpapi.protect(v)
            except Exception as e:  # noqa: BLE001 - e.g. non-Windows: fall back to plaintext, never crash
                log.warning("Could not encrypt %s, saving as plain text: %s", k, e)
        return json.dumps(d, indent=2)

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        text = self._serialize()
        cur = None
        try:
            cur = SETTINGS_FILE.read_text(encoding="utf-8")
        except OSError:
            pass
        atomic_write_text(SETTINGS_FILE, text)
        # .bak: last good file; never contains a plaintext secret
        try:
            if _has_plaintext_secret(text):
                return
            if cur is not None and _is_json_dict(cur):
                atomic_write_text(_bak_path(), text if _has_plaintext_secret(cur) else cur)
        except OSError as e:
            log.warning("Could not write settings backup: %s", e)


def _bak_path() -> Path:
    return SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".bak")


def _is_json_dict(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def _has_plaintext_secret(text: str) -> bool:
    try:
        d = json.loads(text)
    except ValueError:
        return False
    return isinstance(d, dict) and any(
        isinstance(d.get(k), str) and d[k] and not d[k].startswith("dpapi:") for k in SECRETS)


ENUMS = {"engine": {"local", "openai"}, "language": {"auto", "th", "en"},
         "summary_backend": {"auto", "cli", "api"}, "device": {"auto", "cpu", "cuda"}}
SECRETS = {"anthropic_key", "openai_key"}
INTERNAL = {"last_update_check", "skipped_version"}  # written by the updater, never by the settings UI
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
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
        if typ is float:  # JS numbers arrive as int when whole
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
            if ok:
                v = float(v)
        else:
            ok = isinstance(v, bool) if typ is bool else (isinstance(v, typ) and not isinstance(v, bool))
        if ok and k == "skipped_version" and v != "" and not (len(v) <= 64 and _SEMVER.match(v)):
            ok = False
        if ok and k in ENUMS and v not in ENUMS[k]:
            ok = False
        if not ok:
            if strict:
                raise ValueError(f"Invalid value for {k}")
            continue
        out[k] = v
    return out
