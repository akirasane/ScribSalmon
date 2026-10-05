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


def _com_init() -> bool:
    """CoInitializeEx(MTA) on this thread; True if we must CoUninitialize later."""
    try:
        import ctypes
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0x0) & 0xFFFFFFFF
        return hr in (0, 1)  # S_OK / S_FALSE (already initialised, still ref-counted)
    except Exception:
        return False


def _com_uninit(owned: bool) -> None:
    if owned:
        try:
            import ctypes
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass


def pick_cut(block_rms: list, min_blocks: int = 40, max_blocks: int = 100,
             silence_rms: float = 0.01) -> Optional[int]:
    """Choose where to cut a live chunk, working on 0.1 s blocks of pending audio.

    Returns None (keep accumulating) or the exclusive end index: the chunk is blocks[:cut].
    Nothing is cut before `min_blocks`. Candidate cuts are after the blocks in
    [min_blocks-1, min(n, max_blocks)-1]; the quietest one wins, the LAST of equal minima.
    Before `max_blocks` the cut is taken only when that block is a real pause (rms below
    `silence_rms`, or well below the average of the window); at `max_blocks` it is forced.
    """
    n = len(block_rms)
    if n < min_blocks or min_blocks < 1:
        return None
    hi = min(n, max_blocks)
    window = block_rms[min_blocks - 1:hi]
    lowest = min(window)
    idx = min_blocks - 1 + max(i for i, v in enumerate(window) if v == lowest)
    if n >= max_blocks:
        return idx + 1
    if lowest < silence_rms or lowest < 0.3 * (sum(window) / len(window)):
        return idx + 1
    return None


class _LoopSource(threading.Thread):
    """System audio via WASAPI loopback (soundcard). All COM work happens inside this thread."""

    def __init__(self, stop: threading.Event):
        super().__init__(daemon=True)
        self.stop_evt = stop
        self.buf: deque = deque()
        self.lock = threading.Lock()
        self.error: Optional[Exception] = None
        self.ready = threading.Event()

    def run(self):
        com = False
        try:
            import soundcard as sc  # lazy; must come first (its import-time COM init rejects S_FALSE)
            com = _com_init()  # ...and it only initialises COM in the thread that first imports it
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            with mic.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK) as rec:
                self.ready.set()
                while not self.stop_evt.is_set():
                    data = rec.record(numframes=BLOCK)[:, 0].astype(np.float32)
                    with self.lock:
                        self.buf.append(data)
        except Exception as e:  # no device, device vanished, etc.
            self.error = e
        finally:
            self.ready.set()
            _com_uninit(com)

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
        self.ready = threading.Event()

    def _cb(self, indata, frames, t, status):
        with self.lock:
            self.buf.append(indata[:, 0].copy())

    def run(self):
        try:
            import sounddevice as sd  # lazy
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._cb):
                self.ready.set()
                self.stop_evt.wait()
        except Exception as e:
            self.error = e
        finally:
            self.ready.set()

    drain = _LoopSource.drain


class Recorder:
    """Records to a WAV file; calls on_chunk(np.float32 array) with live chunks cut at pauses.

    `chunk_sec` is the nominal chunk length: chunks are at least 2/3 of it and at most 5/3 of it
    (default 6.0 -> min 4 s, hard max 10 s), cut at the quietest 0.1 s block (see pick_cut).
    The WAV always receives the full audio."""

    def __init__(self, wav_path: Path, use_system: bool, use_mic: bool,
                 on_chunk: Callable[[np.ndarray], None], on_error: Callable[[str], None],
                 chunk_sec: float = 6.0, on_dead: Optional[Callable[[], None]] = None):
        self.wav_path, self.use_system, self.use_mic = wav_path, use_system, use_mic
        self.on_chunk, self.on_error, self.chunk_sec = on_chunk, on_error, chunk_sec
        self.on_dead = on_dead
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._wf = None
        self._sources: list = []
        self.level = 0.0

    def start(self, timeout: float = 3.0):
        sources = []
        if self.use_system:
            sources.append(_LoopSource(self._stop))
        if self.use_mic:
            sources.append(_MicSource(self._stop))
        if not sources:
            raise RuntimeError("No audio source selected.")

        wf = wave.open(str(self.wav_path), "wb")  # OSError propagates
        try:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
        except Exception:
            wf.close()
            raise

        for s in sources:
            s.start()
        deadline = time.monotonic() + timeout
        for s in sources:
            s.ready.wait(max(0.0, deadline - time.monotonic()))
        # a source that is not ready by the deadline counts as failed
        failed = [s for s in sources if s.error or not s.ready.is_set()]
        ok = [s for s in sources if s not in failed]
        if not ok:
            self._stop.set()
            try:
                wf.close()
            except Exception:
                pass
            try:
                self.wav_path.unlink()
            except OSError:
                pass
            msg = "; ".join(str(s.error) for s in sources if s.error) or "timed out opening audio device"
            raise RuntimeError("Audio device error: " + msg)
        for s in failed:
            self.on_error(f"Audio source failed: {s.error or 'timed out opening device'}")
            s.error = None

        self._wf = wf
        self._sources = ok
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t is not threading.current_thread():
            t.join(timeout=10)

    def _run(self):
        sources = self._sources
        wf = self._wf
        blocks: list = []   # (samples, rms) 0.1 s blocks since the last cut
        carry = np.zeros(0, np.float32)
        min_blocks = max(1, round(self.chunk_sec * 10 * 2 / 3))
        max_blocks = max(min_blocks + 1, round(self.chunk_sec * 10 * 5 / 3))
        dead = False
        try:
            while not self._stop.is_set():
                time.sleep(0.1)
                mixed = self._mix([s.drain() for s in sources])
                for s in sources:
                    if s.error:
                        self.on_error(f"Audio source failed: {s.error}")
                        s.error = None
                if len(mixed):
                    self.level = float(np.sqrt(np.mean(mixed ** 2)))
                    wf.writeframes((np.clip(mixed, -1, 1) * 32767).astype(np.int16).tobytes())
                    carry = np.concatenate([carry, mixed]) if len(carry) else mixed
                    while len(carry) >= BLOCK:
                        blk, carry = carry[:BLOCK], carry[BLOCK:]
                        blocks.append((blk, float(np.sqrt(np.mean(blk ** 2)))))
                    while True:
                        cut = pick_cut([r for _, r in blocks], min_blocks, max_blocks)
                        if cut is None:
                            break
                        self.on_chunk(np.concatenate([b_[0] for b_ in blocks[:cut]]))
                        blocks = blocks[cut:]
                if all(not s.is_alive() for s in sources):
                    dead = True
                    break
            # final flush
            tail = self._mix([s.drain() for s in sources])
            if len(tail):
                wf.writeframes((np.clip(tail, -1, 1) * 32767).astype(np.int16).tobytes())
                carry = np.concatenate([carry, tail]) if len(carry) else tail
            rest = [b_[0] for b_ in blocks] + ([carry] if len(carry) else [])
            if rest:
                self.on_chunk(np.concatenate(rest))
        finally:
            try:
                wf.close()
            except Exception:
                pass
        if dead and not self._stop.is_set() and self.on_dead:
            self.on_dead()

    @staticmethod
    def _mix(parts):
        n = max((len(p) for p in parts), default=0)
        if n == 0:
            return np.zeros(0, np.float32)
        out = np.zeros(n, np.float32)
        for p in parts:
            out[: len(p)] += p
        return out
