"""
ScreenCapture — grabs frames from the desktop display using mss.

Exposes the same interface as CameraManager (open / close / read_frame / is_open)
so VisionModule doesn't need to know which source type is active.

Source string format:
  "screen"      → primary monitor (monitor 1)
  "screen:0"    → all monitors combined into one wide frame
  "screen:1"    → monitor 1 (primary)
  "screen:2"    → monitor 2 (if connected)
  "screen:1:x,y,w,h"  → crop region on monitor 1, e.g. "screen:1:0,0,1280,720"

Requires:  pip install mss
Linux note: works with X11 and Wayland (via XWayland).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import mss
    import mss.tools
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False
    logger.error("mss not installed. Run: pip install mss")

_FRAME_TIMEOUT = 10.0   # seconds before declaring screen reader stale


class ScreenCapture:
    """
    Thread-safe desktop screen grabber.

    Continuously grabs frames into a one-element buffer; read_frame() returns
    the latest grab without blocking the async event loop.
    """

    def __init__(self, source: str = "screen", fps: float = 2.0) -> None:
        """
        Args:
            source: "screen", "screen:N", or "screen:N:x,y,w,h"
            fps:    Target grabs per second (actual rate may be lower on slow machines)
        """
        self.source = source
        self._fps = fps
        self._monitor_idx, self._region = self._parse_source(source)

        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._last_frame_time: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API  (matches CameraManager interface)
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Start the background screen-grab thread."""
        if not _MSS_AVAILABLE:
            raise RuntimeError("mss is not installed. Run: pip install mss")
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._grab_loop, name="vision-screen-grab", daemon=True
        )
        self._thread.start()
        # Wait up to 3 s for first frame
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self._latest_frame is not None:
                label = self._region_label()
                logger.info("Screen capture opened: %s", label)
                return
            time.sleep(0.05)
        logger.warning("Screen capture started but no frame received within 3 s")

    def close(self) -> None:
        """Stop the grab thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("Screen capture closed: %s", self.source)

    def read_frame(self) -> Optional[np.ndarray]:
        """Return the most recent screen frame (BGR), or None if unavailable."""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            if time.monotonic() - self._last_frame_time > _FRAME_TIMEOUT:
                logger.warning("Screen capture stale (no frame for %.0fs)", _FRAME_TIMEOUT)
                return None
            return self._latest_frame.copy()

    @property
    def is_open(self) -> bool:
        return self._running and self._latest_frame is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _grab_loop(self) -> None:
        interval = 1.0 / max(self._fps, 0.1)
        with mss.mss() as sct:
            monitors = sct.monitors  # [0]=all, [1]=primary, [2]=secondary, …
            monitor_count = len(monitors) - 1  # subtract the "all" entry

            monitor = self._resolve_monitor(monitors, monitor_count)
            if monitor is None:
                logger.error("Screen capture: no valid monitor found for source '%s'", self.source)
                return

            logger.debug(
                "Screen grab loop: monitor=%d region=%s fps=%.1f",
                self._monitor_idx, self._region, self._fps,
            )

            while self._running:
                try:
                    grab_target = self._region or monitor
                    shot = sct.grab(grab_target)
                    # mss returns BGRA; drop alpha channel → BGR for OpenCV compatibility
                    frame = np.array(shot)[:, :, :3]
                    with self._frame_lock:
                        self._latest_frame = frame
                        self._last_frame_time = time.monotonic()
                except Exception as exc:
                    logger.error("Screen grab error: %s", exc)
                time.sleep(interval)

    def _resolve_monitor(self, monitors, count):
        """Return the mss monitor dict to grab, or None on error."""
        if self._monitor_idx > count:
            logger.error(
                "Monitor %d requested but only %d monitor(s) available.",
                self._monitor_idx, count,
            )
            return None
        return monitors[self._monitor_idx]

    def _region_label(self) -> str:
        if self._region:
            r = self._region
            return f"monitor {self._monitor_idx} region {r['left']},{r['top']} {r['width']}x{r['height']}"
        if self._monitor_idx == 0:
            return "all monitors"
        return f"monitor {self._monitor_idx}"

    # ------------------------------------------------------------------
    # Source string parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_source(source: str) -> Tuple[int, Optional[dict]]:
        """
        Parse source string into (monitor_index, region_dict_or_None).

        Examples:
          "screen"         → (1, None)       primary monitor, full
          "screen:0"       → (0, None)       all monitors combined
          "screen:2"       → (2, None)       secondary monitor, full
          "screen:1:0,0,1280,720" → (1, {"left":0,"top":0,"width":1280,"height":720})
        """
        parts = source.split(":")
        # parts[0] is "screen"
        monitor_idx = 1  # default = primary
        region = None

        if len(parts) >= 2 and parts[1].strip():
            try:
                monitor_idx = int(parts[1])
            except ValueError:
                logger.warning("Invalid monitor index '%s'; defaulting to 1", parts[1])

        if len(parts) >= 3 and parts[2].strip():
            try:
                x, y, w, h = (int(v) for v in parts[2].split(","))
                region = {"left": x, "top": y, "width": w, "height": h}
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid crop region '%s'; capturing full monitor.", parts[2]
                )

        return monitor_idx, region

    @staticmethod
    def is_screen_source(source) -> bool:
        """Return True if the source string denotes a screen capture."""
        return isinstance(source, str) and source.lower().startswith("screen")
