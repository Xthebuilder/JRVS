"""
AudioPlayer — plays raw PCM audio on Linux via sounddevice.

Two modes:
  play_array(audio, sample_rate)  — play a numpy float32/int16 array
  play_pcm_bytes(data, sample_rate, sample_width)  — play raw bytes (from Piper)

Stop safety: uses a threading.Event so stop() can be called from any thread
(including the asyncio event loop thread) without causing a segfault.
Playback runs inside an sd.OutputStream, writing 50 ms chunks at a time and
checking the stop event between each chunk.  On stop, stream.abort() is called
from the *same* playback thread, which is safe.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False
    logger.error("sounddevice not installed. Run: pip install sounddevice")


class AudioPlayer:
    """Synchronous audio playback via sounddevice (blocks until done or stopped)."""

    def __init__(self, output_device=None) -> None:
        self._device = output_device
        self._stop_event = threading.Event()

    def play_array(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play a numpy audio array (float32 or int16)."""
        if not _SD_AVAILABLE:
            logger.warning("AudioPlayer: sounddevice unavailable, skipping playback.")
            return

        # Normalise to float32 in [-1.0, 1.0]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
            if np.abs(audio).max() > 1.0:
                audio = audio / 32768.0

        # Ensure shape (frames, channels)
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        channels = audio.shape[1]

        # Each write is ~50 ms of audio.  Small chunks mean stop_event is
        # checked frequently, keeping interruption latency ≤ ~100 ms.
        chunk_frames = max(256, sample_rate // 20)

        # Clear any stale stop signal from a previous call.
        self._stop_event.clear()

        stream = None
        try:
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                device=self._device,
                latency="low",
            )
            stream.start()

            offset = 0
            while offset < len(audio):
                if self._stop_event.is_set():
                    # Abort immediately — discard any buffered audio.
                    try:
                        stream.abort()
                    except Exception:
                        pass
                    return

                chunk = audio[offset : offset + chunk_frames]
                try:
                    stream.write(chunk)
                except Exception as exc:
                    logger.error("stream.write error: %s", exc)
                    return
                offset += chunk_frames

            # All data written — drain the internal PortAudio buffer so the
            # last chunk actually plays out before we return.
            try:
                stream.stop()
            except Exception:
                pass

        except Exception as exc:
            logger.error("AudioPlayer.play_array error: %s", exc)
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

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

    def stop(self) -> None:
        """Signal the current playback to stop as soon as the next chunk boundary.

        Thread-safe: can be called from any thread or from asyncio.
        The actual sd.abort() call happens inside the playback thread itself,
        avoiding the cross-thread PortAudio call that caused the segfault.
        """
        self._stop_event.set()

    def play_ack_tone(self, sample_rate: int = 16000, duration_ms: int = 80) -> None:
        """Play a short sine-wave acknowledgment beep."""
        if not _SD_AVAILABLE:
            return
        t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000))
        tone = (0.3 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
        self.play_array(tone, sample_rate)
