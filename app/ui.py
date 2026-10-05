import queue
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QTextEdit, QVBoxLayout, QWidget)

from . import sessions, theme
from .audio import Recorder
from .sessions import Session
from .settings import Settings
from .summarize import DEFAULT_PROMPT, summarize
from .transcribe import SAMPLE_RATE, load_wav, make_engine
from .widgets import (ROLE_META, BusyBar, GlowButton, LevelMeter, NoteDelegate, Toggle, fade_in,
                      fade_window)


def _label(text: str, name: str = "") -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    return lb


def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


class Bus(QObject):
    text = Signal(str, str)      # session dir, text
    summary = Signal(str, str)   # session dir, markdown
    status = Signal(str)
    error = Signal(str)
    busy = Signal(bool)


class SettingsDialog(QDialog):
    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(660, 760)
        self.s = s
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(14)
        root.addWidget(_label("Settings", "brand"))

        self.live = Toggle("Live transcript while recording")
        self.live.setChecked(s.live_transcript)
        root.addWidget(self.live)
        root.addWidget(_label("Off = record only (light on CPU), transcribe after Stop.", "muted"))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        self.model = QComboBox()
        self.model.addItems(["tiny", "base", "small", "medium", "large-v3"])
        self.model.setCurrentText(s.whisper_model)
        self.backend = QComboBox()
        self.backend.addItem("Auto (Claude Code CLI if installed, else API key)", "auto")
        self.backend.addItem("Claude Code CLI (uses your Claude Code login)", "cli")
        self.backend.addItem("Anthropic API key", "api")
        self.backend.setCurrentIndex(max(0, self.backend.findData(s.summary_backend)))
        self.akey = QLineEdit(s.anthropic_key)
        self.akey.setEchoMode(QLineEdit.Password)
        self.okey = QLineEdit(s.openai_key)
        self.okey.setEchoMode(QLineEdit.Password)
        self.cmodel = QLineEdit(s.claude_model)
        form.addRow(_label("Local Whisper model", "muted"), self.model)
        form.addRow(_label("Summary backend", "muted"), self.backend)
        form.addRow(_label("Anthropic API key", "muted"), self.akey)
        form.addRow(_label("OpenAI API key", "muted"), self.okey)
        form.addRow(_label("Claude model (API)", "muted"), self.cmodel)
        root.addLayout(form)

        root.addWidget(_label("SUMMARY PROMPT", "h"))
        root.addWidget(_label("Use {transcript} to place the text; otherwise it is appended at the end.", "muted"))
        self.prompt = QPlainTextEdit(s.summary_prompt.strip() or DEFAULT_PROMPT.strip())
        self.prompt.setMinimumHeight(200)
        pc = _card()
        pl = QVBoxLayout(pc)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.addWidget(self.prompt)
        root.addWidget(pc, 1)
        reset = GlowButton("Reset prompt to default", "ghost")
        reset.clicked.connect(lambda: self.prompt.setPlainText(DEFAULT_PROMPT.strip()))
        rr = QHBoxLayout()
        rr.addWidget(reset)
        rr.addStretch()
        root.addLayout(rr)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def showEvent(self, e):
        super().showEvent(e)
        theme.dark_titlebar(self)
        if not getattr(self, "_shown", False):
            self._shown = True
            fade_window(self, 220)

    def apply(self):
        self.s.live_transcript = self.live.isChecked()
        self.s.summary_backend = self.backend.currentData()
        p = self.prompt.toPlainText().strip()
        self.s.summary_prompt = "" if p == DEFAULT_PROMPT.strip() else p
        self.s.whisper_model = self.model.currentText()
        self.s.anthropic_key = self.akey.text().strip()
        self.s.openai_key = self.okey.text().strip()
        self.s.claude_model = self.cmodel.text().strip() or "claude-sonnet-5-5"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScribSalmon")
        self.resize(1280, 800)
        self.setMinimumSize(980, 640)
        self.s = Settings.load()
        self.bus = Bus()
        self.recorder: Optional[Recorder] = None
        self.rec_session: Optional[Session] = None
        self.engine = None
        self.q: "queue.Queue" = queue.Queue()
        self.worker = None
        self.cur: Optional[Session] = None
        self.t0 = None
        self._loading = False
        self._last_sec = -1

        self.bus.text.connect(self._on_text)
        self.bus.summary.connect(self._on_summary)
        self.bus.status.connect(lambda m: self.status.setText(m))
        self.bus.error.connect(lambda m: QMessageBox.warning(self, "Error", m))
        self.bus.busy.connect(lambda b: self.busy_bar.setBusy(b))

        self._build_ui()
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(800)
        self.autosave.timeout.connect(self._save_current)
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self.refresh_list()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._show(None)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_shown", False):
            self._shown = True
            theme.dark_titlebar(self)
            fade_window(self)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        # ---- sidebar
        brand = _label("◉  ScribSalmon", "brand")
        sub = _label("Meeting notes", "muted")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes…")
        self.search.textChanged.connect(self.refresh_list)
        self.list = QListWidget()
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(NoteDelegate(self.list))
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._on_select)
        self.new_btn = GlowButton("+  New note", "primary")
        self.del_btn = GlowButton("Delete", "ghost")
        self.new_btn.clicked.connect(self.new_note)
        self.del_btn.clicked.connect(self.delete_note)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setMinimumWidth(270)
        side.setMaximumWidth(360)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(18, 22, 10, 16)
        sv.setSpacing(6)
        sv.addWidget(brand)
        sv.addWidget(sub)
        sv.addSpacing(12)
        sv.addWidget(self.search)
        sv.addSpacing(6)
        sv.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(0)
        row.addWidget(self.new_btn, 1)
        row.addWidget(self.del_btn)
        sv.addLayout(row)

        # ---- detail header
        self.title = QLineEdit()
        self.title.setObjectName("title")
        self.title.setPlaceholderText("Untitled note")
        self.info = _label("", "muted")

        # ---- control card
        self.rec_btn = GlowButton("Record", "ghost", dot=True)
        self.stop_btn = GlowButton("Stop", "ghost")
        self.stop_btn.setEnabled(False)
        self.timer_lbl = _label("00:00", "timer")
        self.timer_lbl.setMinimumWidth(56)
        self.meter = LevelMeter()
        self.sys_chk = Toggle("System audio")
        self.sys_chk.setChecked(self.s.use_system)
        self.mic_chk = Toggle("Microphone")
        self.mic_chk.setChecked(self.s.use_mic)
        self.engine_cb = QComboBox()
        self.engine_cb.addItem("Local Whisper", "local")
        self.engine_cb.addItem("OpenAI Whisper (cloud)", "openai")
        self.engine_cb.setCurrentIndex(0 if self.s.engine == "local" else 1)
        self.lang_cb = QComboBox()
        for label, code in (("Auto-detect", "auto"), ("Thai", "th"), ("English", "en")):
            self.lang_cb.addItem(label, code)
        self.lang_cb.setCurrentIndex(max(0, self.lang_cb.findData(self.s.language)))
        self.import_btn = GlowButton("Add WAV…", "ghost")
        self.set_btn = GlowButton("Settings", "ghost")

        ctl = _card()
        cv = QVBoxLayout(ctl)
        cv.setContentsMargins(14, 10, 14, 10)
        cv.setSpacing(6)
        r1 = QHBoxLayout()
        r1.setSpacing(2)
        r1.addWidget(self.rec_btn)
        r1.addWidget(self.stop_btn)
        r1.addSpacing(10)
        r1.addWidget(self.timer_lbl)
        r1.addSpacing(8)
        r1.addWidget(self.meter, 1)
        cv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(14)
        r2.addWidget(self.sys_chk)
        r2.addWidget(self.mic_chk)
        r2.addStretch()
        r2.addWidget(self.engine_cb)
        r2.addWidget(self.lang_cb)
        r2.addSpacing(4)
        r2.addWidget(self.import_btn)
        r2.addWidget(self.set_btn)
        cv.addLayout(r2)

        # ---- transcript / summary cards
        self.transcript = QPlainTextEdit()
        self.transcript.setPlaceholderText("Transcript appears here (editable)…")
        self.summary = QTextEdit()
        self.summary.setPlaceholderText("Press Summarize to generate numbered meeting notes (editable)…")
        self.summary.document().setDefaultStyleSheet(
            f"h2 {{ color: {theme.ACCENT}; }} h1 {{ color: {theme.ACCENT}; }}")
        self.sum_btn = GlowButton("Summarize", "primary")
        self.export_btn = GlowButton("Export…", "ghost")

        tc, sc = _card(), _card()
        tl, sl = QVBoxLayout(tc), QVBoxLayout(sc)
        for lay in (tl, sl):
            lay.setContentsMargins(18, 14, 14, 14)
            lay.setSpacing(6)
        th = QHBoxLayout()
        th.addWidget(_label("TRANSCRIPT", "h"))
        th.addStretch()
        tl.addLayout(th)
        tl.addWidget(self.transcript, 1)
        sh = QHBoxLayout()
        sh.addWidget(_label("SUMMARY", "h"))
        sh.addStretch()
        sh.addWidget(self.sum_btn)
        sh.addWidget(self.export_btn)
        sl.addLayout(sh)
        sl.addWidget(self.summary, 1)
        panes = QSplitter(Qt.Horizontal)
        panes.setHandleWidth(12)
        panes.addWidget(tc)
        panes.addWidget(sc)
        panes.setStretchFactor(0, 1)
        panes.setStretchFactor(1, 1)
        panes.setSizes([500, 500])

        self.detail = QWidget()
        dv = QVBoxLayout(self.detail)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)
        dv.addWidget(self.title)
        dv.addWidget(self.info)
        dv.addSpacing(4)
        dv.addWidget(ctl)
        dv.addWidget(panes, 1)

        # ---- empty state
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setAlignment(Qt.AlignCenter)
        ev.setSpacing(8)
        for w in (_label("◉", "glyph"), _label("No notes yet", "emptyTitle"),
                  _label("Create a note, then record a meeting.", "muted")):
            w.setAlignment(Qt.AlignCenter)
            ev.addWidget(w)
        ev.addSpacing(10)
        first = GlowButton("+  Create your first note", "primary")
        first.clicked.connect(self.new_note)
        ev.addWidget(first, 0, Qt.AlignCenter)

        # ---- main area
        self.busy_bar = BusyBar()
        self.status = _label("Ready", "status")
        main = QWidget()
        main.setObjectName("main")
        mv = QVBoxLayout(main)
        mv.setContentsMargins(30, 24, 30, 10)
        mv.setSpacing(8)
        mv.addWidget(self.detail, 1)
        mv.addWidget(self.empty, 1)
        mv.addWidget(self.busy_bar)
        mv.addWidget(self.status)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        split.addWidget(side)
        split.addWidget(main)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 980])
        self.setCentralWidget(split)

        self.rec_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.import_btn.clicked.connect(self.import_wav)
        self.sum_btn.clicked.connect(self.run_summary)
        self.export_btn.clicked.connect(self.export_note)
        self.set_btn.clicked.connect(self.open_settings)
        for w in (self.transcript, self.summary):
            w.textChanged.connect(self._dirty)
        self.title.textChanged.connect(self._dirty)

    # ------------------------------------------------------------ list / selection
    def refresh_list(self, *_):
        keep = self.cur.dir if self.cur else None
        q = self.search.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        sel = None
        for s in sessions.list_all():
            if q and q not in s.title.lower() and q not in s.read("transcript.txt").lower() \
                    and q not in s.read("summary.md").lower():
                continue
            it = QListWidgetItem()
            self._fill_item(it, s)
            self.list.addItem(it)
            if keep and s.dir == keep:
                sel = it
        if sel:
            self.list.setCurrentItem(sel)
        self.list.blockSignals(False)

    @staticmethod
    def _fill_item(it, s: Session):
        it.setText(s.title)
        it.setData(ROLE_META, f"{s.created:%Y-%m-%d %H:%M}  ·  {sessions.fmt_duration(s.duration)}")
        it.setData(Qt.UserRole, s)

    def _on_select(self, item, _prev=None):
        self._save_current()
        self._show(item.data(Qt.UserRole) if item else None)

    def _show(self, s: Optional[Session]):
        self._loading = True
        self.cur = s
        self.detail.setVisible(s is not None)
        self.empty.setVisible(s is None)
        if s:
            self.title.setText(s.title)
            self.transcript.setPlainText(s.read("transcript.txt"))
            md = s.read("summary.md")
            self.summary.setMarkdown(md) if md else self.summary.clear()
            self._update_info()
            fade_in(self.detail)
        else:
            fade_in(self.empty)
        self._loading = False
        self._update_buttons()

    def _update_info(self):
        if self.cur:
            n = len(self.cur.parts)
            self.info.setText(f"{self.cur.created:%Y-%m-%d %H:%M}  ·  {n} recording(s)  ·  "
                              f"{sessions.fmt_duration(self.cur.duration)}")

    def _update_buttons(self):
        rec = self.recorder is not None
        mine = rec and self.cur is not None and self.rec_session and self.rec_session.dir == self.cur.dir
        self.rec_btn.setEnabled(not rec and self.cur is not None)
        self.rec_btn.setLive(bool(mine))
        self.rec_btn.setText("Recording" if mine else ("Record more" if (self.cur and self.cur.parts) else "Record"))
        self.stop_btn.setEnabled(bool(mine))

    # ------------------------------------------------------------ notes CRUD
    def new_note(self):
        self._save_current()
        s = sessions.create()
        self.search.clear()
        self.cur = s
        self.refresh_list()
        self._show(s)
        self.title.setFocus()
        self.title.selectAll()

    def delete_note(self):
        if not self.cur:
            return
        if self.recorder and self.rec_session and self.rec_session.dir == self.cur.dir:
            QMessageBox.information(self, "Busy", "Stop recording before deleting this note.")
            return
        r = QMessageBox.question(self, "Delete note",
                                 f"Permanently delete “{self.cur.title}” and its recordings?",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        sessions.delete(self.cur)
        self.cur = None
        self.refresh_list()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._show(None)

    def _dirty(self):
        if not self._loading and self.cur:
            self.autosave.start()

    def _save_current(self):
        self.autosave.stop()
        s = self.cur
        if not s or not s.dir.exists():
            return
        s.title = self.title.text().strip() or s.title
        s.save_meta()
        s.write("transcript.txt", self.transcript.toPlainText())
        s.write("summary.md", self.summary.toMarkdown() if self.summary.toPlainText().strip() else "")
        it = self.list.currentItem()
        if it and it.data(Qt.UserRole).dir == s.dir:
            self._fill_item(it, s)

    def export_note(self):
        if not self.cur:
            return
        self._save_current()
        path, _ = QFileDialog.getSaveFileName(self, "Export note", f"{self.cur.title}.md", "Markdown (*.md)")
        if path:
            body = (f"# {self.cur.title}\n\n{self.cur.created:%Y-%m-%d %H:%M}\n\n"
                    f"{self.cur.read('summary.md')}\n\n## Transcript\n\n{self.cur.read('transcript.txt')}\n")
            Path(path).write_text(body, encoding="utf-8")
            self.status.setText(f"Exported to {path}")

    # ------------------------------------------------------------ misc
    def _persist_choices(self):
        self.s.engine = self.engine_cb.currentData()
        self.s.language = self.lang_cb.currentData()
        self.s.use_system = self.sys_chk.isChecked()
        self.s.use_mic = self.mic_chk.isChecked()
        self.s.save()

    def _tick(self):
        if self.t0 and self.recorder:
            sec = int((datetime.now() - self.t0).total_seconds())
            if sec != self._last_sec:
                self._last_sec = sec
                self.timer_lbl.setText(f"{sec // 60:02d}:{sec % 60:02d}")
            self.meter.setLevel(self.recorder.level)

    def open_settings(self):
        d = SettingsDialog(self.s, self)
        if d.exec():
            d.apply()
            self.s.save()
            self.engine = None  # force reload

    # ------------------------------------------------------------ transcription worker
    def _ensure_worker(self):
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def _work(self):
        while True:
            d, audio = self.q.get()
            if audio is None:
                self.q.task_done()
                if self.q.empty():
                    self.bus.status.emit("Transcription finished.")
                    self.bus.busy.emit(False)
                continue
            try:
                if self.engine is None:
                    self.bus.status.emit("Loading speech model (first run downloads it)…")
                    self.bus.busy.emit(True)
                    self.engine = make_engine(self.s)
                self.bus.busy.emit(True)
                self.bus.status.emit(f"Transcribing… ({self.q.qsize()} more waiting)")
                lang = None if self.s.language == "auto" else self.s.language
                self.bus.text.emit(d, self.engine.transcribe(audio, lang))
            except Exception as e:
                self.bus.error.emit(f"Transcription failed: {e}")
                self.engine = None
            finally:
                self.q.task_done()
                if self.q.empty():
                    self.bus.busy.emit(False)

    def _on_text(self, d: str, text: str):
        if not text:
            return
        if self.cur and str(self.cur.dir) == d:
            self.transcript.appendPlainText(text)  # autosave persists it
            self._save_current()
        elif Path(d).exists():
            sessions.load(Path(d)).append("transcript.txt", text)

    def _on_summary(self, d: str, md: str):
        if self.cur and str(self.cur.dir) == d:
            self.summary.setMarkdown(md)
            self._save_current()
        elif Path(d).exists():
            sessions.load(Path(d)).write("summary.md", md)

    # ------------------------------------------------------------ recording
    def start_recording(self):
        if not self.cur or self.recorder:
            return
        if not (self.sys_chk.isChecked() or self.mic_chk.isChecked()):
            QMessageBox.information(self, "Source", "Pick system audio and/or microphone.")
            return
        self._persist_choices()
        self._save_current()
        self.rec_session = self.cur
        d = str(self.cur.dir)
        self._ensure_worker()
        self.rec_path = self.cur.next_part_path()
        live = self.s.live_transcript
        self.recorder = Recorder(self.rec_path, self.s.use_system, self.s.use_mic,
                                 on_chunk=(lambda a: self.q.put((d, a))) if live else (lambda a: None),
                                 on_error=self.bus.error.emit)
        self.recorder.start()
        self.t0 = datetime.now()
        self._last_sec = -1
        self.timer_lbl.setStyleSheet(f"color: {theme.DANGER};")
        self.meter.setActive(True)
        self.tick.start(60)
        self.status.setText("Recording…" if live else "Recording (transcribe after Stop)…")
        self._update_buttons()

    def stop_recording(self):
        if not self.recorder:
            return
        self.stop_btn.setEnabled(False)
        self.status.setText("Stopping…")
        self.recorder.stop()
        self.recorder = None
        self.tick.stop()
        self.t0 = None
        self.timer_lbl.setText("00:00")
        self.timer_lbl.setStyleSheet("")
        self.meter.setActive(False)
        d = str(self.rec_session.dir)
        if self.s.live_transcript:
            self.q.put((d, None))
        else:
            self._transcribe_file(d, self.rec_path)
        self.rec_session = None
        self.status.setText("Recording saved. Transcribing…")
        self._update_info()
        self.refresh_list()
        self._update_buttons()

    def import_wav(self):
        if not self.cur:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Add WAV", "", "WAV (*.wav)")
        if not path:
            return
        self._persist_choices()
        self._save_current()
        s = self.cur
        d = str(s.dir)
        dest = s.next_part_path("import")
        shutil.copy2(path, dest)
        self._update_info()
        self._transcribe_file(d, dest)

    def _transcribe_file(self, d: str, path: Path):
        """Queue a whole WAV for transcription in 30 s pieces."""
        self._ensure_worker()

        def feed():
            try:
                a = load_wav(path)
                step = 30 * SAMPLE_RATE
                for i in range(0, len(a), step):
                    self.q.put((d, a[i:i + step]))
                self.q.put((d, None))
            except Exception as e:
                self.bus.error.emit(f"Transcription of {Path(path).name} failed: {e}")

        threading.Thread(target=feed, daemon=True).start()
        self.status.setText("Transcribing file…")

    # ------------------------------------------------------------ summary
    def run_summary(self):
        if not self.cur:
            return
        d, text = str(self.cur.dir), self.transcript.toPlainText()
        self.bus.busy.emit(True)
        self.bus.status.emit("Summarizing with Claude… (CLI can take ~30 s)")
        self.sum_btn.setEnabled(False)

        def go():
            try:
                self.bus.summary.emit(d, summarize(text, self.s.summary_backend, self.s.anthropic_key, self.s.claude_model,
                                                      self.s.summary_prompt))
                self.bus.status.emit("Summary done.")
            except Exception as e:
                self.bus.error.emit(f"Summary failed: {e}")
            finally:
                self.bus.busy.emit(False)
                QTimer.singleShot(0, lambda: self.sum_btn.setEnabled(True))

        threading.Thread(target=go, daemon=True).start()

    def closeEvent(self, e):
        if self.recorder:
            self.recorder.stop()
        self._save_current()
        e.accept()
