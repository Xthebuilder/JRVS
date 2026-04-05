"""
Unit tests for the authentication system.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAuthTokenGeneration:
    """Test token generation and verification."""

    def test_generate_token_format(self):
        from core.auth import generate_token
        token = generate_token()
        assert token.startswith("jrvs_")
        assert len(token) > 20

    def test_generate_unique_tokens(self):
        from core.auth import generate_token
        tokens = {generate_token() for _ in range(10)}
        assert len(tokens) == 10  # All unique


class TestAuthVerification:
    """Test token verification logic."""

    def test_verify_valid_token(self):
        from core import auth
        # Simulate loaded tokens
        test_token = "test_secret_token_123"
        import hashlib
        token_hash = hashlib.sha256(test_token.encode()).hexdigest()
        original_hashed = auth._hashed_tokens
        auth._hashed_tokens = {token_hash}
        try:
            assert auth._verify_token(test_token) is True
        finally:
            auth._hashed_tokens = original_hashed

    def test_reject_invalid_token(self):
        from core import auth
        import hashlib
        valid_hash = hashlib.sha256(b"real_token").hexdigest()
        original_hashed = auth._hashed_tokens
        auth._hashed_tokens = {valid_hash}
        try:
            assert auth._verify_token("wrong_token") is False
        finally:
            auth._hashed_tokens = original_hashed

    def test_empty_tokens_means_no_validation(self):
        from core import auth
        original = auth._hashed_tokens
        auth._hashed_tokens = set()
        try:
            # With no tokens configured, verify should fail
            assert auth._verify_token("anything") is False
        finally:
            auth._hashed_tokens = original


class TestWebSocketRateLimiter:
    """Test the WebSocket rate limiter."""

    def test_allows_under_limit(self):
        from core.ws_rate_limiter import WebSocketRateLimiter
        limiter = WebSocketRateLimiter(max_messages=5, window_seconds=60)
        for _ in range(4):
            assert limiter.is_limited("conn1") is False
            limiter.record("conn1")

    def test_blocks_over_limit(self):
        from core.ws_rate_limiter import WebSocketRateLimiter
        limiter = WebSocketRateLimiter(max_messages=3, window_seconds=60)
        for _ in range(3):
            limiter.record("conn1")
        assert limiter.is_limited("conn1") is True

    def test_separate_connections_independent(self):
        from core.ws_rate_limiter import WebSocketRateLimiter
        limiter = WebSocketRateLimiter(max_messages=2, window_seconds=60)
        limiter.record("conn1")
        limiter.record("conn1")
        assert limiter.is_limited("conn1") is True
        assert limiter.is_limited("conn2") is False

    def test_disconnect_cleans_up(self):
        from core.ws_rate_limiter import WebSocketRateLimiter
        limiter = WebSocketRateLimiter(max_messages=2, window_seconds=60)
        limiter.record("conn1")
        limiter.record("conn1")
        limiter.disconnect("conn1")
        assert limiter.is_limited("conn1") is False
