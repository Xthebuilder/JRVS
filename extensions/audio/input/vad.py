"""
VoiceActivityDetector — segments continuous audio into speech utterances.

Uses webrtcvad (Google's WebRTC VAD port) for fast, accurate speech detection
without any neural network or torch dependency.

VAD aggressiveness 0–3:
  0 = most permissive (keeps more audio, may include non-speech)
  3 = most aggressive (strips non-speech strictly)

Frame requirements (webrtcvad):
  - Sample rate: 8000, 16000, 32000, or 48000 Hz
  - Frame duration: exactly 10ms, 20ms, or 30ms
  - Encoding: 16-bit PCM, mono
"""
from __future__ import annotations

import collections
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import webrtcvad
    _WEBRTCVAD_AVAILABLE = True
except ImportError:
    _WEBRTCVAD_AVAILABLE = False
    logger.error("webrtcvad not installed. Run: pip install webrtcvad")


class VoiceActivityDetector:
    """
    Stateful VAD that tracks silence duration to detect utterance boundaries.

    Call is_speech(chunk) for each audio chunk.
    Call is_silence_end(speech_result) to know when the utterance is done.
    """

    def __init__(
        self,
        aggressiveness: int = 2,
        sample_rate: int = 16000,
        chunk_ms: int = 30,
        silence_timeout: float = 1.5,
        consecutive_voiced: int = 3,
    ) -> None:
        """
        Args:
            aggressiveness:      0–3 VAD sensitivity
            sample_rate:         Hz (must be 8000/16000/32000/48000)
            chunk_ms:            Frame size (must be 10/20/30 ms)
            silence_timeout:     Seconds of silence to end utterance
            consecutive_voiced:  N consecutive voiced frames to confirm speech start
        """
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.silence_timeout = silence_timeout
        self.consecutive_voiced = consecutive_voiced

        self._vad = None
        if _WEBRTCVAD_AVAILABLE:
            self._vad = webrtcvad.Vad(aggressiveness)

        # Silence tracking
        self._silence_frames = 0
        self._silence_frames_threshold = int(
            silence_timeout * 1000 / chunk_ms
        )

        # Voice confirmation ring buffer
        self._voiced_history: collections.deque = collections.deque(
            maxlen=consecutive_voiced
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_speech(self, chunk: np.ndarray, sample_rate: Optional[int] = None) -> bool:
        """
        Classify a single audio chunk as speech or non-speech.

        Args:
            chunk:       int16 numpy array of length chunk_ms * sample_rate / 1000
            sample_rate: override if different from constructor value

        Returns:
            True if webrtcvad classifies this frame as speech.
        """
        if self._vad is None:
            return True  # Degrade gracefully: treat all audio as speech

        sr = sample_rate or self.sample_rate
        # webrtcvad wants raw bytes of int16 PCM
        pcm_bytes = chunk.astype(np.int16).tobytes()
        try:
            result = self._vad.is_speech(pcm_bytes, sr)
        except Exception as exc:
            logger.debug("VAD error: %s", exc)
            result = False

        if result:
            self._silence_frames = 0
        else:
            self._silence_frames += 1

        self._voiced_history.append(result)
        return result

    def is_silence_end(self, latest_is_speech: bool) -> bool:
        """
        Return True when sustained silence indicates utterance is complete.

        Should be called with the same result returned by is_speech().
        """
        return (
            not latest_is_speech
            and self._silence_frames >= self._silence_frames_threshold
        )

    def is_speech_confirmed(self) -> bool:
        """Return True when N consecutive voiced frames have been seen."""
        return (
            len(self._voiced_history) == self.consecutive_voiced
            and all(self._voiced_history)
        )

    def reset(self) -> None:
        """Reset silence counter and history (call between utterances)."""
        self._silence_frames = 0
        self._voiced_history.clear()
