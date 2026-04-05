"""
WhisperBackend — speech-to-text using faster-whisper.

faster-whisper is a CTranslate2-optimized reimplementation of OpenAI Whisper.
It's 4× faster than the original on CPU and supports int8 quantization.

https://github.com/SYSTRAN/faster-whisper

Model sizes: tiny (~39M), base (~74M), small (~244M), medium (~769M), large-v3 (~1.5B)
Recommendation for conversational use on CPU: "base" or "small"
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np

from extensions.audio.input.stt_engine import STTBackend
from extensions.audio.models.schemas import Transcript

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
    _FW_AVAILABLE = True
except ImportError:
    _FW_AVAILABLE = False
    logger.error("faster-whisper not installed. Run: pip install faster-whisper")


class WhisperBackend(STTBackend):
    """faster-whisper based STT backend."""

    def __init__(
        self,
        model_size: str = "base",
        language: Optional[str] = "en",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self._model_size = model_size
        self._language = language or None  # None → auto-detect
        self._device = device
        self._compute_type = compute_type
        self._model: Optional["WhisperModel"] = None
        self._ready = False
        self._load_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Load the Whisper model in a thread pool."""
        async with self._load_lock:
            if self._ready:
                return
            if not _FW_AVAILABLE:
                logger.error("faster-whisper unavailable; STT will not work.")
                return
            logger.info(
                "Loading Whisper model '%s' on %s (%s)…",
                self._model_size, self._device, self._compute_type,
            )
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._load_model
                )
                self._ready = True
                logger.info("Whisper model '%s' loaded.", self._model_size)
            except Exception as exc:
                logger.error("Whisper model load failed: %s", exc)

    def _load_model(self) -> None:
        # CTranslate2 needs libcublas.so.12 etc., which on this system live inside
        # Ollama's private lib dir rather than the system ld cache.  Pre-load them
        # via ctypes so the dynamic linker finds them before CTranslate2 opens CUDA.
        if self._device == "cuda":
            self._preload_cuda_libs()

        try:
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        except Exception as exc:
            if self._device == "cuda":
                logger.warning(
                    "Whisper CUDA load failed (%s); falling back to CPU/int8.", exc
                )
                self._device = "cpu"
                self._compute_type = "int8"
                self._model = WhisperModel(
                    self._model_size,
                    device="cpu",
                    compute_type="int8",
                )
            else:
                raise

    @staticmethod
    def _preload_cuda_libs() -> None:
        """Pre-load CUDA shared libs from Ollama's bundled copy if not on ld path."""
        import ctypes
        import glob

        # Candidate directories — Ollama bundles CUDA 12 here on Linux
        search_dirs = [
            "/usr/local/lib/ollama/cuda_v12",
            "/usr/local/lib/ollama/cuda_v13",
            "/usr/lib/x86_64-linux-gnu",
            "/usr/local/cuda/lib64",
        ]
        needed = ["libcublas.so.12", "libcublasLt.so.12",
                  "libcudart.so.12", "libcurand.so.10"]
        for lib_name in needed:
            for d in search_dirs:
                candidates = glob.glob(f"{d}/{lib_name}*")
                if candidates:
                    try:
                        ctypes.CDLL(candidates[0])
                        logger.debug("Pre-loaded %s from %s", lib_name, d)
                    except OSError:
                        pass
                    break

    async def transcribe(self, audio: np.ndarray) -> Transcript:
        if not self._ready or self._model is None:
            return Transcript(
                text="", language="en", duration_seconds=0.0, timestamp=datetime.now()
            )

        # faster-whisper expects float32 in [-1, 1]
        audio_f32 = audio.astype(np.float32) / 32768.0

        t0 = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            segments, info = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(
                    audio_f32,
                    language=self._language,
                    beam_size=5,
                    vad_filter=True,          # built-in VAD to skip non-speech
                    vad_parameters=dict(min_silence_duration_ms=500),
                ),
            )
            text = " ".join(seg.text for seg in segments).strip()
            duration = time.perf_counter() - t0
            return Transcript(
                text=text,
                language=info.language,
                duration_seconds=duration,
                timestamp=datetime.now(),
            )
        except Exception as exc:
            logger.error("Whisper transcription error: %s", exc)
            return Transcript(
                text="", language="en", duration_seconds=0.0, timestamp=datetime.now()
            )

    def is_ready(self) -> bool:
        return self._ready
