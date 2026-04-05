"""
AudioModule — public interface for the JRVS audio extension.

Usage from JRVS or any orchestration code:

    from extensions.audio import AudioModule

    audio = AudioModule()
    await audio.initialize()

    # One-shot listen + transcribe
    text = await audio.listen()

    # One-shot TTS
    await audio.speak("Hello, I'm JRVS.")

    # Full conversation loop (blocks until stop() is called)
    async def jrvs_respond(user_text: str) -> str:
        # Call JRVS API or CLI here
        return f"You said: {user_text}"

    await audio.start_loop(jrvs_respond)

    await audio.stop()

Standalone smoke tests:
    python -m extensions.audio.audio_module --say "Hello from JRVS"
    python -m extensions.audio.audio_module --listen-once
    python -m extensions.audio.audio_module --run  (full wake-word loop)
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import signal
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

import re

import numpy as np

from extensions.base import BaseExtension
from extensions.audio.config import audio_config
from extensions.audio.input.microphone import MicrophoneCapture
from extensions.audio.input.vad import VoiceActivityDetector
from extensions.audio.input.stt_engine import STTBackend, create_stt_backend
from extensions.audio.output.tts_engine import TTSBackend, create_tts_backend
from extensions.audio.output.audio_player import AudioPlayer
from extensions.audio.models.schemas import Transcript, SpeechEvent
from extensions.audio.intent_parser import intent_parser
from extensions.audio.command_executor import CommandExecutor
from extensions.audio.command_mode import CommandMode

logger = logging.getLogger(__name__)

_THINKING_PHRASES = itertools.cycle([
    "Let me think.",
    "One moment.",
    "Sure.",
    "Hmm, let me check.",
    "Got it.",
    "Looking into that.",
])


def _strip_markdown(text: str) -> str:
    """Remove markdown symbols that TTS would read aloud literally."""
    # Bold / italic: ***text***, **text**, *text*, __text__, _text_
    text = re.sub(r'\*{1,3}|_{1,3}', '', text)
    # Headers: ## Title → Title
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Inline code and code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Links: [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Bullet points: leading - or * or • → nothing (sentence still reads fine)
    text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
    # Numbered lists: "1. " → nothing
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class AudioModule(BaseExtension):
    """
    JRVS audio extension.

    Provides natural voice I/O: wake word detection → Whisper STT → JRVS →
    Piper/Kokoro TTS.  Everything runs locally; nothing is sent to external APIs.
    """

    def __init__(self, config=None, vision_module=None) -> None:
        self._cfg = config or audio_config
        self._vision = vision_module   # optional VisionModule for vision commands
        self._mic = MicrophoneCapture(
            device=self._cfg.input_device,
            sample_rate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            chunk_ms=self._cfg.chunk_ms,
        )
        self._vad = VoiceActivityDetector(
            aggressiveness=self._cfg.vad_aggressiveness,
            sample_rate=self._cfg.sample_rate,
            chunk_ms=self._cfg.chunk_ms,
            silence_timeout=self._cfg.silence_timeout,
        )
        self._stt: Optional[STTBackend] = None
        self._tts: Optional[TTSBackend] = None
        self._player = AudioPlayer()
        self._wake_detector: Optional["_WakeWordDetector"] = None
        self._cmd_mode: Optional[CommandMode] = None

        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._is_listening = False
        self._conversation_count = 0
        self._start_time: Optional[datetime] = None
        self._last_speech_event: Optional[SpeechEvent] = None

    # ------------------------------------------------------------------
    # BaseExtension lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Load all sub-components. Must be called before any other method."""
        logger.info(
            "Initializing AudioModule (stt=%s, tts=%s, wake_word=%s)",
            self._cfg.whisper_model,
            self._cfg.tts_backend,
            self._cfg.wake_word or "none (always-on)",
        )

        # Open microphone
        self._mic.open()

        # Load STT
        self._stt = create_stt_backend(self._cfg)
        await self._stt.initialize()

        # Load TTS
        self._tts = create_tts_backend(self._cfg)
        await self._tts.initialize()

        # Load wake word detector if configured
        if self._cfg.wake_word:
            self._wake_detector = _WakeWordDetector(
                phrase=self._cfg.wake_word,
                threshold=self._cfg.wake_word_threshold,
                sample_rate=self._cfg.sample_rate,
                chunk_ms=self._cfg.chunk_ms,
            )
            await self._wake_detector.initialize()

        logger.info("AudioModule initialized.")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._mic.close()
        logger.info(
            "AudioModule stopped. Conversations: %d", self._conversation_count
        )

    def is_running(self) -> bool:
        return self._running and (
            self._loop_task is not None and not self._loop_task.done()
        )

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.is_running(),
            "mic_device": str(self._cfg.input_device or "system default"),
            "stt_model": self._cfg.whisper_model,
            "tts_engine": self._cfg.tts_backend,
            "wake_word": self._cfg.wake_word,
            "is_listening": self._is_listening,
            "conversation_count": self._conversation_count,
            "uptime_seconds": (
                (datetime.now() - self._start_time).total_seconds()
                if self._start_time else 0
            ),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def listen(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Record one utterance and return the transcribed text.

        Blocks until speech is detected and the utterance ends.

        Args:
            timeout: Max seconds to wait for speech to begin.
                     None = wait indefinitely.

        Returns:
            Transcribed text string, or None if nothing was captured.
        """
        if self._stt is None:
            raise RuntimeError("Call initialize() first.")

        self._is_listening = True
        try:
            loop = asyncio.get_running_loop()
            audio = await loop.run_in_executor(
                None,
                lambda: self._mic.record_utterance(
                    self._vad, max_duration=self._cfg.max_duration
                ),
            )
            self._vad.reset()

            if audio is None or len(audio) == 0:
                return None

            # Resample to 16000 Hz if captured at a different rate (Whisper requires 16 kHz)
            capture_rate = self._mic.sample_rate
            if capture_rate != 16000:
                from scipy.signal import resample_poly
                import math
                g = math.gcd(capture_rate, 16000)
                audio = resample_poly(audio, 16000 // g, capture_rate // g).astype(np.int16)

            transcript = await self._stt.transcribe(audio)
            text = transcript.text.strip()
            logger.info("Transcribed: %s", text[:100] if text else "(empty)")
            return text if text else None
        finally:
            self._is_listening = False

    async def speak(self, text: str) -> None:
        """
        Synthesize text with TTS and play through system speakers.
        Runs a barge-in monitor concurrently; if the user starts speaking,
        TTS is interrupted so they can be heard immediately.

        Args:
            text: Text for JRVS to say aloud.
        """
        if self._tts is None:
            raise RuntimeError("Call initialize() first.")
        if not text.strip():
            return

        full_text = (self._cfg.response_prefix + text) if self._cfg.response_prefix else text
        full_text = _strip_markdown(full_text)
        logger.info("Speaking: %s", full_text[:80])

        speak_task = asyncio.create_task(self._tts.speak(full_text))
        barge_task = asyncio.create_task(self._barge_in_monitor())

        done, pending = await asyncio.wait(
            {speak_task, barge_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel whichever task didn't finish first
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        # If barge-in fired before speaking finished, interrupt TTS
        if barge_task in done and speak_task not in done:
            self._tts.stop_speaking()
            await asyncio.sleep(0.05)  # short gap so sounddevice settles

    async def _barge_in_monitor(self) -> None:
        """
        Read audio from the already-open mic stream and return as soon as
        VAD detects sustained speech (barge-in).  Runs concurrently with speak().

        Acoustic-echo mitigation:
          1. Flush the mic buffer before we start (clear any stale pre-TTS audio).
          2. Wait 600 ms — gives TTS audio time to leave the speakers *and*
             be picked up by the mic *before* we start classifying.
          3. Flush again — discard the speaker-bleed that accumulated during
             the dead period.
          4. Require 6 consecutive voiced frames (≈ 180 ms) to trigger —
             short bursts of echo won't fire the interrupt.
        """
        try:
            import webrtcvad as wv
            vad = wv.Vad(self._cfg.vad_aggressiveness)
        except ImportError:
            # webrtcvad unavailable — barge-in is silently disabled
            await asyncio.Event().wait()
            return

        chunk_samples = int(self._cfg.sample_rate * self._cfg.chunk_ms / 1000)
        # 6 consecutive voiced frames × 30 ms = 180 ms of continuous speech
        # required before we treat it as a real barge-in (not speaker echo).
        consecutive_voiced = 0
        required = 6

        try:
            # ── Step 1: discard audio already in the buffer ───────────────────
            self._mic.flush()

            # ── Step 2: deaf period — don't monitor while TTS is ramping up ──
            await asyncio.sleep(0.6)

            # ── Step 3: flush speaker bleed accumulated during the dead zone ──
            self._mic.flush()

            # ── Step 4: monitor for genuine user speech ───────────────────────
            while True:
                chunk = self._mic.read_raw_chunk()
                if chunk is not None and len(chunk) >= chunk_samples:
                    pcm_bytes = chunk[:chunk_samples].astype(np.int16).tobytes()
                    try:
                        if vad.is_speech(pcm_bytes, self._cfg.sample_rate):
                            consecutive_voiced += 1
                            if consecutive_voiced >= required:
                                logger.info("Barge-in detected — interrupting TTS.")
                                return
                        else:
                            consecutive_voiced = 0
                    except Exception:
                        consecutive_voiced = 0
                else:
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Barge-in monitor error: %s", exc)
            await asyncio.Event().wait()  # don't interrupt if monitor fails

    async def start_loop(
        self,
        on_input: Callable[[str], Awaitable[str]],
    ) -> None:
        """
        Start the full conversational loop (non-blocking; runs as background task).

        Flow:
          1. Wait for wake word ("hey jarvis") — or skip if wake_word is None
          2. Play acknowledgment tone
          3. Record utterance via VAD
          4. Transcribe with Whisper
          5. Call on_input(text) → get response string from JRVS
          6. Speak response with TTS
          7. Repeat

        Args:
            on_input: Async callable that takes user text and returns JRVS response.
                      Typically wraps the JRVS API /api/chat endpoint.
        """
        if self._running:
            logger.warning("AudioModule loop already running.")
            return
        if self._stt is None or self._tts is None:
            raise RuntimeError("Call initialize() before start_loop().")

        # Build command mode machinery
        executor = CommandExecutor(
            on_input=on_input,
            vision_module=self._vision,
        )
        self._cmd_mode = CommandMode(
            executor=executor,
            listen_fn=self.listen,
            speak_fn=self.speak,
            multi_command=self._cfg.cmd_multi_command,
            command_timeout=self._cfg.cmd_timeout,
        )

        self._running = True
        self._start_time = datetime.now()
        self._loop_task = asyncio.create_task(
            self._conversation_loop(on_input), name="audio-conversation-loop"
        )
        logger.info("AudioModule conversation loop started.")

    # ------------------------------------------------------------------
    # Internal conversation loop
    # ------------------------------------------------------------------

    async def _conversation_loop(
        self, on_input: Callable[[str], Awaitable[str]]
    ) -> None:
        logger.info(
            "Listening%s…",
            f" for '{self._cfg.wake_word}'" if self._cfg.wake_word else "",
        )
        while self._running:
            try:
                # ── Step 1: wait for wake word ────────────────────────────────
                if self._wake_detector and self._cfg.wake_word:
                    triggered = await self._wait_for_wake_word()
                    if not triggered:
                        continue

                # ── Step 2: acknowledgment tone ───────────────────────────────
                if self._cfg.ack_tone:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, lambda: self._player.play_ack_tone(self._cfg.sample_rate)
                    )

                # ── Step 3 & 4: record + transcribe ──────────────────────────
                t_listen_start = time.perf_counter()
                user_text = await self.listen()
                if not user_text:
                    logger.debug("Empty utterance; resuming wake-word detection.")
                    continue

                logger.info("User: %s", user_text)

                # ── Step 5a: check for command mode trigger ───────────────────
                if self._cmd_mode and intent_parser.is_command_mode_trigger(user_text):
                    logger.info("Command mode triggered.")
                    await self._cmd_mode.run()
                    continue

                # ── Step 5b: get JRVS response (with thinking audio) ─────────
                t_stt = time.perf_counter()

                # Play a filler phrase after 1.2 s if JRVS hasn't responded yet
                async def _thinking_audio() -> None:
                    await asyncio.sleep(1.2)
                    await self.speak(next(_THINKING_PHRASES))

                thinking_task = asyncio.create_task(_thinking_audio())
                try:
                    response = await on_input(user_text)
                except Exception as exc:
                    logger.error("on_input() error: %s", exc)
                    response = "I encountered an error processing that."
                finally:
                    if not thinking_task.done():
                        thinking_task.cancel()
                        self._tts.stop_speaking()  # stop if phrase was mid-play
                        try:
                            await thinking_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        await asyncio.sleep(0.05)

                t_response = time.perf_counter()

                if not response:
                    response = "I'm not sure how to respond to that."

                logger.info("JRVS: %s", response[:100])

                # ── Step 6: speak response ────────────────────────────────────
                await self.speak(response)
                t_tts = time.perf_counter()

                # Track conversation history
                self._conversation_count += 1
                self._last_speech_event = SpeechEvent(
                    user_text=user_text,
                    response_text=response,
                    stt_duration=t_stt - t_listen_start,
                    tts_duration=t_tts - t_response,
                    wakeword_used=self._cfg.wake_word,
                )

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Conversation loop error: %s", exc, exc_info=True)
                await asyncio.sleep(1.0)

    async def _wait_for_wake_word(self) -> bool:
        """
        Block until the wake word is detected.

        Returns True when triggered, False on cancellation/error.
        """
        try:
            loop = asyncio.get_running_loop()
            detected = await loop.run_in_executor(
                None, self._wake_detector.listen_for_trigger
            )
            return detected
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Wake word detection error: %s", exc)
            await asyncio.sleep(0.5)
            return False


# ---------------------------------------------------------------------------
# Wake word detector (openwakeword)
# ---------------------------------------------------------------------------

class _WakeWordDetector:
    """
    Thin wrapper around openwakeword for local wake phrase detection.

    openwakeword ships pre-trained models for common phrases.
    Custom phrases require recording samples and fine-tuning (see their docs).

    Install: pip install openwakeword
    """

    def __init__(
        self,
        phrase: str = "hey jarvis",
        threshold: float = 0.5,
        sample_rate: int = 16000,
        chunk_ms: int = 80,
    ) -> None:
        self._phrase = phrase
        self._threshold = threshold
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._chunk_samples = int(sample_rate * chunk_ms / 1000)
        self._model = None
        self._model_name: Optional[str] = None
        self._ready = False

    async def initialize(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._load_model)
        except ImportError:
            logger.error(
                "openwakeword not installed. Run: pip install openwakeword\n"
                "Wake word detection disabled; module will always listen."
            )
        except Exception as exc:
            logger.error("Wake word model load failed: %s", exc)

    def _load_model(self) -> None:
        import openwakeword  # type: ignore[import]
        from openwakeword.model import Model  # type: ignore[import]

        # openwakeword includes built-in models.  Map common phrases to model names.
        _BUILTIN_MODELS = {
            "hey jarvis": "hey_jarvis",
            "hey mycroft": "hey_mycroft",
            "alexa": "alexa",
            "hey siri": "hey_siri",
        }
        model_name = _BUILTIN_MODELS.get(self._phrase.lower().strip())

        if model_name:
            # Download pre-trained model if not cached
            openwakeword.utils.download_models([model_name])
            self._model = Model(wakeword_models=[model_name], inference_framework="onnx")
            self._model_name = model_name
        else:
            logger.warning(
                "Wake phrase '%s' has no built-in openwakeword model.\n"
                "Available built-in phrases: %s\n"
                "For custom phrases see: https://github.com/dscripka/openWakeWord",
                self._phrase, list(_BUILTIN_MODELS.keys()),
            )
            return

        self._ready = True
        logger.info("Wake word detector ready: '%s' (threshold=%.2f)", self._phrase, self._threshold)

    def listen_for_trigger(self) -> bool:
        """
        Blocking call: reads audio chunks until wake phrase detected.
        Returns True on trigger, False if model is unavailable.
        """
        if not self._ready or self._model is None:
            # Degrade gracefully: if no wake word model, always return True
            # so the conversation loop still works (always-on mode)
            import time
            time.sleep(0.1)
            return True

        import sounddevice as sd  # type: ignore[import]
        import numpy as np

        with sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._chunk_samples,
        ) as stream:
            while True:
                audio_chunk, _ = stream.read(self._chunk_samples)
                audio_int16 = audio_chunk.flatten()

                # openwakeword expects float32 in [-1, 1]
                audio_f32 = audio_int16.astype(np.float32) / 32768.0
                predictions = self._model.predict(audio_f32)

                if self._model_name and self._model_name in predictions:
                    score = predictions[self._model_name]
                    if score >= self._threshold:
                        logger.info(
                            "Wake word detected: '%s' (score=%.3f)", self._phrase, score
                        )
                        self._model.reset()
                        return True


# ---------------------------------------------------------------------------
# __main__ — smoke tests
# ---------------------------------------------------------------------------
async def _smoke_say(text: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    a = AudioModule()
    await a.initialize()
    await a.speak(text)
    await a.stop()


async def _smoke_listen() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    a = AudioModule()
    await a.initialize()
    print("Listening… speak now.")
    text = await a.listen()
    print(f"\nTranscribed: {text!r}\n")
    await a.stop()


async def _smoke_run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async def echo_response(user_text: str) -> str:
        return f"You said: {user_text}"

    a = AudioModule()
    await a.initialize()
    await a.speak("Audio module ready. Say 'hey jarvis' to begin.")
    await a.start_loop(echo_response)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)

    print("Running. Press Ctrl-C to stop.\n")
    try:
        await stop_event.wait()
    finally:
        await a.stop()


if __name__ == "__main__":
    import sys as _sys

    if "--say" in _sys.argv:
        idx = _sys.argv.index("--say")
        text = _sys.argv[idx + 1] if idx + 1 < len(_sys.argv) else "Hello from JRVS."
        asyncio.run(_smoke_say(text))
    elif "--listen-once" in _sys.argv:
        asyncio.run(_smoke_listen())
    else:
        asyncio.run(_smoke_run())
