"""Pluggable speech-to-text engines."""
import gc
import io
import logging
import os
import re
import time
import wave
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from . import gpu
from .errors import Cancelled

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SILENCE_RMS = 0.003


def is_silent(audio: np.ndarray, strict: bool = False) -> bool:
    """Skip-transcription gate. Default (local engine): only near-digital-silence, since the VAD filters the
    rest and a fixed RMS gate drops quiet speech. strict=True: the old RMS < 0.003 gate (OpenAI engine, which
    has no VAD and hallucinates on noise)."""
    if len(audio) == 0:
        return True
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if strict:
        return rms < SILENCE_RMS
    return float(np.max(np.abs(audio))) < 0.003 or rms < 0.0005


def normalize(audio: np.ndarray) -> np.ndarray:
    """Boost quiet recordings (laptop mics are often very low) so Whisper hears them better."""
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if 0.003 < peak < 0.5:
        audio = audio * min(0.7 / peak, 12.0)
    return audio.astype(np.float32, copy=False)


_REPEAT = re.compile(r"(.{2,40}?)\1{3,}", re.S)


def _collapse(m: "re.Match") -> str:
    unit = m.group(1)
    # numbers / punctuation runs ("100000000", "......") are legitimate, not a Whisper loop
    return unit if any(c.isalpha() for c in unit) else m.group(0)


def collapse_repeats(text: str) -> str:
    """Whisper sometimes loops ("ทุกคนทุกคนทุกคน..."). Collapse 4+ immediate repeats of a unit containing
    letters to one."""
    return _REPEAT.sub(_collapse, text)


class Engine(ABC):
    @abstractmethod
    def transcribe(self, audio: np.ndarray, language: Optional[str], prompt: Optional[str] = None,
                   long_form: bool = False, should_stop=None) -> str:
        """audio: float32 mono 16 kHz. language: 'th'/'en'/None(auto).
        prompt: context/vocabulary hint. long_form: whole recording (keeps context across windows,
        one line per segment) instead of a short live chunk.
        should_stop: optional callable checked between segments; when it returns True raise
        errors.Cancelled."""


def _cuda_count() -> int:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


_CUDA_ERR = re.compile(r"cuda|cublas|cudnn", re.I)


class LocalWhisper(Engine):
    def __init__(self, model_name: str, device: str = "auto"):
        device = (device or "auto").strip().lower()
        if device not in ("auto", "cpu", "cuda"):
            device = "auto"
        self.model_name = model_name
        self.requested = device
        self.fallback_reason: Optional[str] = None
        self.model = None
        self.device = "cpu"
        self.compute = "int8"
        t0 = time.monotonic()
        want = "cuda" if device == "cuda" or (device == "auto" and _cuda_count() > 0) else "cpu"
        if want == "cuda":
            try:
                gpu.activate(preload=True)
            except Exception:
                log.warning("GPU activation failed", exc_info=True)
            missing = gpu.missing_dlls()
            if missing:
                reason = gpu.explain(f"Library {missing[0]} is not found or cannot be loaded")
                if device == "cuda":
                    raise RuntimeError(reason)
                self.fallback_reason = reason
                log.warning("CUDA skipped: %s", reason)
                want = "cpu"
        if want == "cuda":
            try:
                self._load("cuda", self._cuda_compute())
                self._warmup()
            except Exception as e:
                if device == "cuda":
                    raise RuntimeError(f"CUDA requested but not usable: {gpu.explain(e)}") from e
                self.fallback_reason = gpu.explain(e)
                log.warning("CUDA failed, falling back to CPU: %s", e, exc_info=True)
                self.model = None
                gc.collect()
                self._load("cpu", "int8")
        else:
            self._load("cpu", "int8")
        log.info("engine loaded model=%s device=%s compute=%s in %.1f s", model_name, self.device,
                 self.compute, time.monotonic() - t0)

    @staticmethod
    def _cuda_compute() -> str:
        try:
            import ctranslate2
            types = ctranslate2.get_supported_compute_types("cuda")
            if "float16" not in types and "int8_float32" in types:
                return "int8_float32"
        except Exception:
            pass
        return "float16"

    def _load(self, dev: str, compute: str):
        from faster_whisper import WhisperModel  # lazy: slow import + model download
        self.model = WhisperModel(self.model_name, device=dev, compute_type=compute)
        self.device = dev
        self.compute = compute

    def _warmup(self):
        segs, _ = self.model.transcribe(np.zeros(SAMPLE_RATE, np.float32), language="en", beam_size=1,
                                        vad_filter=False, without_timestamps=True,
                                        condition_on_previous_text=False)
        list(segs)

    def transcribe(self, audio, language, prompt=None, long_form=False, should_stop=None):
        try:
            return self._transcribe(audio, language, prompt, long_form, should_stop)
        except RuntimeError as e:
            if self.device == "cuda" and self.requested == "auto" and _CUDA_ERR.search(str(e)):
                self.fallback_reason = gpu.explain(e)
                log.warning("CUDA failed during transcribe, falling back to CPU: %s", e, exc_info=True)
                self.model = None
                gc.collect()
                self._load("cpu", "int8")
                return self._transcribe(audio, language, prompt, long_form, should_stop)
            raise

    def _transcribe(self, audio, language, prompt=None, long_form=False, should_stop=None):
        if should_stop and should_stop():
            raise Cancelled()
        if is_silent(audio):
            return ""
        audio = normalize(audio)

        def run(without_timestamps: bool):
            segs, info = self.model.transcribe(
                audio, language=language, task="transcribe", beam_size=5,
                initial_prompt=(prompt or None),
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 250},
                # never feed earlier output back in automatically: it makes Thai loop/hallucinate.
                # (live mode passes the transcript tail as initial_prompt instead.)
                condition_on_previous_text=False,
                without_timestamps=without_timestamps,
                repetition_penalty=1.1 if long_form else 1.0,
                temperature=[0.0, 0.2, 0.4], compression_ratio_threshold=2.2)
            out = []
            for x in segs:
                if should_stop and should_stop():
                    raise Cancelled()
                if x.text.strip():
                    out.append(x.text.strip())
            return out, info

        texts, info = run(False)
        # Some fine-tuned models (e.g. the Thai Thonburian conversion) emit nothing when timestamp tokens
        # are on. If VAD found speech but we got no text, retry without timestamps.
        if not texts and getattr(info, "duration_after_vad", 0) > 1.0:
            texts, _ = run(True)
        return collapse_repeats(("\n" if long_form else " ").join(texts)).strip()


