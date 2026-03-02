"""
MicrophoneCapture — records audio from a Linux microphone via sounddevice.

sounddevice wraps PortAudio which supports ALSA and PulseAudio on Linux.

Usage:
    mic = MicrophoneCapture(device=None, sample_rate=16000)
    mic.open()
    audio_array = mic.record_utterance(vad_detector, max_duration=30)
    mic.close()
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Optional, Union

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False
    logger.error("sounddevice not installed. Run: pip install sounddevice")


class MicrophoneCapture:
    """Captures audio from the system microphone on Linux."""

    def __init__(
        self,
        device: Optional[Union[int, str]] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_ms: int = 30,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sample_rate * chunk_ms / 1000)

        self._stream: Optional["sd.InputStream"] = None
        self._buffer: collections.deque = collections.deque(maxlen=200)
        self._lock = threading.Lock()
        self._open = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the microphone stream."""
        if not _SD_AVAILABLE:
            raise RuntimeError("sounddevice is not installed.")
        if self._open:
            return

        device_id = self._resolve_device(self.device)
        self._stream = sd.InputStream(
            device=device_id,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_samples,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._open = True
        logger.info(
            "Microphone opened: device=%s, rate=%d Hz, chunk=%d ms",
            device_id, self.sample_rate, self.chunk_ms,
        )

    def close(self) -> None:
        """Close the microphone stream."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
        self._open = False
        logger.info("Microphone closed.")

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_utterance(
        self,
        vad,
        max_duration: float = 30.0,
        pre_buffer_chunks: int = 5,
    ) -> Optional[np.ndarray]:
        """
        Record a single voice utterance, gated by VAD.

        Blocks until speech is detected, then records until silence,
        up to max_duration seconds.

        Args:
            vad:              VoiceActivityDetector instance
            max_duration:     Max recording length in seconds
            pre_buffer_chunks: Chunks to include before speech start (context)

        Returns:
            int16 numpy array at self.sample_rate, or None on timeout/error.
        """
        if not self._open:
            raise RuntimeError("Call open() before record_utterance().")

        pre_roll = collections.deque(maxlen=pre_buffer_chunks)
        speech_chunks = []
        speech_started = False
        deadline = time.monotonic() + max_duration + 10  # extra for pre-speech wait

        while time.monotonic() < deadline:
            chunk = self._read_chunk()
            if chunk is None:
                time.sleep(0.005)
                continue

            is_speech = vad.is_speech(chunk, self.sample_rate)

            if not speech_started:
                pre_roll.append(chunk)
                if is_speech:
                    speech_started = True
                    speech_chunks.extend(list(pre_roll))
                    logger.debug("Speech started.")
            else:
                speech_chunks.append(chunk)
                elapsed = len(speech_chunks) * self.chunk_ms / 1000
                if elapsed >= max_duration:
                    logger.debug("Max duration reached.")
                    break
                if vad.is_silence_end(is_speech):
                    logger.debug("Silence end detected — utterance complete.")
                    break

        if not speech_chunks:
            return None
        return np.concatenate(speech_chunks, axis=0)

    def read_raw_chunk(self) -> Optional[np.ndarray]:
        """Return a single raw audio chunk (int16) for wake word processing."""
        return self._read_chunk()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            logger.debug("sounddevice status: %s", status)
        with self._lock:
            self._buffer.append(indata.copy().flatten())

    def _read_chunk(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._buffer:
                return self._buffer.popleft()
        return None

    @staticmethod
    def _resolve_device(device: Optional[Union[int, str]]) -> Optional[Union[int, str]]:
        """Resolve device name substring to device index if necessary."""
        if device is None or isinstance(device, int):
            return device
        if not _SD_AVAILABLE:
            return None
        import sounddevice as sd_  # local import to handle unavailable case
        devices = sd_.query_devices()
        for i, dev in enumerate(devices):
            if device.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
                logger.info("Resolved microphone '%s' → device index %d", device, i)
                return i
        logger.warning("Microphone device '%s' not found; using system default.", device)
        return None

    @staticmethod
    def list_devices() -> None:
        """Print available audio input devices to stdout."""
        if not _SD_AVAILABLE:
            print("sounddevice not installed.")
            return
        import sounddevice as sd_
        devices = sd_.query_devices()
        print("\nAvailable audio input devices:")
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                print(f"  [{i}] {dev['name']}")
        print()
