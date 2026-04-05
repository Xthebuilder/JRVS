"""
STTBackend — abstract base + factory for speech-to-text backends.

Usage:
    stt = create_stt_backend(audio_config)
    await stt.initialize()
    transcript = await stt.transcribe(audio_array_int16)
    print(transcript.text)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

from extensions.audio.models.schemas import Transcript

logger = logging.getLogger(__name__)


class STTBackend(ABC):
    """Abstract speech-to-text backend."""

    @abstractmethod
    async def initialize(self) -> None:
        """Load model.  Called once before first transcribe()."""

    @abstractmethod
    async def transcribe(self, audio: np.ndarray) -> Transcript:
        """
        Transcribe a mono 16kHz int16 numpy audio array.

        Args:
            audio:  1-D int16 numpy array (mono, 16000 Hz)

        Returns:
            Transcript dataclass with text, language, duration.
        """

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True once initialize() has completed successfully."""


def create_stt_backend(config) -> STTBackend:
    """Factory: create the STT backend named in config.stt_backend."""
    backend_name = config.stt_backend.lower()

    if backend_name == "whisper":
        from extensions.audio.input.whisper_backend import WhisperBackend
        logger.info(
            "STT backend: faster-whisper (%s, device=%s, compute=%s)",
            config.whisper_model, config.whisper_device, config.whisper_compute_type,
        )
        return WhisperBackend(
            model_size=config.whisper_model,
            language=config.whisper_language,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )

    raise ValueError(
        f"Unknown STT backend: '{backend_name}'. Only 'whisper' is supported."
    )
