"""
DiaBackend — TTS via Nari Labs Dia-1.6B neural TTS model.

Dia is a 1.6B-parameter dialogue TTS model that produces highly natural,
expressive speech — significantly more human-sounding than Piper or Kokoro.

GitHub:  https://github.com/nari-labs/dia
Model:   nari-labs/Dia-1.6B  (~3 GB, auto-downloaded from HuggingFace)

Install:
  pip install torch --index-url https://download.pytorch.org/whl/cu124
  pip install git+https://github.com/nari-labs/dia.git

VRAM note:
  Dia-1.6B (float16) needs ~3-4 GB VRAM.  If your GPU also runs the LLM
  (e.g. Gemma 12B = ~10 GB), set OLLAMA_KEEP_ALIVE=0 in your .env so the
  LLM unloads immediately after each response, freeing VRAM for Dia.

Usage in config.yaml:
  tts:
    backend: "dia"
    dia:
      model_id: "nari-labs/Dia-1.6B"
      device: "cuda"            # "cuda" or "cpu"
      compute_dtype: "float16"  # "float16" (GPU) or "float32"
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional

import numpy as np

from extensions.audio.output.audio_player import AudioPlayer
from extensions.audio.output.tts_engine import TTSBackend

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100  # Dia outputs 44.1 kHz


class DiaBackend(TTSBackend):
    """TTS via Nari Labs Dia-1.6B — high-quality neural speech synthesis."""

    def __init__(
        self,
        model_id: str = "nari-labs/Dia-1.6B-0626",
        device: str = "cuda",
        compute_dtype: str = "float16",
        speed: float = 1.0,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._compute_dtype = compute_dtype
        self._speed = speed
        self._model = None
        self._ready = False
        self._load_lock = asyncio.Lock()
        self._player = AudioPlayer()
        self._interrupted = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Download (first run) and load the Dia model in a thread pool."""
        async with self._load_lock:
            if self._ready:
                return
            logger.info(
                "Loading Dia TTS model '%s' on %s (%s) — first run downloads ~3 GB…",
                self._model_id, self._device, self._compute_dtype,
            )
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._load_model
                )
                self._ready = True
                logger.info("Dia TTS ready (device=%s).", self._device)
            except ImportError:
                logger.error(
                    "Dia not installed. Run:\n"
                    "  pip install torch --index-url https://download.pytorch.org/whl/cu124\n"
                    "  pip install git+https://github.com/nari-labs/dia.git"
                )
            except Exception as exc:
                if self._device == "cuda":
                    logger.warning(
                        "Dia CUDA load failed (%s) — VRAM may be full. "
                        "Set OLLAMA_KEEP_ALIVE=0 in .env to free GPU memory. "
                        "Retrying on CPU…", exc
                    )
                    self._device = "cpu"
                    self._compute_dtype = "float32"
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, self._load_model
                        )
                        self._ready = True
                        logger.info("Dia TTS ready (CPU fallback — will be slow).")
                    except Exception as exc2:
                        logger.error("Dia CPU fallback also failed: %s", exc2)
                else:
                    logger.error("Dia load failed: %s", exc)

    def _load_model(self) -> None:
        from dia.model import Dia  # type: ignore[import]
        self._model = Dia.from_pretrained(
            self._model_id,
            compute_dtype=self._compute_dtype,
        )

    def stop_speaking(self) -> None:
        """Interrupt ongoing playback (barge-in support)."""
        self._interrupted = True
        self._player.stop()

    # ------------------------------------------------------------------
    # speak — sentence-level pipeline (synthesise N+1 while playing N)
    # ------------------------------------------------------------------

    async def speak(self, text: str) -> None:
        """Synthesise text and play. Pipelines sentences for low latency."""
        if not self._ready or self._model is None:
            logger.warning("DiaBackend not ready; cannot speak.")
            return
        if not text.strip():
            return

        self._interrupted = False  # reset on each new speak() call

        sentences = self._split_sentences(text)
        if not sentences:
            return

        if len(sentences) == 1:
            audio = await asyncio.get_running_loop().run_in_executor(
                None, self._synthesize, sentences[0]
            )
            if audio is not None and not self._interrupted:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self._player.play_array(audio, SAMPLE_RATE)
                )
            return

        # Multi-sentence: producer synthesises ahead while consumer plays.
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)

        async def _produce() -> None:
            for s in sentences:
                if self._interrupted:
                    break
                audio = await asyncio.get_running_loop().run_in_executor(
                    None, self._synthesize, s
                )
                await queue.put(audio)
            await queue.put(None)  # sentinel

        async def _consume() -> None:
            while True:
                audio = await queue.get()
                if audio is None or self._interrupted:
                    break
                if audio is not None:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda a=audio: self._player.play_array(a, SAMPLE_RATE)
                    )

        try:
            await asyncio.gather(_produce(), _consume())
        except asyncio.CancelledError:
            self._interrupted = True
            self._player.stop()
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _synthesize(self, text: str) -> Optional[np.ndarray]:
        """Run one Dia inference call. Returns float32 array at 44100 Hz."""
        try:
            # Dia requires a speaker tag for single-speaker output
            tagged = f"[S1] {text.strip()}"
            audio = self._model.generate(tagged, verbose=False)
            if audio is None or len(audio) == 0:
                return None
            return np.array(audio, dtype=np.float32)
        except Exception as exc:
            logger.error("Dia synthesis error: %s", exc)
            return None

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into natural sentence chunks for streaming playback."""
        parts = re.split(r'(?<=[.!?])\s+', text.strip())
        sentences: List[str] = []
        for part in parts:
            for line in part.split("\n"):
                line = line.strip()
                if len(line) > 2:
                    sentences.append(line)
        return sentences

    def is_ready(self) -> bool:
        return self._ready
