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
                await asyncio.get_event_loop().run_in_executor(
                    None, self._load_model
                )
                self._ready = True
                logger.info("Whisper model '%s' loaded.", self._model_size)
            except Exception as exc:
                logger.error("Whisper model load failed: %s", exc)

    def _load_model(self) -> None:
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )

    async def transcribe(self, audio: np.ndarray) -> Transcript:
        if not self._ready or self._model is None:
            return Transcript(
                text="", language="en", duration_seconds=0.0, timestamp=datetime.now()
            )

        # faster-whisper expects float32 in [-1, 1]
        audio_f32 = audio.astype(np.float32) / 32768.0

        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
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
