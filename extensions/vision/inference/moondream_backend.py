"""
MoondreamBackend — visual inference using Moondream2 loaded locally.

Model: vikhyatk/moondream2 (HuggingFace)
Loaded lazily on first call to describe() so startup is fast.

No external API calls; everything runs locally.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from extensions.vision.inference.vision_inference import VisionBackend

logger = logging.getLogger(__name__)


class MoondreamBackend(VisionBackend):
    """Moondream2 local vision-language model."""

    def __init__(
        self,
        model_id: str = "vikhyatk/moondream2",
        revision: str = "2025-01-09",
        model_path: Optional[str] = None,
    ) -> None:
        self._model_id = model_id
        self._revision = revision
        self._cache_dir = model_path  # None → HuggingFace default cache
        self._model = None
        self._tokenizer = None
        self._ready = False
        self._load_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Load Moondream model in thread pool (avoids blocking event loop)."""
        async with self._load_lock:
            if self._ready:
                return
            logger.info("Loading Moondream model '%s' (this may take a minute)…", self._model_id)
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._load_model)
                self._ready = True
                logger.info("Moondream model loaded.")
            except Exception as exc:
                logger.error("Moondream load failed: %s", exc)
                self._ready = False

    def _load_model(self) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        kwargs = {"trust_remote_code": True, "revision": self._revision}
        if self._cache_dir:
            kwargs["cache_dir"] = self._cache_dir

        self._tokenizer = AutoTokenizer.from_pretrained(self._model_id, **kwargs)
        self._model = AutoModelForCausalLM.from_pretrained(self._model_id, **kwargs)
        self._model.eval()

    async def describe(self, frame: np.ndarray, prompt: str) -> str:
        if not self._ready:
            await self.initialize()
        if not self._ready:
            return "[vision offline — Moondream not loaded]"

        pil_img = self._frame_to_pil(frame)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, self._infer, pil_img, prompt
            )
            return result
        except Exception as exc:
            logger.error("Moondream inference error: %s", exc)
            return f"[vision error: {exc}]"

    def _infer(self, pil_img: Image.Image, prompt: str) -> str:
        enc_img = self._model.encode_image(pil_img)
        return self._model.answer_question(enc_img, prompt, self._tokenizer)

    def is_ready(self) -> bool:
        return self._ready

    @staticmethod
    def _frame_to_pil(frame: np.ndarray) -> Image.Image:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)
