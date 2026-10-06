"""UI-independent controller: recording, transcription queue, summaries, notes CRUD.

Talks to the UI only through `emit(event, payload)`; works with any front-end.
Events: text{id,text,rev} transcript{id,text,rev} summary{id,markdown|None,rev}
        review{id,items|None} status str busy bool error str
        tasks{id,tasks:[refine|summary|review]} (per-note running long tasks)
        backlog{id,pending,seconds_behind} (audio waiting to be transcribed)
        recording{id|None} level float notes (list changed)
"""
import logging
import queue
import threading
import time
from functools import reduce
from pathlib import Path
from typing import Callable, Optional

from . import gpu, gpuconst, gpulibs, logsetup, sessions
from . import transcribe as _transcribe
from .audio import Recorder
from .sessions import Session
from .errors import Cancelled
from .settings import INTERNAL, SECRETS, Settings, coerce_patch
from . import updater as _updater_mod
from .updater import Updater, install_mode
from .summarize import DEFAULT_PROMPT, review, summarize
from .transcribe import SAMPLE_RATE, load_wav, make_engine
from .version import VERSION

ENGINE_KEYS = {"engine", "whisper_model", "whisper_custom", "openai_key", "device"}
log = logging.getLogger(__name__)
BACKLOG_FALLBACK_SECS = 120.0
TASK_KINDS = ("refine", "summary", "review")
_SECRET_ENV = {"anthropic_key": "ANTHROPIC_API_KEY", "openai_key": "OPENAI_API_KEY"}