class OpenAIWhisper(Engine):
    def __init__(self, api_key: str):
        from openai import OpenAI
        if not api_key:
            raise ValueError("OpenAI API key missing (Settings).")
        self.client = OpenAI(api_key=api_key)

    def transcribe(self, audio, language, prompt=None, long_form=False, should_stop=None):
        if should_stop and should_stop():
            raise Cancelled()
        if is_silent(audio, strict=True):
            return ""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((np.clip(normalize(audio), -1, 1) * 32767).astype(np.int16).tobytes())
        buf.name = "chunk.wav"
        buf.seek(0)
        kwargs = {"language": language} if language else {}
        if prompt:
            kwargs["prompt"] = prompt[-800:]
        r = self.client.audio.transcriptions.create(model="whisper-1", file=buf, **kwargs)
        return r.text.strip()


def make_engine(settings) -> Engine:
    if settings.engine == "openai":
        return OpenAIWhisper(getattr(settings, "effective_openai_key", None) or settings.openai_key)
    return LocalWhisper((settings.whisper_custom or "").strip() or settings.whisper_model,
                        getattr(settings, "device", "auto"))


def _read_fast_wav(path) -> Optional[np.ndarray]:
    """float32 samples if `path` is a 16-bit PCM 16 kHz mono WAV, else None (needs the decoder)."""
    try:
        with wave.open(str(path), "rb") as wf:
            if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                return None
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError):
        return None
    return np.frombuffer(raw, "<i2").astype(np.float32) / 32768


def _av_decode(path) -> np.ndarray:
    """PyAV decode + resample to 16 kHz mono (faster_whisper.decode_audio). Falls back to an equivalent
    local decode when decode_audio is incompatible with the installed PyAV (av>=17 dropped the
    `metadata_errors` argument that faster-whisper 1.2.1 passes)."""
    from faster_whisper import decode_audio
    try:
        return decode_audio(str(path), sampling_rate=SAMPLE_RATE)
    except TypeError as e:
        if "metadata_errors" not in str(e):
            raise
    import av
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(path), mode="r") as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def decode_any(path) -> np.ndarray:
    """Any audio/video file -> float32 mono 16 kHz. Raises ValueError with a readable message."""
    fast = _read_fast_wav(path)
    if fast is not None:
        return fast
    try:
        data = _av_decode(path)
    except Exception as e:
        raise ValueError(f"Could not read this audio file ({type(e).__name__}: {e}). "
                         "It may be corrupt or an unsupported format.") from e
    data = np.asarray(data, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=0)
    return data


def load_wav(path) -> np.ndarray:
    """Load an audio file as float32 mono 16 kHz (WAV fast path, otherwise decoded/resampled by PyAV)."""
    return decode_any(path)


def import_audio(src, dest_wav) -> float:
    """Validate + convert `src` to a 16 kHz mono 16-bit WAV at `dest_wav` (atomically). Returns seconds.
    Raises ValueError on unsupported/corrupt input before anything is written to the destination."""
    data = decode_any(src)
    if len(data) == 0:
        raise ValueError("This audio file contains no audio.")
    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
    dest = os.fspath(dest_wav)
    tmp = os.path.join(os.path.dirname(dest) or ".", f".{os.path.basename(dest)}.{os.getpid()}.tmp")
    try:
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        os.replace(tmp, dest)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return len(pcm) / SAMPLE_RATE
