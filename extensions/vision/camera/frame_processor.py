"""
FrameProcessor — decides which frames are worth sending to the inference backend.

Two conditions trigger processing (either is sufficient):
  1. Motion score ≥ motion_threshold   (significant pixel change)
  2. Seconds since last inference ≥ periodic_interval

Motion is measured by MOG2 background subtraction — more robust than simple
frame differencing because it adapts to gradual lighting changes.

Frames are also resized to max_width before being returned so inference stays fast.
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

import cv2
import numpy as np


class FrameProcessor:
    """Filters and preprocesses camera frames for visual inference."""

    def __init__(
        self,
        motion_threshold: float = 0.05,
        periodic_interval: float = 30.0,
        max_width: int = 512,
    ) -> None:
        self.motion_threshold = motion_threshold
        self.periodic_interval = periodic_interval
        self.max_width = max_width

        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=16, detectShadows=False
        )
        self._last_inference_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self, frame: np.ndarray
    ) -> Tuple[Optional[np.ndarray], float]:
        """
        Evaluate whether frame is interesting.

        Returns (resized_frame, motion_score) if the frame should be inferred,
        or (None, motion_score) if it should be skipped.
        """
        motion_score = self._compute_motion(frame)
        now = time.monotonic()
        elapsed = now - self._last_inference_time

        should_infer = (
            motion_score >= self.motion_threshold
            or elapsed >= self.periodic_interval
        )

        if should_infer:
            self._last_inference_time = now
            return self._resize(frame), motion_score

        return None, motion_score

    def motion_score_only(self, frame: np.ndarray) -> float:
        """Compute motion score without updating the last-inference timer."""
        return self._compute_motion(frame)

    def reset(self) -> None:
        """Reset the background model (call after long pauses)."""
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=16, detectShadows=False
        )
        self._last_inference_time = 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_motion(self, frame: np.ndarray) -> float:
        """Return fraction of pixels classified as foreground by MOG2."""
        mask = self._bg_subtractor.apply(frame)
        # mask values: 0=background, 127=shadow (ignored), 255=foreground
        fg_pixels = np.count_nonzero(mask == 255)
        total = mask.size
        return fg_pixels / total if total > 0 else 0.0

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        """Downscale to max_width while preserving aspect ratio."""
        h, w = frame.shape[:2]
        if w <= self.max_width:
            return frame
        scale = self.max_width / w
        new_w = self.max_width
        new_h = int(h * scale)
        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