class Controller:
    def __init__(self, emit: Callable[[str, object], None]):
        self.emit = emit
        self.s = Settings.load()
        self.lock = threading.RLock()
        self.engine_lock = threading.Lock()  # one transcription at a time per model
        self.q: "queue.Queue" = queue.Queue()
        self.engine = None
        self._engine_init_lock = threading.Lock()
        self._engine_gen = 0
        self._revs: dict = {}
        self.rec_lock = threading.Lock()
        self.rec_live = False
        self.worker: Optional[threading.Thread] = None
        self.recorder: Optional[Recorder] = None
        self.rec_session: Optional[Session] = None
        self.rec_path: Optional[Path] = None
        self.rec_started = 0.0
        self.rec_state: dict = {"fallback": False, "fed": 0.0}
        self._tasks: dict = {}    # note id -> set of running kinds (refine/summary/review)
        self._pending: dict = {}  # note id -> audio chunks queued/being transcribed
        self._behind: dict = {}   # note id -> seconds of audio queued/being transcribed
        self._cancels: dict = {}  # (note id, kind) -> threading.Event
        self.updater = Updater(self.emit, lambda: self.s, self._save_update_fields, self._is_idle)
        self.gpulibs = gpulibs.GpuLibsInstaller(self.emit, self._on_gpu_libs_installed)
        self._fallback_seen: set = set()  # distinct GPU-fallback reasons already announced this session
        self.restart_requested = False
        threading.Thread(target=self._cleanup_updates, name="update-cleanup", daemon=True).start()

    def _err(self, msg) -> None:
        """emit("error") that also leaves a trace in the log file (messages carry no secrets/transcripts)."""
        log.warning("error shown to user: %s", msg)
        self.emit("error", msg)

    def _is_idle(self) -> bool:
        return self.recorder is None and not self._busy_now()

    def _cleanup_updates(self):
        # module-level functions (not Updater methods); each guarded on its own so one failure can't skip the other
        for fn in (_updater_mod.cleanup_stale, gpulibs.cleanup_stale):
            try:
                fn()
            except Exception:  # noqa: BLE001 - housekeeping must never matter
                log.info("cleanup failed: %s", getattr(fn, "__module__", fn), exc_info=True)

    def _save_update_fields(self, fields: dict) -> None:
        """Persist updater-owned settings (last check / skipped version); nothing else is touched."""
        patch = {k: v for k, v in coerce_patch(fields, strict=True).items() if k in INTERNAL}
        changed = False
        for k, v in patch.items():
            if getattr(self.s, k) != v:
                setattr(self.s, k, v)
                changed = True
        if changed:
            self.s.save()

    # ---------------------------------------------------------------- whisper context hint
    def _prompt_for(self, note_id: Optional[str]) -> Optional[str]:
        """Vocabulary + the end of the transcript so far: helps Whisper spell names/terms
        consistently and continue the previous sentence across chunk boundaries."""
        parts = []
        if self.s.vocabulary.strip():
            parts.append(self.s.vocabulary.strip())
        if note_id:
            d = self._dir(note_id)
            if d:
                tail = sessions.load(d).read("transcript.txt").strip()[-160:]
                if tail:
                    parts.append(tail)
        return (" ".join(parts)[-400:]) or None

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _dir(note_id) -> Optional[Path]:
        if not sessions.is_valid_id(note_id):
            return None
        root = sessions.SESSIONS_DIR.resolve()
        d = (sessions.SESSIONS_DIR / note_id).resolve()
        if d.parent != root or not d.is_dir():
            return None
        return d

    def _session(self, note_id: str) -> Session:
        if not sessions.is_valid_id(note_id):
            raise ValueError("Invalid note id.")
        d = self._dir(note_id)
        if d is None:
            raise ValueError("Note not found.")
        return sessions.load(d)

    def _rev(self, nid: str) -> dict:
        with self.lock:
            return self._revs.setdefault(nid, {"t": 0, "s": 0, "replaced": 0, "tail": []})

    # ---------------------------------------------------------------- task / backlog tracking
    def _busy_now(self) -> bool:
        return any(self._tasks.values()) or any(v > 0 for v in self._pending.values())

    def _emit_busy(self):
        with self.lock:
            b = self._busy_now()
        self.emit("busy", b)

    def _begin_task(self, nid: str, kind: str) -> threading.Event:
        with self.lock:
            if kind in self._tasks.get(nid, ()):
                raise ValueError("That is already running for this note.")
            ev = threading.Event()
            self._tasks.setdefault(nid, set()).add(kind)
            self._cancels[(nid, kind)] = ev
            kinds = sorted(self._tasks[nid])
        self.emit("tasks", {"id": nid, "tasks": kinds})
        self.emit("busy", True)
        return ev

    def _end_task(self, nid: str, kind: str):
        with self.lock:
            ks = self._tasks.get(nid)
            if ks is not None:
                ks.discard(kind)
                if not ks:
                    del self._tasks[nid]
            self._cancels.pop((nid, kind), None)
            kinds = sorted(self._tasks.get(nid, ()))
        self.emit("tasks", {"id": nid, "tasks": kinds})
        self._emit_busy()

    def _is_refining(self, nid: str) -> bool:
        with self.lock:
            return "refine" in self._tasks.get(nid, ())

    def _add_pending(self, nid: str, n: int, secs: float = 0.0):
        with self.lock:
            self._pending[nid] = self._pending.get(nid, 0) + n
            self._behind[nid] = max(0.0, self._behind.get(nid, 0.0) + secs)
            if self._pending[nid] <= 0:
                self._pending.pop(nid, None)
                self._behind.pop(nid, None)
            pend, behind = self._pending.get(nid, 0), self._behind.get(nid, 0.0)
        self.emit("backlog", {"id": nid, "pending": pend, "seconds_behind": round(behind, 1)})
        self._emit_busy()

    def _enqueue(self, nid: str, item):
        """The only way audio enters the queue: keeps per-note pending/backlog counters exact.
        `item` None is an end-of-batch marker and is not counted."""
        if item is None:
            self.q.put((nid, None))
            return
        self._add_pending(nid, 1, self._secs(item))
        self.q.put((nid, item))

    @staticmethod
    def _secs(audio) -> float:
        try:
            return len(audio) / SAMPLE_RATE
        except TypeError:
            return 0.0

    def cancel(self, kind: str, note_id: str) -> bool:
        """Ask a running refine/summary/review on this note to stop. False if none is running."""
        if kind not in TASK_KINDS:
            raise ValueError("Unknown task.")
        if not sessions.is_valid_id(note_id):
            raise ValueError("Invalid note id.")
        with self.lock:
            ev = self._cancels.get((note_id, kind))
        if ev is None:
            return False
        ev.set()
        self.emit("status", "Cancelling…")
        return True

    # ---------------------------------------------------------------- engine
    def _get_engine(self):
        while True:
            with self._engine_init_lock:
                eng = self.engine
                if eng is not None:
                    return eng
                gen = self._engine_gen
                self.emit("status", "Loading speech model (first run downloads it)…")
                self.emit("busy", True)
                eng = make_engine(self.s)
                if gen != self._engine_gen:
                    continue  # settings changed while loading; build again
                self.engine = eng
                log.info("engine ready: %s", self._settings_summary())
                fb = getattr(eng, "fallback_reason", None)
                if fb and fb not in self._fallback_seen:
                    self._fallback_seen.add(fb)
                    self.emit("gpu_fallback", {"reason": gpu.explain(fb) or fb, "detail": fb})
                return eng

    def _settings_summary(self) -> dict:
        """Non-secret settings only: never keys, vocabulary or prompt text."""
        s = self.s
        return {"engine": s.engine, "model": s.whisper_custom or s.whisper_model, "device": s.device,
                "language": s.language, "live_transcript": s.live_transcript}

    # ---------------------------------------------------------------- GPU
    def _on_gpu_libs_installed(self) -> dict:
        gpu.activate(preload=True)
        self._reset_engine()
        gpu.invalidate_cache()
        return self.gpu_status()

    def gpu_status(self) -> dict:
        eng = self.engine
        st = gpu.with_engine(gpu.status(), getattr(eng, "device", None) if eng else None,
                             getattr(eng, "fallback_reason", None) if eng else None)
        st["download_bytes"] = gpuconst.SIZE
        st["disk_bytes"] = gpuconst.INSTALLED_BYTES
        st["eula_url"] = gpuconst.EULA_URL
        st["libs_folder"] = str(gpuconst.libs_root())
        return st

    def restart_app(self) -> bool:
        if not self._is_idle():
            raise ValueError("Finish recording and transcription before restarting.")
        self.restart_requested = True
        return True

    def diagnostics(self) -> str:
        import platform
        eng = self.engine
        return logsetup.diagnostics_text({
            "version": VERSION,
            "install mode": install_mode(),
            "os": platform.platform(),
            "settings": self._settings_summary(),
            "gpu": self.gpu_status(),
            "engine": {"loaded": eng is not None, "device": getattr(eng, "device", None),
                       "fallback_reason": getattr(eng, "fallback_reason", None)},
        })

    def _reset_engine(self, only=None):
        if only is None or self.engine is only:
            self._engine_gen += 1
            self.engine = None

    @staticmethod
    def _brief(s: Session) -> dict:
        return {"id": s.dir.name, "title": s.title, "created": s.created.isoformat(),
                "duration": s.duration, "parts": len(s.parts)}

    def _full(self, s: Session) -> dict:
        d = self._brief(s)
        d["transcript"] = s.read("transcript.txt")
        d["summary"] = s.read("summary.md")
        st = self._rev(s.dir.name)
        d["transcript_rev"] = st["t"]
        d["summary_rev"] = st["s"]
        return d

    # ---------------------------------------------------------------- notes
    def list_notes(self, query: str = "") -> list:
        out = []
        for s in sessions.list_all():
            if s.matches(query):  # cached per file mtime/size, so typing in the search box stays cheap
                out.append(self._brief(s))
        return out

    def get_note(self, note_id: str) -> dict:
        return self._full(self._session(note_id))

    def create_note(self) -> dict:
        s = sessions.create()
        return self._full(s)

    def save_note(self, note_id: str, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("Invalid note data.")
        for k in ("title", "transcript", "summary"):
            if k in patch and not isinstance(patch[k], str):
                raise ValueError(f"Invalid value for {k}")
        with self.lock:
            s = self._session(note_id)
            st = self._rev(s.dir.name)
            appended: list = []
            conflict: list = []
            if "title" in patch:
                s.title = patch["title"].strip() or s.title
                s.save_meta()
            if "transcript" in patch:
                text = patch["transcript"]
                base = patch.get("transcript_rev", st["t"])
                if not isinstance(base, int) or isinstance(base, bool):
                    base = -1
                if base == st["t"]:
                    s.write("transcript.txt", text)
                elif st["replaced"] <= base < st["t"]:
                    appended = [x for r, x in st["tail"] if r > base]
                    s.write("transcript.txt", reduce(sessions.append_text, appended, text))
                else:
                    conflict.append("transcript")
            if "summary" in patch:
                base = patch.get("summary_rev", st["s"])
                if base == st["s"]:
                    s.write("summary.md", patch["summary"])
                else:
                    conflict.append("summary")
            out = self._brief(s)
            out["transcript_rev"] = st["t"]
            out["summary_rev"] = st["s"]
            if appended:
                out["appended"] = appended
            if conflict:
                out["conflict"] = conflict
            return out

    def delete_note(self, note_id: str) -> bool:
        s = self._session(note_id)
        with self.rec_lock:
            if self.rec_session and self.rec_session.dir.resolve() == s.dir.resolve():
                raise ValueError("Stop recording before deleting this note.")
            sessions.delete(s)
        with self.lock:
            self._revs.pop(s.dir.name, None)
        return True

    def export_note(self, note_id: str, path: str) -> str:
        s = self._session(note_id)
        body = (f"# {s.title}\n\n{s.created:%Y-%m-%d %H:%M}\n\n{s.read('summary.md')}\n\n"
                f"## Transcript\n\n{s.read('transcript.txt')}\n")
        Path(path).write_text(body, encoding="utf-8")
        return path

    # ---------------------------------------------------------------- settings
    def get_settings(self) -> dict:
        import os
        from dataclasses import asdict
        d = asdict(self.s)
        for k, env in _SECRET_ENV.items():
            saved = bool(d[k])
            has = bool(getattr(self.s, "effective_" + k))
            d[k] = ""
            d["has_" + k] = has
            if k in getattr(self.s, "_unreadable", ()):
                d[k + "_source"] = "unreadable"
            else:
                d[k + "_source"] = "saved" if saved else ("env" if os.environ.get(env) else "")
        d["default_prompt"] = DEFAULT_PROMPT.strip()
        d["version"] = VERSION
        d["install_mode"] = install_mode()
        return d

    def _apply_settings(self, data: dict) -> set:
        data = dict(data)
        clears = {k for k in SECRETS if data.pop("clear_" + k, False) is True}
        patch = coerce_patch(data, strict=True)
        for k in SECRETS:
            if k in patch:
                patch[k] = patch[k].strip()
                if not patch[k]:
                    del patch[k]  # empty typed key = keep the saved one
        changed = set()
        for k, v in patch.items():
            if getattr(self.s, k) != v:
                setattr(self.s, k, v)
                changed.add(k)
        for k in clears:
            if getattr(self.s, k):
                setattr(self.s, k, "")
                changed.add(k)
        if changed:
            self.s.save()
            if changed & ENGINE_KEYS:
                self._reset_engine()
        return changed

    def save_settings(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError("Invalid settings.")
        data = {k: v for k, v in data.items() if k not in INTERNAL}  # the UI cannot set updater state
        prompt = data.get("summary_prompt")
        if isinstance(prompt, str) and prompt.strip() == DEFAULT_PROMPT.strip():
            data["summary_prompt"] = ""
        self._apply_settings(data)
        return self.get_settings()

    # ---------------------------------------------------------------- transcription worker
    def _ensure_worker(self):
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def _work(self):
        while True:
            note_id, audio = self.q.get()
            if audio is None:
                self.q.task_done()
                with self.lock:
                    idle = self.q.empty() and not any(v > 0 for v in self._pending.values())
                if idle:
                    self.emit("status", "Transcription finished.")
                    self.emit("notes", None)
                self._emit_busy()
                continue
            eng = None
            try:
                eng = self._get_engine()
                self.emit("busy", True)
                self.emit("status", f"Transcribing… ({self.q.qsize()} more waiting)")
                lang = None if self.s.language == "auto" else self.s.language
                with self.engine_lock:
                    text = eng.transcribe(audio, lang, self._prompt_for(note_id))
                if text:
                    rev = None
                    with self.lock:
                        d = self._dir(note_id)
                        if d:
                            sessions.load(d).append("transcript.txt", text)
                            st = self._rev(note_id)
                            st["t"] += 1
                            rev = st["t"]
                            st["tail"].append((rev, text))
                            del st["tail"][:-500]
                    if rev is not None:
                        self.emit("text", {"id": note_id, "text": text, "rev": rev})
            except Exception as e:
                self._err(f"Transcription failed: {e}")
                self._reset_engine(only=eng)
            finally:
                self.q.task_done()
                self._add_pending(note_id, -1, -self._secs(audio))

    def _transcribe_file(self, note_id: str, path: Path, start_seconds: float = 0.0):
        self._ensure_worker()
        self._add_pending(note_id, 1)  # token: keeps the note busy while the file is decoded and fed

        def feed():
            try:
                a = load_wav(path)
                if start_seconds > 0:
                    a = a[int(start_seconds * SAMPLE_RATE):]
                step = 30 * SAMPLE_RATE
                for i in range(0, len(a), step):
                    self._enqueue(note_id, a[i:i + step])
                self._enqueue(note_id, None)
            except Exception as e:
                self._err(f"Transcription of {Path(path).name} failed: {e}")
            finally:
                self._add_pending(note_id, -1)

        threading.Thread(target=feed, daemon=True).start()
        self.emit("status", "Transcribing file…")

    # ---------------------------------------------------------------- recording
    def start_recording(self, note_id: str, opts: dict) -> dict:
        if self.updater.quitting:
            raise ValueError("ScribSalmon is installing an update and will restart.")
        with self.rec_lock:
            if self.recorder:
                raise ValueError("Already recording.")
            mapped = {k: opts[k_js] for k_js, k in (("system", "use_system"), ("mic", "use_mic"),
                                                    ("engine", "engine"), ("language", "language"))
                      if k_js in opts}
            self._apply_settings(mapped)
            if not (self.s.use_system or self.s.use_mic):
                raise ValueError("Pick system audio and/or microphone.")
            s = self._session(note_id)
            if self._is_refining(s.dir.name):
                raise ValueError("Wait for Refine to finish (or cancel it) before recording.")
            self._ensure_worker()
            path = s.next_part_path()
            live = self.s.live_transcript
            nid = s.dir.name
            state = {"fallback": False, "fed": 0.0}
            self.rec_state = state
            rec = Recorder(path, self.s.use_system, self.s.use_mic,
                           on_chunk=(lambda a: self._live_chunk(nid, state, a)) if live else (lambda a: None),
                           on_error=lambda m: self._err(m),
                           on_dead=lambda: threading.Thread(target=self._on_rec_dead, args=(rec,),
                                                            daemon=True).start())
            try:
                rec.start()
            except Exception as e:
                raise ValueError(f"Could not start recording: {e}")
            self.recorder = rec
            self.rec_session = s
            self.rec_path = path
            self.rec_live = live
            self.rec_started = time.time()
            threading.Thread(target=self._level_loop, args=(rec,), daemon=True).start()
            self.emit("status", "Recording…" if live else "Recording (transcribe after Stop)…")
            self.emit("recording", {"id": nid, "started": self.rec_started})
            return {"id": nid, "started": self.rec_started}

    def _live_chunk(self, nid: str, state: dict, audio):
        """Feed a live chunk unless transcription is hopelessly behind (then Stop transcribes the rest)."""
        if state["fallback"]:
            return
        with self.lock:
            behind = self._behind.get(nid, 0.0)
        if behind > BACKLOG_FALLBACK_SECS:
            state["fallback"] = True
            self.emit("status", "Live transcription fell behind; the rest will be transcribed after Stop.")
            return
        state["fed"] += self._secs(audio)
        self._enqueue(nid, audio)

    def _level_loop(self, rec: Recorder):
        while self.recorder is rec:
            self.emit("level", rec.level)
            time.sleep(0.08)

    def _on_rec_dead(self, rec: Recorder):
        self._err("All audio sources stopped; recording saved.")
        self.stop_recording(expected=rec)

    def stop_recording(self, expected=None) -> dict:
        with self.rec_lock:
            rec, sess, path, live = self.recorder, self.rec_session, self.rec_path, self.rec_live
            if not rec or not sess or (expected is not None and rec is not expected):
                return {}
            self.recorder = None  # ends the level loop
            self.rec_session = None
            rec.stop()
            nid = sess.dir.name
            state = self.rec_state
            if live and state.get("fallback"):
                self._transcribe_file(nid, path, start_seconds=state["fed"])
            elif live:
                self._enqueue(nid, None)
            else:
                self._transcribe_file(nid, path)
            self.emit("recording", {"id": None})
            self.emit("status", "Recording saved. Transcribing…")
            self.emit("notes", None)
            try:
                return self._brief(self._session(nid))
            except ValueError:
                return {}

    def import_wav(self, note_id: str, path: str) -> dict:
        """Add an audio file (WAV/MP3/M4A/FLAC/OGG...) to a note and transcribe it."""
        s = self._session(note_id)
        if self._is_refining(s.dir.name):
            raise ValueError("Wait for Refine to finish (or cancel it) before importing audio.")
        dest = s.next_part_path("import")
        _transcribe.import_audio(Path(path), dest)  # ValueError (and nothing left behind) if unusable
        self._transcribe_file(s.dir.name, dest)
        self.emit("notes", None)
        return self._brief(s)

    def retranscribe(self, note_id: str) -> bool:
        """Re-run speech-to-text over the WHOLE recording(s) with full context (more accurate than
        live 6 s chunks) and replace the transcript. Refused while the note is recording, still has
        audio waiting in the transcription queue, or is already refining. Cancellable: a cancelled
        refine keeps the old transcript."""
        s = self._session(note_id)
        nid = s.dir.name
        if self.rec_session and self.rec_session.dir.resolve() == s.dir.resolve():
            raise ValueError("Stop recording first.")
        parts = s.parts
        if not parts:
            raise ValueError("This note has no recording to refine.")
        with self.lock:
            if self._pending.get(nid, 0) > 0:
                raise ValueError("Wait for transcription to finish.")
        cancel = self._begin_task(nid, "refine")

        def go():
            eng = None
            try:
                eng = self._get_engine()
                lang = None if self.s.language == "auto" else self.s.language
                texts = []
                for i, p in enumerate(parts, 1):
                    if cancel.is_set():
                        raise Cancelled()
                    self.emit("status", f"Refining transcript… recording {i}/{len(parts)} (this can take a while)")
                    a = load_wav(p)
                    with self.engine_lock:
                        t = eng.transcribe(a, lang, self._prompt_for(None), long_form=True,
                                           should_stop=cancel.is_set)
                    if t:
                        texts.append(t)
                if cancel.is_set():
                    raise Cancelled()
                full = "\n".join(texts).strip() + "\n"
                with self.lock:
                    s.write("transcript.txt", full)
                    st = self._rev(nid)
                    st["t"] += 1
                    st["replaced"] = st["t"]
                    st["tail"].clear()
                    rev = st["t"]
                self.emit("transcript", {"id": note_id, "text": full, "rev": rev})
                self.emit("status", "Transcript refined.")
            except Cancelled:
                self.emit("status", "Cancelled")  # the old transcript is untouched
            except Exception as e:
                self._err(f"Refine failed: {e}")
                self._reset_engine(only=eng)
            finally:
                self._end_task(nid, "refine")

        threading.Thread(target=go, daemon=True).start()
        return True

    # ---------------------------------------------------------------- Thai/word review
    def review(self, note_id: str, transcript: str) -> bool:
        nid = self._session(note_id).dir.name
        transcript = transcript if isinstance(transcript, str) else ""
        cancel = self._begin_task(nid, "review")
        self.emit("status", "Checking transcript for garbled words…")

        def go():
            try:
                items = review(transcript, self.s.summary_backend, self.s.effective_anthropic_key,
                               self.s.claude_model, self.s.vocabulary, cancel=cancel)
                self.emit("review", {"id": note_id, "items": items})
                self.emit("status", f"Found {len(items)} phrase(s) to check." if items else "Nothing suspicious found.")
            except Cancelled:
                self.emit("review", {"id": note_id, "items": None})
                self.emit("status", "Cancelled")
            except Exception as e:
                self.emit("review", {"id": note_id, "items": None})
                self._err(f"Review failed: {e}")
            finally:
                self._end_task(nid, "review")

        threading.Thread(target=go, daemon=True).start()
        return True

    # ---------------------------------------------------------------- summary
    def summarize(self, note_id: str, transcript: str) -> None:
        nid = self._session(note_id).dir.name
        transcript = transcript if isinstance(transcript, str) else ""
        cancel = self._begin_task(nid, "summary")
        self.emit("status", "Summarizing with Claude… (CLI can take ~30 s)")

        def go():
            try:
                md = summarize(transcript, self.s.summary_backend, self.s.effective_anthropic_key,
                               self.s.claude_model, self.s.summary_prompt, cancel=cancel)
                rev = 0
                with self.lock:
                    d = self._dir(note_id)
                    if d:
                        sessions.load(d).write("summary.md", md)
                        st = self._rev(note_id)
                        st["s"] += 1
                        rev = st["s"]
                self.emit("summary", {"id": note_id, "markdown": md, "rev": rev})
                self.emit("status", "Summary done.")
            except Cancelled:
                self.emit("summary", {"id": note_id, "markdown": None})
                self.emit("status", "Cancelled")
            except Exception as e:
                self.emit("summary", {"id": note_id, "markdown": None})
                self._err(f"Summary failed: {e}")
            finally:
                self._end_task(nid, "summary")

        threading.Thread(target=go, daemon=True).start()

    def shutdown(self):
        self.stop_recording()
        try:
            self.gpulibs.cancel()
        except Exception:  # noqa: BLE001
            log.info("gpu download cancel failed", exc_info=True)
