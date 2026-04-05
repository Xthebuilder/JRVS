"""
PiperBackend — TTS via the Piper neural text-to-speech engine.

Piper is a fast, local, high-quality TTS system from Rhasspy.
It ships as a standalone binary and ONNX voice models.

Install:
  1. Download binary from https://github.com/rhasspy/piper/releases
     (e.g., piper_linux_x86_64.tar.gz) and put `piper` on your PATH.
  2. Download a voice model (.onnx + .onnx.json) into models_dir.
     Example: en_US-lessac-medium.onnx
     See: https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US

Usage in config.yaml:
  tts:
    backend: "piper"
    piper:
      model: "en_US-lessac-medium"
      models_dir: "~/.local/share/piper-voices"
      binary: "piper"

Piper is invoked as a subprocess: text is piped to stdin, raw PCM comes out
on stdout.  This approach avoids Python binding complexities and matches the
recommended Piper integration pattern.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from extensions.audio.output.audio_player import AudioPlayer
from extensions.audio.output.tts_engine import TTSBackend

logger = logging.getLogger(__name__)


class PiperBackend(TTSBackend):
    """TTS via Piper binary subprocess."""

    def __init__(
        self,
        model_name: str = "en_US-lessac-medium",
        models_dir: str = "~/.local/share/piper-voices",
        binary: str = "piper",
        sample_rate: int = 22050,
        speed: float = 1.0,
    ) -> None:
        self._model_name = model_name
        self._models_dir = Path(models_dir).expanduser()
        self._binary = binary
        self._sample_rate = sample_rate
        self._speed = speed
        self._model_path: Optional[Path] = None
        self._ready = False
        self._interrupted = False
        self._player = AudioPlayer()

    async def initialize(self) -> None:
        """Verify Piper binary exists and locate the voice model."""
        binary_path = shutil.which(self._binary)
        if binary_path is None:
            logger.error(
                "Piper binary '%s' not found. Download from "
                "https://github.com/rhasspy/piper/releases and add to PATH.",
                self._binary,
            )
            return

        # Find model file: models_dir/en_US-lessac-medium.onnx
        model_file = self._models_dir / f"{self._model_name}.onnx"
        if not model_file.exists():
            # Also check without directory prefix in name
            candidates = list(self._models_dir.glob(f"*{self._model_name}*.onnx"))
            if candidates:
                model_file = candidates[0]
                logger.info("Found Piper model: %s", model_file)
            else:
                logger.error(
                    "Piper model '%s.onnx' not found in %s.\n"
                    "Download from: https://huggingface.co/rhasspy/piper-voices",
                    self._model_name, self._models_dir,
                )
                return

        self._model_path = model_file
        self._ready = True
        logger.info("Piper TTS ready: binary=%s, model=%s", binary_path, model_file.name)

    def stop_speaking(self) -> None:
        """Interrupt ongoing playback (barge-in or thinking-phrase cancellation)."""
        self._interrupted = True
        self._player.stop()

    async def speak(self, text: str) -> None:
        """Synthesize text and play through system audio.

        For multi-sentence responses, pipelines synthesis of sentence N+1
        with playback of sentence N so there is no gap between sentences
        and the first word is heard as soon as the first sentence is ready.
        """
        if not self._ready or self._model_path is None:
            logger.warning("PiperBackend not ready; cannot speak.")
            return
        if not text.strip():
            return

        self._interrupted = False  # reset on each new speak() call

        sentences = self._split_sentences(text)
        if not sentences:
            return

        if len(sentences) == 1:
            pcm_bytes = await self._synthesize(sentences[0])
            if pcm_bytes and not self._interrupted:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._player.play_pcm_bytes(
                        pcm_bytes, self._sample_rate, channels=1, sample_width=2
                    ),
                )
            return

        # Multi-sentence: producer synthesizes ahead while consumer plays.
        # Queue size 2 keeps one sentence pre-rendered and ready.
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)

        async def _produce() -> None:
            for s in sentences:
                if self._interrupted:
                    break
                pcm = await self._synthesize(s)
                await queue.put(pcm)
            await queue.put(None)  # sentinel

        async def _consume() -> None:
            loop = asyncio.get_running_loop()
            while True:
                pcm = await queue.get()
                if pcm is None or self._interrupted:
                    break
                if pcm:
                    await loop.run_in_executor(
                        None,
                        lambda p=pcm: self._player.play_pcm_bytes(
                            p, self._sample_rate, channels=1, sample_width=2
                        ),
                    )

        try:
            await asyncio.gather(_produce(), _consume())
        except asyncio.CancelledError:
            self._interrupted = True
            self._player.stop()
            raise

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into natural spoken chunks at sentence boundaries."""
        # Split on .  !  ?  followed by whitespace, and also on newlines
        parts = re.split(r'(?<=[.!?])\s+', text.strip())
        sentences: List[str] = []
        for part in parts:
            for line in part.split("\n"):
                line = line.strip()
                if len(line) > 2:
                    sentences.append(line)
        return sentences

    async def _synthesize(self, text: str) -> bytes:
        """Run Piper and collect raw PCM output."""
        cmd = [
            self._binary,
            "--model", str(self._model_path),
            "--output_raw",
            "--length_scale", str(1.0 / max(self._speed, 0.1)),
        ]
        # Piper ships its .so files alongside the binary.  Add the binary's
        # directory to LD_LIBRARY_PATH so it finds them regardless of where
        # the binary lives (Python 3.14 uses posix_spawn which doesn't run
        # shell wrappers, so we set the env directly here instead).
        env = os.environ.copy()
        binary_dir = str(Path(self._binary).parent)
        env["LD_LIBRARY_PATH"] = (
            binary_dir + ":" + env.get("LD_LIBRARY_PATH", "")
        ).rstrip(":")
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await proc.communicate(input=text.encode("utf-8"))
            if proc.returncode != 0:
                logger.error("Piper error: %s", stderr.decode(errors="replace")[:200])
                return b""
            return stdout
        except asyncio.CancelledError:
            # Kill the subprocess before re-raising so the asyncio subprocess
            # transport can shut down cleanly.  Leaving the process running
            # while the transport is garbage-collected produces
            # "InvalidStateError: invalid state" in _call_connection_lost.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
            raise
        except FileNotFoundError:
            logger.error("Piper binary not found: %s", self._binary)
            return b""
        except Exception as exc:
            logger.error("Piper synthesis error: %s", exc)
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return b""

    def is_ready(self) -> bool:
        return self._ready
