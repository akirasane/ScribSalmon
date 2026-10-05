"""Pluggable speech-to-text engines."""
import gc
import io
import re
import wave
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000
SILENCE_RMS = 0.003


def is_silent(audio: np.ndarray) -> bool:
    return len(audio) == 0 or float(np.sqrt(np.mean(audio ** 2))) < SILENCE_RMS


def normalize(audio: np.ndarray) -> np.ndarray:
    """Boost quiet recordings (laptop mics are often very low) so Whisper hears them better."""
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if 0.003 < peak < 0.5:
        audio = audio * min(0.7 / peak, 12.0)
    return audio.astype(np.float32, copy=False)


_REPEAT = re.compile(r"(.{2,40}?)\1{3,}", re.S)


def collapse_repeats(text: str) -> str:
    """Whisper sometimes loops ("ทุกคนทุกคนทุกคน..."). Collapse 4+ immediate repeats to one."""
    return _REPEAT.sub(r"\1", text)


class Engine(ABC):
    @abstractmethod
    def transcribe(self, audio: np.ndarray, language: Optional[str], prompt: Optional[str] = None,
                   long_form: bool = False) -> str:
        """audio: float32 mono 16 kHz. language: 'th'/'en'/None(auto).
        prompt: context/vocabulary hint. long_form: whole recording (keeps context across windows,
        one line per segment) instead of a short live chunk."""


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
        want = "cuda" if device == "cuda" or (device == "auto" and _cuda_count() > 0) else "cpu"
        if want == "cuda":
            try:
                self._load("cuda", "float16")
                self._warmup()
            except Exception as e:
                if device == "cuda":
                    raise RuntimeError(f"CUDA requested but not usable: {e}") from e
                self.fallback_reason = str(e)
                self.model = None
                gc.collect()
                self._load("cpu", "int8")
        else:
            self._load("cpu", "int8")

    def _load(self, dev: str, compute: str):
        from faster_whisper import WhisperModel  # lazy: slow import + model download
        self.model = WhisperModel(self.model_name, device=dev, compute_type=compute)
        self.device = dev

    def _warmup(self):
        segs, _ = self.model.transcribe(np.zeros(SAMPLE_RATE, np.float32), language="en", beam_size=1,
                                        vad_filter=False, without_timestamps=True,
                                        condition_on_previous_text=False)
        list(segs)

    def transcribe(self, audio, language, prompt=None, long_form=False):
        try:
            return self._transcribe(audio, language, prompt, long_form)
        except RuntimeError as e:
            if self.device == "cuda" and self.requested == "auto" and _CUDA_ERR.search(str(e)):
                self.fallback_reason = str(e)
                self.model = None
                gc.collect()
                self._load("cpu", "int8")
                return self._transcribe(audio, language, prompt, long_form)
            raise

    def _transcribe(self, audio, language, prompt=None, long_form=False):
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
            return [x.text.strip() for x in segs if x.text.strip()], info

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

    def transcribe(self, audio, language, prompt=None, long_form=False):
        if is_silent(audio):
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


def load_wav(path) -> np.ndarray:
    """Load any wav as float32 mono 16 kHz (simple resample)."""
    with wave.open(str(path), "rb") as wf:
        sr, ch, sw = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        if sw != 2:
            raise ValueError("Only 16-bit PCM WAV supported for import.")
        data = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
    return data
