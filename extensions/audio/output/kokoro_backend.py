"""
KokoroBackend — TTS via the Kokoro local neural TTS model.

Kokoro is a compact (82M parameter) high-quality TTS model.
GitHub: https://github.com/hexgrad/kokoro

Install:
  pip install kokoro soundfile

Model is downloaded automatically from HuggingFace on first use.

Available voices (en): af_sky, af_bella, am_adam, am_michael, etc.
See https://huggingface.co/hexgrad/Kokoro-82M for full voice list.

Usage in config.yaml:
  tts:
    backend: "kokoro"
    kokoro:
      voice: "af_sky"
      lang_code: "a"    # "a" = American English
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

from extensions.audio.output.audio_player import AudioPlayer
from extensions.audio.output.tts_engine import TTSBackend

logger = logging.getLogger(__name__)


class KokoroBackend(TTSBackend):
    """TTS via local Kokoro-82M model."""

    SAMPLE_RATE = 24000  # Kokoro outputs 24kHz

    def __init__(
        self,
        model_path: Optional[str] = None,
        voice: str = "af_sky",
        lang_code: str = "a",
        speed: float = 1.0,
    ) -> None:
        self._model_path = model_path  # None → auto HuggingFace download
        self._voice = voice
        self._lang_code = lang_code
        self._speed = speed
        self._pipeline = None
        self._ready = False
        self._load_lock = asyncio.Lock()
        self._player = AudioPlayer()
        self._interrupted = False

    async def initialize(self) -> None:
        """Load Kokoro pipeline in thread pool."""
        async with self._load_lock:
            if self._ready:
                return
            logger.info("Loading Kokoro TTS model (voice=%s)…", self._voice)
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._load_model
                )
                self._ready = True
                logger.info("Kokoro TTS ready.")
            except ImportError:
                logger.error(
                    "Kokoro not installed. Run: pip install kokoro soundfile"
                )
            except Exception as exc:
                logger.error("Kokoro load failed: %s", exc)

    def _load_model(self) -> None:
        from kokoro import KPipeline  # type: ignore[import]
        self._pipeline = KPipeline(
            lang_code=self._lang_code,
            model=self._model_path,  # None → default HuggingFace download
        )

    def stop_speaking(self) -> None:
        """Interrupt ongoing playback (barge-in support)."""
        self._interrupted = True
        self._player.stop()

    async def speak(self, text: str) -> None:
        if not self._ready or self._pipeline is None:
            logger.warning("KokoroBackend not ready; cannot speak.")
            return
        if not text.strip():
            return

        self._interrupted = False  # reset on each new speak() call

        loop = asyncio.get_running_loop()
        audio_chunks = await loop.run_in_executor(None, self._synthesize, text)
        for chunk in audio_chunks:
            if self._interrupted:
                break
            await loop.run_in_executor(
                None,
                lambda c=chunk: self._player.play_array(c, self.SAMPLE_RATE),
            )

    def _synthesize(self, text: str):
        """Run Kokoro synthesis; returns list of audio numpy arrays."""
        chunks = []
        try:
            generator = self._pipeline(
                text,
                voice=self._voice,
                speed=self._speed,
                split_pattern=r"\n+",  # split on newlines for streaming feel
            )
            for _, _, audio in generator:
                if audio is not None and len(audio) > 0:
                    chunks.append(np.array(audio, dtype=np.float32))
        except Exception as exc:
            logger.error("Kokoro synthesis error: %s", exc)
        return chunks

    def is_ready(self) -> bool:
        return self._ready
