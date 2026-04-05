"""
Unit tests for core.lazy_loader — LazyLoader, ResourcePool, CircuitBreaker,
HealthChecker, retry_on_failure, and with_timeout.
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.lazy_loader import (
    CircuitBreaker,
    HealthChecker,
    LazyLoader,
    ResourcePool,
    retry_on_failure,
    with_timeout,
)


# ---------------------------------------------------------------------------
# LazyLoader
# ---------------------------------------------------------------------------

class TestLazyLoader:

    @pytest.mark.asyncio
    async def test_lazy_load_sync_factory(self):
        loader = LazyLoader(lambda: 42)
        result = await loader.get()
        assert result == 42

    @pytest.mark.asyncio
    async def test_lazy_load_async_factory(self):
        async def factory():
            return "async_value"

        loader = LazyLoader(factory)
        result = await loader.get()
        assert result == "async_value"

    @pytest.mark.asyncio
    async def test_cached_after_first_load(self):
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            return calls

        loader = LazyLoader(factory)
        first = await loader.get()
        second = await loader.get()
        assert first == second == 1

    @pytest.mark.asyncio
    async def test_invalidate_forces_reload(self):
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            return calls

        loader = LazyLoader(factory)
        await loader.get()
        loader.invalidate()
        result = await loader.get()
        assert result == 2

    @pytest.mark.asyncio
    async def test_ttl_expiry_triggers_reload(self):
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            return calls

        loader = LazyLoader(factory, ttl=0.01)
        await loader.get()
        await asyncio.sleep(0.02)
        result = await loader.get()
        assert result == 2


# ---------------------------------------------------------------------------
# ResourcePool
# ---------------------------------------------------------------------------

class TestResourcePool:

    @pytest.mark.asyncio
    async def test_get_or_create_returns_resource(self):
        pool = ResourcePool(max_size=5)
        result = await pool.get_or_create("key1", lambda: "value1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_reuses_existing_resource(self):
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            return f"v{calls}"

        pool = ResourcePool(max_size=5)
        r1 = await pool.get_or_create("k", factory)
        r2 = await pool.get_or_create("k", factory)
        assert r1 == r2 == "v1"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_eviction_when_pool_full(self):
        pool = ResourcePool(max_size=2)
        await pool.get_or_create("a", lambda: "A")
        await pool.get_or_create("b", lambda: "B")
        await pool.get_or_create("c", lambda: "C")  # should evict LRU
        assert "c" in pool._pool
        assert len(pool._pool) <= 2

    @pytest.mark.asyncio
    async def test_cleanup_all_empties_pool(self):
        pool = ResourcePool(max_size=5)
        await pool.get_or_create("x", lambda: "X")
        await pool.cleanup_all()
        assert len(pool._pool) == 0

    @pytest.mark.asyncio
    async def test_cleanup_calls_resource_cleanup(self):
        resource = MagicMock()
        resource.cleanup = MagicMock()
        pool = ResourcePool(max_size=5)
        await pool.get_or_create("r", lambda: resource)
        await pool.cleanup_all()
        resource.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    @pytest.mark.asyncio
    async def test_closed_by_default(self):
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_success_keeps_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        result = await cb.call(lambda: 42)
        assert result == 42
        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        async def failing():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing)

        assert cb.state == "OPEN"

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)

        async def failing():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.call(failing)

        assert cb.state == "OPEN"
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            await cb.call(lambda: "should not run")

    @pytest.mark.asyncio
    async def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        async def failing():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.call(failing)
        assert cb.state == "OPEN"

        await asyncio.sleep(0.02)
        # Next call should transition to HALF_OPEN then succeed
        result = await cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == "CLOSED"


# ---------------------------------------------------------------------------
# retry_on_failure decorator
# ---------------------------------------------------------------------------

class TestRetryOnFailure:

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        @retry_on_failure(max_retries=3, delay=0.01)
        async def good():
            return "ok"

        assert await good() == "ok"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        calls = 0

        @retry_on_failure(max_retries=3, delay=0.01, backoff=1.0)
        async def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("not yet")
            return "finally"

        assert await flaky() == "finally"
        assert calls == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        @retry_on_failure(max_retries=2, delay=0.01, backoff=1.0)
        async def always_fails():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            await always_fails()


# ---------------------------------------------------------------------------
# with_timeout decorator
# ---------------------------------------------------------------------------

class TestWithTimeout:

    @pytest.mark.asyncio
    async def test_fast_function_completes(self):
        @with_timeout(1.0)
        async def quick():
            return "done"

        assert await quick() == "done"

    @pytest.mark.asyncio
    async def test_slow_function_times_out(self):
        @with_timeout(0.01)
        async def slow():
            await asyncio.sleep(10)
            return "never"

        with pytest.raises(Exception, match="timed out"):
            await slow()


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------

class TestHealthChecker:

    def test_register_component(self):
        hc = HealthChecker()
        hc.register_component("db", lambda: True)
        assert "db" in hc.components
        assert hc.health_status["db"]["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_check_healthy_component(self):
        hc = HealthChecker()
        hc.register_component("db", lambda: True)
        await hc._check_all_components()
        assert hc.health_status["db"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_check_unhealthy_component(self):
        hc = HealthChecker()
        hc.register_component("db", lambda: False)
        await hc._check_all_components()
        assert hc.health_status["db"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_erroring_component(self):
        def explode():
            raise ConnectionError("db down")

        hc = HealthChecker()
        hc.register_component("db", explode)
        await hc._check_all_components()
        assert hc.health_status["db"]["status"] == "error"

    def test_is_system_healthy_all_healthy(self):
        hc = HealthChecker()
        hc.health_status = {
            "a": {"status": "healthy"},
            "b": {"status": "healthy"},
        }
        assert hc.is_system_healthy() is True

    def test_is_system_healthy_one_unhealthy(self):
        hc = HealthChecker()
        hc.health_status = {
            "a": {"status": "healthy"},
            "b": {"status": "unhealthy"},
        }
        assert hc.is_system_healthy() is False
