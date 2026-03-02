"""
TTSBackend — abstract base + factory for text-to-speech backends.

Usage:
    tts = create_tts_backend(audio_config)
    await tts.initialize()
    await tts.speak("Hello from JRVS.")
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TTSBackend(ABC):
    """Abstract text-to-speech backend."""

    @abstractmethod
    async def initialize(self) -> None:
        """Load model / verify binary.  Called once before first speak()."""

    @abstractmethod
    async def speak(self, text: str) -> None:
        """Synthesize text and play audio through the system speaker."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True once initialize() completed successfully."""


def create_tts_backend(config) -> TTSBackend:
    """Factory: create the TTS backend named in config.tts_backend."""
    backend_name = config.tts_backend.lower()

    if backend_name == "piper":
        from extensions.audio.output.piper_backend import PiperBackend
        logger.info(
            "TTS backend: Piper (%s)", config.piper_model
        )
        return PiperBackend(
            model_name=config.piper_model,
            models_dir=config.piper_models_dir,
            binary=config.piper_binary,
            sample_rate=config.piper_sample_rate,
            speed=config.tts_speed,
        )

    if backend_name == "kokoro":
        from extensions.audio.output.kokoro_backend import KokoroBackend
        logger.info(
            "TTS backend: Kokoro (%s)", config.kokoro_voice
        )
        return KokoroBackend(
            model_path=config.kokoro_model_path,
            voice=config.kokoro_voice,
            lang_code=config.kokoro_lang_code,
            speed=config.tts_speed,
        )

    raise ValueError(
        f"Unknown TTS backend: '{backend_name}'. Choose 'piper' or 'kokoro'."
    )
