"""
AudioPlayer — plays raw PCM audio on Linux via sounddevice.

Two modes:
  play_array(audio, sample_rate)  — play a numpy float32/int16 array
  play_pcm_bytes(data, sample_rate, sample_width)  — play raw bytes (from Piper)
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False
    logger.error("sounddevice not installed. Run: pip install sounddevice")


class AudioPlayer:
    """Synchronous audio playback via sounddevice (blocks until done)."""

    def __init__(self, output_device=None) -> None:
        self._device = output_device

    def play_array(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play a numpy audio array (float32 or int16)."""
        if not _SD_AVAILABLE:
            logger.warning("AudioPlayer: sounddevice unavailable, skipping playback.")
            return
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
            if audio.max() > 1.0:
                audio = audio / 32768.0
        try:
            sd.play(audio, samplerate=sample_rate, device=self._device)
            sd.wait()
        except Exception as exc:
            logger.error("AudioPlayer.play_array error: %s", exc)

    def play_pcm_bytes(
        self,
        data: bytes,
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2,  # bytes per sample; 2 = int16
    ) -> None:
        """Play raw PCM bytes (e.g., from Piper's --output_raw mode)."""
        if not data:
            return
        dtype = np.int16 if sample_width == 2 else np.float32
        audio = np.frombuffer(data, dtype=dtype)
        if channels > 1:
            audio = audio.reshape(-1, channels)
        self.play_array(audio, sample_rate)

    def play_ack_tone(self, sample_rate: int = 16000, duration_ms: int = 80) -> None:
        """Play a short sine-wave acknowledgment beep."""
        if not _SD_AVAILABLE:
            return
        t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000))
        tone = (0.3 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
        self.play_array(tone, sample_rate)
