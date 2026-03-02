"""
VisionBackend — abstract base + factory for visual inference backends.

Usage:
    backend = create_backend(vision_config)
    await backend.initialize()
    description = await backend.describe(frame_bgr, prompt)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)


class VisionBackend(ABC):
    """Abstract visual inference backend."""

    @abstractmethod
    async def initialize(self) -> None:
        """Load model / verify connectivity.  Called once before first describe()."""

    @abstractmethod
    async def describe(self, frame: np.ndarray, prompt: str) -> str:
        """
        Generate a text description of the given BGR frame.

        Args:
            frame:  BGR numpy array from OpenCV
            prompt: Instruction to the vision model

        Returns:
            Natural-language description string.
        """

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True once initialize() has completed successfully."""


def create_backend(config) -> VisionBackend:
    """
    Factory: instantiate the backend named in config.inference_backend.

    Args:
        config: VisionConfig instance

    Returns:
        Concrete VisionBackend (LLaVABackend or MoondreamBackend)
    """
    backend_name = config.inference_backend.lower()

    if backend_name == "llava":
        from extensions.vision.inference.llava_backend import LLaVABackend
        logger.info("Vision backend: LLaVA via Ollama (%s)", config.llava_ollama_url)
        return LLaVABackend(
            model=config.llava_model,
            ollama_url=config.llava_ollama_url,
            timeout=config.llava_timeout,
        )

    if backend_name == "moondream":
        from extensions.vision.inference.moondream_backend import MoondreamBackend
        logger.info("Vision backend: Moondream local (%s)", config.moondream_model_id)
        return MoondreamBackend(
            model_id=config.moondream_model_id,
            revision=config.moondream_revision,
            model_path=config.moondream_model_path,
        )

    raise ValueError(
        f"Unknown vision inference backend: '{backend_name}'. "
        "Choose 'llava' or 'moondream' in extensions/vision/config.yaml."
    )
