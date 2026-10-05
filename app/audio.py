"""Capture system audio (WASAPI loopback) + microphone, mix to 16 kHz mono."""
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Callable, Optional

import numpy as np

SAMPLE_RATE = 16000
BLOCK = 1600  # 0.1 s


class _Source(threading.Thread):
    def __init__(self, mic, stop: threading.Event):
        super().__init__(daemon=True)
        self.mic, self.stop_evt = mic, stop
        self.buf: deque = deque()
        self.lock = threading.Lock()
        self.error: Optional[Exception] = None

    def run(self):
        try:
            with self.mic.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK) as rec:
                while not self.stop_evt.is_set():
                    data = rec.record(numframes=BLOCK)[:, 0].astype(np.float32)
                    with self.lock:
                        self.buf.append(data)
        except Exception as e:  # device vanished, etc.
            self.error = e

    def drain(self) -> np.ndarray:
        with self.lock:
            chunks = list(self.buf)
            self.buf.clear()
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


class _MicSource(threading.Thread):
    """Microphone via PortAudio (soundcard asserts on some mic formats)."""

    def __init__(self, stop: threading.Event):
        super().__init__(daemon=True)
        self.stop_evt = stop
        self.buf: deque = deque()
        self.lock = threading.Lock()
        self.error: Optional[Exception] = None

    def _cb(self, indata, frames, t, status):
        with self.lock:
            self.buf.append(indata[:, 0].copy())

    def run(self):
        try:
            import sounddevice as sd  # lazy: keep COM init off the Qt main thread
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._cb):
                self.stop_evt.wait()
        except Exception as e:
            self.error = e

    drain = _Source.drain


class Recorder:
    """Records to a WAV file; calls on_chunk(np.float32 array) every `chunk_sec` of audio."""

    def __init__(self, wav_path: Path, use_system: bool, use_mic: bool,
                 on_chunk: Callable[[np.ndarray], None], on_error: Callable[[str], None],
                 chunk_sec: float = 6.0):
        self.wav_path, self.use_system, self.use_mic = wav_path, use_system, use_mic
        self.on_chunk, self.on_error, self.chunk_sec = on_chunk, on_error, chunk_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.level = 0.0

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self):
        sources = []
        try:
            import soundcard as sc  # lazy: keep COM init off the Qt main thread
            if self.use_system:
                spk = sc.default_speaker()
                sources.append(_Source(sc.get_microphone(id=str(spk.name), include_loopback=True), self._stop))
            if self.use_mic:
                sources.append(_MicSource(self._stop))
        except Exception as e:
            self.on_error(f"Audio device error: {e}")
            return
        if not sources:
            self.on_error("No audio source selected.")
            return
        for s in sources:
            s.start()

        pending = []
        pending_len = 0
        target = int(self.chunk_sec * SAMPLE_RATE)
        with wave.open(str(self.wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            while not self._stop.is_set():
                time.sleep(0.1)
                mixed = self._mix([s.drain() for s in sources])
                for s in sources:
                    if s.error:
                        self.on_error(f"Audio source failed: {s.error}")
                        s.error = None
                if not len(mixed):
                    continue
                self.level = float(np.sqrt(np.mean(mixed ** 2)))
                wf.writeframes((np.clip(mixed, -1, 1) * 32767).astype(np.int16).tobytes())
                pending.append(mixed)
                pending_len += len(mixed)
                if pending_len >= target:
                    self.on_chunk(np.concatenate(pending))
                    pending, pending_len = [], 0
            # final flush
            tail = self._mix([s.drain() for s in sources])
            if len(tail):
                wf.writeframes((np.clip(tail, -1, 1) * 32767).astype(np.int16).tobytes())
                pending.append(tail)
            if pending:
                self.on_chunk(np.concatenate(pending))

    @staticmethod
    def _mix(parts):
        n = max((len(p) for p in parts), default=0)
        if n == 0:
            return np.zeros(0, np.float32)
        out = np.zeros(n, np.float32)
        for p in parts:
            out[: len(p)] += p
        return out
