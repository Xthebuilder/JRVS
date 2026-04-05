"""
WebSocket rate limiter — sliding-window per-connection message throttle.

Usage:
    limiter = WebSocketRateLimiter(max_messages=30, window_seconds=60)

    async for message in websocket:
        if limiter.is_limited(connection_id):
            await websocket.send_json({"type": "error", "message": "Rate limited"})
            continue
        limiter.record(connection_id)
        ...
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict


class WebSocketRateLimiter:
    """Sliding-window rate limiter for WebSocket connections."""

    def __init__(self, max_messages: int = 30, window_seconds: float = 60.0) -> None:
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, conn_id: str) -> None:
        """Remove timestamps older than the window."""
        cutoff = time.monotonic() - self.window_seconds
        window = self._windows[conn_id]
        while window and window[0] < cutoff:
            window.popleft()

    def is_limited(self, conn_id: str) -> bool:
        """Check if a connection has exceeded the rate limit."""
        self._prune(conn_id)
        return len(self._windows[conn_id]) >= self.max_messages

    def record(self, conn_id: str) -> None:
        """Record a message from a connection."""
        self._prune(conn_id)
        self._windows[conn_id].append(time.monotonic())

    def disconnect(self, conn_id: str) -> None:
        """Clean up state when a connection closes."""
        self._windows.pop(conn_id, None)
