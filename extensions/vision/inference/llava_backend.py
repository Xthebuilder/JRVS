"""
LLaVABackend — visual inference via LLaVA model served by Ollama.

Sends base64-encoded JPEG frames to the Ollama /api/generate endpoint.
Reuses the same Ollama instance JRVS already runs for text generation.

No external API calls; everything runs locally.
"""
from __future__ import annotations

import base64
import json
import logging
from io import BytesIO
from typing import Optional

import aiohttp
import cv2
import numpy as np
from PIL import Image

from extensions.vision.inference.vision_inference import VisionBackend

logger = logging.getLogger(__name__)


class LLaVABackend(VisionBackend):
    """LLaVA multimodal inference via Ollama /api/generate."""

    def __init__(
        self,
        model: str = "llava:7b",
        ollama_url: str = "http://localhost:11434",
        timeout: int = 60,
    ) -> None:
        self._model = model
        self._ollama_url = ollama_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._ready = False

    async def initialize(self) -> None:
        """Verify Ollama is reachable and the model is available."""
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        try:
            async with self._session.get(f"{self._ollama_url}/api/tags") as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ollama returned HTTP {resp.status}")
                data = await resp.json()
                models = [m["name"] for m in data.get("models", [])]
                if not any(self._model in m for m in models):
                    logger.warning(
                        "Model '%s' not found in Ollama. Available: %s. "
                        "Run: ollama pull %s",
                        self._model, models, self._model,
                    )
                else:
                    logger.info("LLaVA model '%s' confirmed in Ollama.", self._model)
            self._ready = True
        except Exception as exc:
            logger.error("LLaVA backend init failed: %s", exc)
            self._ready = False

    async def describe(self, frame: np.ndarray, prompt: str) -> str:
        if not self._ready or self._session is None:
            return "[vision offline — LLaVA not available]"

        b64 = self._frame_to_b64(frame)
        payload = {
            "model": self._model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
        try:
            async with self._session.post(
                f"{self._ollama_url}/api/generate", json=payload
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Ollama /api/generate error %d: %s", resp.status, text[:200])
                    return "[vision error — Ollama returned non-200]"
                data = await resp.json()
                return data.get("response", "").strip()
        except asyncio.TimeoutError:
            logger.warning("LLaVA inference timed out")
            return "[vision timeout]"
        except Exception as exc:
            logger.error("LLaVA describe() error: %s", exc)
            return f"[vision error: {exc}]"

    def is_ready(self) -> bool:
        return self._ready

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _frame_to_b64(frame: np.ndarray) -> str:
        """Convert BGR numpy frame to base64-encoded JPEG string."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        buf = BytesIO()
        pil_img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


# Needed for timeout error reference inside describe()
import asyncio  # noqa: E402
