"""
Unit tests for mcp/rate_limiter.py

Tests TokenBucket, RateLimiter, ResourceManager, and QuotaManager.
No external dependencies.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.rate_limiter import TokenBucket, RateLimiter, ResourceManager, QuotaManager
from mcp.exceptions import RateLimitExceededError, ResourceExhaustedError


class TestTokenBucket:
    def _bucket(self, capacity=10, rate=10.0, tokens=None):
        return TokenBucket(
            capacity=capacity,
            refill_rate=rate,
            tokens=tokens if tokens is not None else capacity,
            last_refill=time.time(),
        )

    def test_consume_succeeds_when_tokens_available(self):
        b = self._bucket()
        assert b.consume(1) is True

    def test_consume_fails_when_empty(self):
        b = self._bucket(tokens=0)
        assert b.consume(1) is False

    def test_consume_reduces_tokens(self):
        b = self._bucket(capacity=10, tokens=5)
        b.consume(3)
        assert b.tokens == pytest.approx(2, abs=0.1)

    def test_consume_multiple_tokens(self):
        b = self._bucket(capacity=10, tokens=10)
        assert b.consume(5) is True
        assert b.tokens == pytest.approx(5, abs=0.1)

    def test_tokens_refill_over_time(self):
        b = self._bucket(capacity=10, tokens=0, rate=100.0)
        time.sleep(0.05)  # 0.05s × 100/s = 5 tokens
        assert b.consume(1) is True  # Should have refilled

    def test_tokens_capped_at_capacity(self):
        b = self._bucket(capacity=5, tokens=5, rate=100.0)
        time.sleep(0.1)
        b._refill()
        assert b.tokens <= 5.0

    def test_get_wait_time_zero_when_tokens_available(self):
        b = self._bucket()
        assert b.get_wait_time(1) == 0.0

    def test_get_wait_time_positive_when_empty(self):
        b = self._bucket(tokens=0, rate=1.0)
        wait = b.get_wait_time(1)
        assert wait > 0.0


class TestRateLimiter:
    def test_allows_first_request(self):
        rl = RateLimiter(default_rate=60, default_burst=10)
        assert rl.check_rate_limit("client1") is True

    def test_raises_when_burst_exceeded(self):
        rl = RateLimiter(default_rate=60, default_burst=3)
        rl.check_rate_limit("c")
        rl.check_rate_limit("c")
        rl.check_rate_limit("c")
        with pytest.raises(RateLimitExceededError):
            rl.check_rate_limit("c")

    def test_different_clients_independent(self):
        rl = RateLimiter(default_rate=60, default_burst=2)
        rl.check_rate_limit("a")
        rl.check_rate_limit("a")
        # Client "b" should still have tokens
        assert rl.check_rate_limit("b") is True

    def test_custom_limit_overrides_default(self):
        rl = RateLimiter(default_rate=60, default_burst=10)
        rl.set_custom_limit("vip", rate=600, burst=50)
        for _ in range(20):
            rl.check_rate_limit("vip")  # Should not raise with burst=50

    def test_get_remaining_tokens_starts_at_burst(self):
        rl = RateLimiter(default_rate=60, default_burst=10)
        remaining = rl.get_remaining_tokens("fresh-client")
        assert remaining == 10

    def test_get_remaining_tokens_decreases(self):
        rl = RateLimiter(default_rate=60, default_burst=10)
        rl.check_rate_limit("c")
        rl.check_rate_limit("c")
        remaining = rl.get_remaining_tokens("c")
        assert remaining <= 8

    def test_stats_shape(self):
        rl = RateLimiter()
        stats = rl.get_stats()
        assert "default_rate" in stats
        assert "default_burst" in stats
        assert "total_clients" in stats

    def test_set_custom_limit_resets_bucket(self):
        rl = RateLimiter(default_rate=60, default_burst=2)
        rl.check_rate_limit("c")
        rl.set_custom_limit("c", rate=60, burst=10)
        # After reset, should have full burst again
        remaining = rl.get_remaining_tokens("c")
        assert remaining == 10


@pytest.mark.asyncio
class TestRateLimiterAsync:
    async def test_wait_for_token_returns(self):
        rl = RateLimiter(default_rate=600, default_burst=5)
        await rl.wait_for_token("client")  # Should return quickly with full bucket


class TestResourceManager:
    def test_acquire_slot_succeeds(self):
        rm = ResourceManager(max_concurrent_requests=5)
        assert rm.acquire_request_slot("req-1") is True

    def test_release_decrements(self):
        rm = ResourceManager(max_concurrent_requests=5)
        rm.acquire_request_slot("req-1")
        rm.release_request_slot("req-1")
        assert rm._current_requests == 0

    def test_raises_when_max_exceeded(self):
        rm = ResourceManager(max_concurrent_requests=2)
        rm.acquire_request_slot("r1")
        rm.acquire_request_slot("r2")
        with pytest.raises(ResourceExhaustedError):
            rm.acquire_request_slot("r3")

    def test_release_nonexistent_is_safe(self):
        rm = ResourceManager()
        rm.release_request_slot("ghost")  # Should not raise

    def test_duration_check_passes_for_new_request(self):
        rm = ResourceManager(max_request_duration_seconds=60)
        rm.acquire_request_slot("r1")
        rm.check_request_duration("r1")  # Should not raise

    def test_duration_check_passes_for_unknown_request(self):
        rm = ResourceManager()
        rm.check_request_duration("unknown")  # Should not raise

    def test_stats_shape(self):
        rm = ResourceManager()
        stats = rm.get_stats()
        assert "concurrent_requests" in stats
        assert "request_durations" in stats


class TestQuotaManager:
    def test_consume_without_limit_always_succeeds(self):
        qm = QuotaManager()
        assert qm.consume("client", "tokens", 100) is True

    def test_consume_within_limit(self):
        qm = QuotaManager()
        qm.set_quota("c", "requests", 10)
        assert qm.consume("c", "requests", 5) is True

    def test_consume_exceeds_limit_raises(self):
        qm = QuotaManager()
        qm.set_quota("c", "requests", 3)
        qm.consume("c", "requests", 3)
        with pytest.raises(ResourceExhaustedError):
            qm.consume("c", "requests", 1)

    def test_get_usage_returns_current(self):
        qm = QuotaManager()
        qm.consume("c", "tokens", 5)
        assert qm.get_usage("c", "tokens") == 5

    def test_get_remaining_with_limit(self):
        qm = QuotaManager()
        qm.set_quota("c", "tokens", 10)
        qm.consume("c", "tokens", 3)
        assert qm.get_remaining("c", "tokens") == 7

    def test_get_remaining_without_limit_is_none(self):
        qm = QuotaManager()
        assert qm.get_remaining("c", "tokens") is None

    def test_stats_shape(self):
        qm = QuotaManager()
        qm.set_quota("c", "api_calls", 100)
        qm.consume("c", "api_calls", 10)
        stats = qm.get_stats("c")
        assert "api_calls" in stats
        assert stats["api_calls"]["current"] == 10
        assert stats["api_calls"]["limit"] == 100
        assert stats["api_calls"]["remaining"] == 90
