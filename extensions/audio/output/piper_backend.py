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
import shutil
from pathlib import Path
from typing import Optional

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

    async def speak(self, text: str) -> None:
        """Synthesize text and play through system audio."""
        if not self._ready or self._model_path is None:
            logger.warning("PiperBackend not ready; cannot speak.")
            return
        if not text.strip():
            return

        pcm_bytes = await self._synthesize(text)
        if pcm_bytes:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._player.play_pcm_bytes(
                    pcm_bytes, self._sample_rate, channels=1, sample_width=2
                ),
            )

    async def _synthesize(self, text: str) -> bytes:
        """Run Piper and collect raw PCM output."""
        cmd = [
            self._binary,
            "--model", str(self._model_path),
            "--output_raw",
            "--length_scale", str(1.0 / max(self._speed, 0.1)),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(input=text.encode("utf-8"))
            if proc.returncode != 0:
                logger.error("Piper error: %s", stderr.decode(errors="replace")[:200])
                return b""
            return stdout
        except FileNotFoundError:
            logger.error("Piper binary not found: %s", self._binary)
            return b""
        except Exception as exc:
            logger.error("Piper synthesis error: %s", exc)
            return b""

    def is_ready(self) -> bool:
        return self._ready
