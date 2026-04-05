"""
AmbientListener — passive audio sense for the JRVS text CLI.

Runs as a background asyncio task:
  1. Continuously listens on the configured microphone (Blue Yeti by default).
  2. Uses VAD to detect speech boundaries.
  3. Transcribes each utterance with Whisper STT.
  4. Embeds the transcript into JRVS memory (SQLite + FAISS) as an
     "audio_observation" document — the same pipeline used by the vision
     extension for camera frames.

JARVIS can then surface these observations through RAG when answering
questions like "What did I say earlier?" or "What was being discussed?"

This module does NOT generate spoken responses — it is a sense only.

Usage:
    listener = AmbientListener()
    await listener.initialize()
    await listener.start()   # non-blocking; runs in background

    await listener.stop()
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JRVS root bootstrap (mirrors the pattern in vision_logger.py)
# ---------------------------------------------------------------------------
_JRVS_ROOT = Path(__file__).parent.parent.parent
if str(_JRVS_ROOT) not in sys.path:
    sys.path.insert(0, str(_JRVS_ROOT))


class AmbientListener:
    """
    Continuously listens on the microphone and embeds every transcribed
    utterance into JRVS memory so JARVIS can recall what was said.
    """

    CONTENT_TYPE = "audio_observation"

    def __init__(self, config=None) -> None:
        from extensions.audio.config import audio_config
        self._cfg = config or audio_config

        self._mic = None
        self._vad = None
        self._stt = None
        self._db = None
        self._vector_store = None
        self._jrvs_available = False

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_transcript: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Load STT model and connect to JRVS memory."""
        try:
            from extensions.audio.input.microphone import MicrophoneCapture
            from extensions.audio.input.vad import VoiceActivityDetector
            from extensions.audio.input.stt_engine import create_stt_backend

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
            self._stt = create_stt_backend(self._cfg)
            await self._stt.initialize()

            # Connect to JRVS memory
            from core.database import db
            from rag.vector_store import vector_store
            await db.initialize()
            self._db = db
            self._vector_store = vector_store
            self._jrvs_available = True

            logger.info("AmbientListener initialized (device=%s, whisper=%s).",
                        self._cfg.input_device, self._cfg.whisper_model)
            return True

        except Exception as exc:
            logger.debug("AmbientListener init failed: %s", exc)
            return False

    async def start(self) -> None:
        """Start the background listen loop (non-blocking)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop(), name="ambient_listener")
        logger.info("AmbientListener started.")

    async def stop(self) -> None:
        """Stop the background loop and close the microphone."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._mic:
            try:
                self._mic.close()
            except Exception:
                pass
        logger.info("AmbientListener stopped.")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Open the mic and continuously capture → transcribe → embed."""
        loop = asyncio.get_event_loop()

        try:
            self._mic.open()
        except Exception as exc:
            logger.error("AmbientListener: failed to open mic: %s", exc)
            self._running = False
            return

        logger.info("AmbientListener: microphone open, listening for speech…")

        while self._running:
            try:
                # record_utterance blocks until speech + silence — run in thread
                audio = await loop.run_in_executor(
                    None,
                    self._mic.record_utterance,
                    self._vad,
                    self._cfg.max_duration,
                )

                if audio is None:
                    # No speech detected within timeout — reset VAD and retry
                    self._vad.reset()
                    await asyncio.sleep(0.05)
                    continue

                self._vad.reset()

                # transcribe() is async and handles its own thread-pool internally
                transcript = await self._stt.transcribe(audio)
                text = (transcript.text or "").strip()
                if not text:
                    continue

                word_count = len(text.split())
                if word_count < self._cfg.ambient_min_words:
                    logger.debug("AmbientListener: skipping short utterance (%d words): %r",
                                 word_count, text)
                    continue

                if not self._should_log(text):
                    logger.debug("AmbientListener: skipping near-duplicate: %r", text[:80])
                    continue

                await self._embed(text)
                self._last_transcript = text

                # Proactively propose goals from spoken content (fire-and-forget)
                asyncio.create_task(self._maybe_propose_goal(text))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("AmbientListener loop error: %s", exc)
                await asyncio.sleep(1.0)

        try:
            self._mic.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Memory persistence — mirrors VisionLogger.log()
    # ------------------------------------------------------------------

    async def _embed(self, text: str) -> None:
        """Write a transcript into JRVS SQLite + FAISS."""
        now = datetime.now()
        doc_url = f"audio://observation/{int(now.timestamp() * 1000)}"
        doc_title = f"Heard @ {now.strftime('%Y-%m-%d %H:%M:%S')}"
        metadata = {
            "source": "ambient_audio",
            "device": str(self._cfg.input_device),
            "timestamp": now.isoformat(),
            "word_count": len(text.split()),
        }

        if self._jrvs_available and self._db:
            try:
                doc_id = await self._db.add_document(
                    url=doc_url,
                    title=doc_title,
                    content=text,
                    content_type=self.CONTENT_TYPE,
                    metadata=metadata,
                )
                if self._vector_store and doc_id:
                    await self._vector_store.add_documents(
                        texts=[text],
                        metadata=[{**metadata, "doc_id": doc_id, "type": self.CONTENT_TYPE}],
                    )
                logger.debug("AmbientListener: embedded → %s | %r…", doc_title, text[:60])
            except Exception as exc:
                logger.error("AmbientListener: failed to embed transcript: %s", exc)
        else:
            logger.info("[AUDIO] %s | %s", doc_title, text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _maybe_propose_goal(self, text: str) -> None:
        """Ask the goal scheduler if the transcript contains an implied task."""
        try:
            from core.goal_scheduler import goal_scheduler
            await goal_scheduler.on_observation(text, source="ambient_audio")
        except Exception as exc:
            logger.debug("AmbientListener: goal proposal error: %s", exc)

    def _should_log(self, text: str) -> bool:
        """For log_level='scene', skip near-duplicate transcripts."""
        if self._cfg.ambient_log_level == "all" or self._last_transcript is None:
            return True
        prev_words = set(self._last_transcript.lower().split())
        curr_words = set(text.lower().split())
        if not prev_words:
            return True
        overlap = len(prev_words & curr_words) / len(prev_words | curr_words)
        return overlap < 0.6

