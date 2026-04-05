"""
CameraManager — opens and maintains a camera or screen stream.

Supported sources (set via config.yaml or JRVS_VISION_CAMERA_SOURCE):
  0, 1, …              USB / built-in webcam (device index)
  http://IP:4747/video DroidCam over WiFi (MJPEG HTTP stream)
  rtsp://…             RTSP network camera
  http://…             Any HTTP MJPEG stream
  "screen"             Primary monitor (desktop screen capture)
  "screen:0"           All monitors combined
  "screen:2"           Secondary monitor
  "screen:1:x,y,w,h"  Cropped region, e.g. "screen:1:0,0,1280,720"

For physical cameras the manager runs a background thread with exponential-
backoff reconnect.  Screen sources are delegated to ScreenCapture (mss).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Union

import cv2
import numpy as np

from extensions.vision.camera.screen_capture import ScreenCapture

logger = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 1.0   # seconds
_RECONNECT_MAX_DELAY  = 30.0  # seconds
_FRAME_TIMEOUT        = 5.0   # seconds before declaring source stale


class CameraManager:
    """
    Thread-safe camera / screen reader.

    Automatically routes to ScreenCapture when source starts with "screen",
    otherwise uses OpenCV VideoCapture for USB/RTSP/HTTP cameras.
    """

    def __init__(self, source: Union[int, str], fps_capture: float = 2.0) -> None:
        self.source = source
        self._fps_capture = fps_capture
        self._screen: Optional[ScreenCapture] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._last_frame_time: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_screen = ScreenCapture.is_screen_source(source)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the source and start capturing."""
        if self._running:
            return
        # Screen source — delegate entirely to ScreenCapture
        if self._is_screen:
            self._screen = ScreenCapture(
                source=str(self.source), fps=self._fps_capture
            )
            self._screen.open()
            self._running = True
            return
        # Physical camera source — use OpenCV reader thread
        self._running = True
        self._thread = threading.Thread(
            target=self._reader_loop, name="vision-camera-reader", daemon=True
        )
        self._thread.start()
        # Wait up to 5 s for first frame
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self._latest_frame is not None:
                logger.info("Camera opened: %s", self.source)
                return
            time.sleep(0.1)
        logger.debug("Camera %s opened but no frame received within 5 s", self.source)

    def close(self) -> None:
        """Stop capturing and release resources."""
        self._running = False
        if self._screen:
            self._screen.close()
            self._screen = None
            return
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap and self._cap.isOpened():
            self._cap.release()
        logger.info("Camera closed: %s", self.source)

    def read_frame(self) -> Optional[np.ndarray]:
        """Return the most recent frame (BGR), or None if unavailable."""
        if self._screen:
            return self._screen.read_frame()
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            if time.monotonic() - self._last_frame_time > _FRAME_TIMEOUT:
                logger.warning("Camera stream appears stale (no frame for %.0fs)", _FRAME_TIMEOUT)
                return None
            return self._latest_frame.copy()

    @property
    def is_open(self) -> bool:
        if self._screen:
            return self._screen.is_open
        return self._running and self._cap is not None and self._cap.isOpened()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Try to open the capture.  Returns True on success."""
        if self._cap and self._cap.isOpened():
            self._cap.release()
        self._cap = cv2.VideoCapture(self.source)
        if isinstance(self.source, str):
            # Lower buffer for HTTP/RTSP to reduce latency
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self._cap.isOpened():
            logger.info("Connected to camera source: %s", self.source)
            return True
        logger.debug("Could not open camera source: %s", self.source)
        return False

    def _reader_loop(self) -> None:
        """Continuously read frames; reconnect on failure."""
        delay = _RECONNECT_BASE_DELAY
        while self._running:
            if not self._connect():
                time.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                continue
            delay = _RECONNECT_BASE_DELAY  # reset on successful connect
            while self._running:
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    logger.warning("Frame read failed on %s; reconnecting…", self.source)
                    break
                with self._frame_lock:
                    self._latest_frame = frame
                    self._last_frame_time = time.monotonic()
        if self._cap:
            self._cap.release()
