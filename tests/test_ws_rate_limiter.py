"""
Unit tests for core.ws_rate_limiter — WebSocket sliding-window rate limiter.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ws_rate_limiter import WebSocketRateLimiter


class TestWebSocketRateLimiter:
    """Tests for the sliding-window rate limiter."""

    def test_default_construction(self):
        limiter = WebSocketRateLimiter()
        assert limiter.max_messages == 30
        assert limiter.window_seconds == 60.0

    def test_custom_construction(self):
        limiter = WebSocketRateLimiter(max_messages=5, window_seconds=10.0)
        assert limiter.max_messages == 5
        assert limiter.window_seconds == 10.0

    def test_not_limited_initially(self):
        limiter = WebSocketRateLimiter(max_messages=3, window_seconds=60)
        assert limiter.is_limited("conn1") is False

    def test_limited_after_exceeding_max(self):
        limiter = WebSocketRateLimiter(max_messages=3, window_seconds=60)
        for _ in range(3):
            limiter.record("conn1")
        assert limiter.is_limited("conn1") is True

    def test_not_limited_below_max(self):
        limiter = WebSocketRateLimiter(max_messages=5, window_seconds=60)
        for _ in range(4):
            limiter.record("conn1")
        assert limiter.is_limited("conn1") is False

    def test_separate_connections_independent(self):
        limiter = WebSocketRateLimiter(max_messages=2, window_seconds=60)
        limiter.record("conn1")
        limiter.record("conn1")
        limiter.record("conn2")
        assert limiter.is_limited("conn1") is True
        assert limiter.is_limited("conn2") is False

    def test_disconnect_clears_state(self):
        limiter = WebSocketRateLimiter(max_messages=2, window_seconds=60)
        limiter.record("conn1")
        limiter.record("conn1")
        assert limiter.is_limited("conn1") is True
        limiter.disconnect("conn1")
        assert limiter.is_limited("conn1") is False

    def test_disconnect_nonexistent_no_error(self):
        limiter = WebSocketRateLimiter(max_messages=5, window_seconds=60)
        limiter.disconnect("no_such_conn")  # should not raise

    def test_window_expiry_unblocks(self):
        """Messages older than the window should be pruned."""
        limiter = WebSocketRateLimiter(max_messages=2, window_seconds=1.0)
        # Manually insert old timestamps
        old_time = time.monotonic() - 2.0
        limiter._windows["conn1"].append(old_time)
        limiter._windows["conn1"].append(old_time)
        # Old messages should be pruned, so not limited
        assert limiter.is_limited("conn1") is False

    def test_record_after_prune_allows_new(self):
        limiter = WebSocketRateLimiter(max_messages=1, window_seconds=0.01)
        limiter.record("conn1")
        assert limiter.is_limited("conn1") is True
        # Wait for window to expire
        time.sleep(0.02)
        assert limiter.is_limited("conn1") is False
        limiter.record("conn1")
        assert limiter.is_limited("conn1") is True
