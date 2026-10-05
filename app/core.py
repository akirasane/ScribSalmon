"""UI-independent controller: recording, transcription queue, summaries, notes CRUD.

Talks to the UI only through `emit(event, payload)`; works with any front-end.
Events: text{id,text} summary{id,markdown} status str busy bool error str
        recording{id|None} level float notes (list changed)
"""
import queue
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import sessions
from .audio import Recorder
from .sessions import Session
from .settings import Settings
from .summarize import DEFAULT_PROMPT, review, summarize
from .transcribe import SAMPLE_RATE, load_wav, make_engine


class Controller:
    def __init__(self, emit: Callable[[str, object], None]):
        self.emit = emit
        self.s = Settings.load()
        self.lock = threading.RLock()
        self.engine_lock = threading.Lock()  # one transcription at a time per model
        self.q: "queue.Queue" = queue.Queue()
        self.engine = None
        self.worker: Optional[threading.Thread] = None
        self.recorder: Optional[Recorder] = None
        self.rec_session: Optional[Session] = None
        self.rec_path: Optional[Path] = None
        self.rec_started = 0.0

    # ---------------------------------------------------------------- whisper context hint
    def _prompt_for(self, note_id: Optional[str]) -> Optional[str]:
        """Vocabulary + the end of the transcript so far: helps Whisper spell names/terms
        consistently and continue the previous sentence across chunk boundaries."""
        parts = []
        if self.s.vocabulary.strip():
            parts.append(self.s.vocabulary.strip())
        if note_id:
            d = sessions.SESSIONS_DIR / note_id
            if d.is_dir():
                tail = sessions.load(d).read("transcript.txt").strip()[-160:]
                if tail:
                    parts.append(tail)
        return (" ".join(parts)[-400:]) or None

    # ---------------------------------------------------------------- helpers
    def _session(self, note_id: str) -> Session:
        if not note_id or Path(note_id).name != note_id:
            raise ValueError("Invalid note id.")
        d = sessions.SESSIONS_DIR / note_id
        if not d.is_dir():
            raise ValueError("Note not found.")
        return sessions.load(d)

    @staticmethod
    def _brief(s: Session) -> dict:
        return {"id": s.dir.name, "title": s.title, "created": s.created.isoformat(),
                "duration": s.duration, "parts": len(s.parts)}

    def _full(self, s: Session) -> dict:
        d = self._brief(s)
        d["transcript"] = s.read("transcript.txt")
        d["summary"] = s.read("summary.md")
        return d

    # ---------------------------------------------------------------- notes
    def list_notes(self, query: str = "") -> list:
        q = (query or "").strip().lower()
        out = []
        for s in sessions.list_all():
            if q and q not in s.title.lower() and q not in s.read("transcript.txt").lower() \
                    and q not in s.read("summary.md").lower():
                continue
            out.append(self._brief(s))
        return out

    def get_note(self, note_id: str) -> dict:
        return self._full(self._session(note_id))

    def create_note(self) -> dict:
        s = sessions.create()
        return self._full(s)

    def save_note(self, note_id: str, title: str, transcript: str, summary: str) -> dict:
        with self.lock:
            s = self._session(note_id)
            s.title = (title or "").strip() or s.title
            s.save_meta()
            s.write("transcript.txt", transcript or "")
            s.write("summary.md", summary or "")
            return self._brief(s)

    def delete_note(self, note_id: str) -> bool:
        s = self._session(note_id)
        if self.rec_session and self.rec_session.dir == s.dir:
            raise ValueError("Stop recording before deleting this note.")
        sessions.delete(s)
        return True

    def export_note(self, note_id: str, path: str) -> str:
        s = self._session(note_id)
        body = (f"# {s.title}\n\n{s.created:%Y-%m-%d %H:%M}\n\n{s.read('summary.md')}\n\n"
                f"## Transcript\n\n{s.read('transcript.txt')}\n")
        Path(path).write_text(body, encoding="utf-8")
        return path

    # ---------------------------------------------------------------- settings
    def get_settings(self) -> dict:
        from dataclasses import asdict
        d = asdict(self.s)
        d["default_prompt"] = DEFAULT_PROMPT.strip()
        return d

    def save_settings(self, data: dict) -> dict:
        prompt = (data.get("summary_prompt") or "").strip()
        if prompt == DEFAULT_PROMPT.strip():
            data["summary_prompt"] = ""
        for k, v in data.items():
            if hasattr(self.s, k) and k != "default_prompt":
                setattr(self.s, k, v)
        self.s.save()
        self.engine = None  # force model reload
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
                if self.q.empty():
                    self.emit("status", "Transcription finished.")
                    self.emit("busy", False)
                    self.emit("notes", None)
                continue
            try:
                if self.engine is None:
                    self.emit("status", "Loading speech model (first run downloads it)…")
                    self.emit("busy", True)
                    self.engine = make_engine(self.s)
                self.emit("busy", True)
                self.emit("status", f"Transcribing… ({self.q.qsize()} more waiting)")
                lang = None if self.s.language == "auto" else self.s.language
                with self.engine_lock:
                    text = self.engine.transcribe(audio, lang, self._prompt_for(note_id))
                if text:
                    with self.lock:
                        d = sessions.SESSIONS_DIR / note_id
                        if d.is_dir():
                            sessions.load(d).append("transcript.txt", text)
                    self.emit("text", {"id": note_id, "text": text})
            except Exception as e:
                self.emit("error", f"Transcription failed: {e}")
                self.engine = None
            finally:
                self.q.task_done()
                if self.q.empty():
                    self.emit("busy", False)

    def _transcribe_file(self, note_id: str, path: Path):
        self._ensure_worker()

        def feed():
            try:
                a = load_wav(path)
                step = 30 * SAMPLE_RATE
                for i in range(0, len(a), step):
                    self.q.put((note_id, a[i:i + step]))
                self.q.put((note_id, None))
            except Exception as e:
                self.emit("error", f"Transcription of {Path(path).name} failed: {e}")

        threading.Thread(target=feed, daemon=True).start()
        self.emit("status", "Transcribing file…")

    # ---------------------------------------------------------------- recording
    def start_recording(self, note_id: str, opts: dict) -> dict:
        if self.recorder:
            raise ValueError("Already recording.")
        for k_js, k in (("system", "use_system"), ("mic", "use_mic"), ("engine", "engine"),
                        ("language", "language")):
            if k_js in opts:
                setattr(self.s, k, opts[k_js])
        if not (self.s.use_system or self.s.use_mic):
            raise ValueError("Pick system audio and/or microphone.")
        self.s.save()
        s = self._session(note_id)
        self._ensure_worker()
        self.rec_session = s
        self.rec_path = s.next_part_path()
        live = self.s.live_transcript
        nid = s.dir.name
        self.recorder = Recorder(self.rec_path, self.s.use_system, self.s.use_mic,
                                 on_chunk=(lambda a: self.q.put((nid, a))) if live else (lambda a: None),
                                 on_error=lambda m: self.emit("error", m))
        self.recorder.start()
        self.rec_started = time.time()
        threading.Thread(target=self._level_loop, args=(self.recorder,), daemon=True).start()
        self.emit("status", "Recording…" if live else "Recording (transcribe after Stop)…")
        self.emit("recording", {"id": nid, "started": self.rec_started})
        return {"id": nid, "started": self.rec_started}

    def _level_loop(self, rec: Recorder):
        while self.recorder is rec:
            self.emit("level", rec.level)
            time.sleep(0.08)

    def stop_recording(self) -> dict:
        rec, sess, path = self.recorder, self.rec_session, self.rec_path
        if not rec or not sess:
            return {}
        self.recorder = None  # ends the level loop
        rec.stop()
        nid = sess.dir.name
        if self.s.live_transcript:
            self.q.put((nid, None))
        else:
            self._transcribe_file(nid, path)
        self.rec_session = None
        self.emit("recording", {"id": None})
        self.emit("status", "Recording saved. Transcribing…")
        self.emit("notes", None)
        return self._brief(self._session(nid))

    def import_wav(self, note_id: str, path: str) -> dict:
        s = self._session(note_id)
        dest = s.next_part_path("import")
        shutil.copy2(path, dest)
        self._transcribe_file(s.dir.name, dest)
        self.emit("notes", None)
        return self._brief(s)

    def retranscribe(self, note_id: str) -> bool:
        """Re-run speech-to-text over the WHOLE recording(s) with full context (more accurate than
        live 6 s chunks). Replaces the transcript."""
        s = self._session(note_id)
        if self.rec_session and self.rec_session.dir == s.dir:
            raise ValueError("Stop recording first.")
        parts = s.parts
        if not parts:
            raise ValueError("This note has no recording to refine.")
        self.emit("busy", True)

        def go():
            try:
                if self.engine is None:
                    self.emit("status", "Loading speech model (first run downloads it)…")
                    self.engine = make_engine(self.s)
                lang = None if self.s.language == "auto" else self.s.language
                texts = []
                for i, p in enumerate(parts, 1):
                    self.emit("status", f"Refining transcript… recording {i}/{len(parts)} (this can take a while)")
                    a = load_wav(p)
                    with self.engine_lock:
                        t = self.engine.transcribe(a, lang, self._prompt_for(None), long_form=True)
                    if t:
                        texts.append(t)
                full = "\n".join(texts).strip() + "\n"
                with self.lock:
                    s.write("transcript.txt", full)
                self.emit("transcript", {"id": note_id, "text": full})
                self.emit("status", "Transcript refined.")
            except Exception as e:
                self.emit("error", f"Refine failed: {e}")
            finally:
                self.emit("busy", False)

        threading.Thread(target=go, daemon=True).start()
        return True

    # ---------------------------------------------------------------- Thai/word review
    def review(self, note_id: str, transcript: str) -> bool:
        self.emit("busy", True)
        self.emit("status", "Checking transcript for garbled words…")

        def go():
            try:
                items = review(transcript, self.s.summary_backend, self.s.anthropic_key,
                               self.s.claude_model, self.s.vocabulary)
                self.emit("review", {"id": note_id, "items": items})
                self.emit("status", f"Found {len(items)} phrase(s) to check." if items else "Nothing suspicious found.")
            except Exception as e:
                self.emit("review", {"id": note_id, "items": None})
                self.emit("error", f"Review failed: {e}")
            finally:
                self.emit("busy", False)

        threading.Thread(target=go, daemon=True).start()
        return True

    # ---------------------------------------------------------------- summary
    def summarize(self, note_id: str, transcript: str) -> None:
        self.emit("busy", True)
        self.emit("status", "Summarizing with Claude… (CLI can take ~30 s)")

        def go():
            try:
                md = summarize(transcript, self.s.summary_backend, self.s.anthropic_key,
                               self.s.claude_model, self.s.summary_prompt)
                with self.lock:
                    d = sessions.SESSIONS_DIR / note_id
                    if d.is_dir():
                        sessions.load(d).write("summary.md", md)
                self.emit("summary", {"id": note_id, "markdown": md})
                self.emit("status", "Summary done.")
            except Exception as e:
                self.emit("summary", {"id": note_id, "markdown": None})
                self.emit("error", f"Summary failed: {e}")
            finally:
                self.emit("busy", False)

        threading.Thread(target=go, daemon=True).start()

    def shutdown(self):
        if self.recorder:
            self.stop_recording()
