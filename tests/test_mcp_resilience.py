"""
Unit tests for mcp/resilience.py

Tests CircuitBreaker, retry decorator, timeout decorator,
Fallback, and BulkheadLimiter.
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.resilience import CircuitBreaker, CircuitState, Fallback, BulkheadLimiter, retry, timeout


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_success_keeps_closed(self):
        cb = CircuitBreaker()
        cb.call(lambda: 42)
        assert cb.state == CircuitState.CLOSED

    def test_call_returns_value(self):
        cb = CircuitBreaker()
        result = cb.call(lambda: "hello")
        assert result == "hello"

    def test_failures_open_circuit(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            with pytest.raises(Exception):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        cb = CircuitBreaker(failure_threshold=1)
        with pytest.raises(Exception):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            cb.call(lambda: "should not reach")

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("1")))
        cb.call(lambda: "ok")  # success
        assert cb.failure_count == 0

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == CircuitState.OPEN
        # recovery_timeout=0, so should immediately try to reset
        cb.last_failure_time = datetime.utcnow() - timedelta(seconds=1)
        # Next call should attempt half-open
        try:
            cb.call(lambda: "recovered")
        except Exception:
            pass
        # After successful call through half-open, should be closed
        cb.call(lambda: "ok")
        assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
class TestCircuitBreakerAsync:
    async def test_async_call_succeeds(self):
        cb = CircuitBreaker()

        async def good():
            return "result"

        result = await cb.call_async(good)
        assert result == "result"

    async def test_async_call_opens_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2)

        async def bad():
            raise ValueError("oops")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call_async(bad)

        assert cb.state == CircuitState.OPEN

    async def test_open_async_circuit_rejects(self):
        cb = CircuitBreaker(failure_threshold=1)

        async def bad():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await cb.call_async(bad)

        async def good():
            return "ok"

        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            await cb.call_async(good)


@pytest.mark.asyncio
class TestRetryDecorator:
    async def test_succeeds_on_first_try(self):
        calls = []

        @retry(max_attempts=3, delay=0.01)
        async def func():
            calls.append(1)
            return "done"

        result = await func()
        assert result == "done"
        assert len(calls) == 1

    async def test_retries_then_succeeds(self):
        calls = []

        @retry(max_attempts=3, delay=0.01)
        async def func():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("not yet")
            return "success"

        result = await func()
        assert result == "success"
        assert len(calls) == 3

    async def test_raises_after_all_attempts(self):
        @retry(max_attempts=3, delay=0.01)
        async def func():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            await func()

    async def test_on_retry_callback_called(self):
        retries = []

        @retry(max_attempts=3, delay=0.01, on_retry=lambda n, e: retries.append(n))
        async def func():
            raise ValueError("x")

        with pytest.raises(ValueError):
            await func()

        assert retries == [1, 2]  # Called on attempt 1 and 2, not on final

    async def test_only_catches_specified_exceptions(self):
        @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
        async def func():
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            await func()


class TestRetrySyncDecorator:
    def test_sync_retry_succeeds(self):
        calls = []

        @retry(max_attempts=3, delay=0.01)
        def func():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("retry me")
            return "ok"

        assert func() == "ok"
        assert len(calls) == 2


@pytest.mark.asyncio
class TestTimeoutDecorator:
    async def test_fast_function_completes(self):
        @timeout(seconds=5.0)
        async def fast():
            return "done"

        result = await fast()
        assert result == "done"

    async def test_slow_function_times_out(self):
        @timeout(seconds=0.05)
        async def slow():
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError):
            await slow()


@pytest.mark.asyncio
class TestFallback:
    async def test_primary_succeeds(self):
        async def primary():
            return "primary"

        async def fallback():
            return "fallback"

        fb = Fallback(primary, fallback)
        assert await fb.execute_async() == "primary"

    async def test_uses_fallback_on_failure(self):
        async def primary():
            raise RuntimeError("primary down")

        async def fallback():
            return "fallback result"

        fb = Fallback(primary, fallback)
        assert await fb.execute_async() == "fallback result"

    def test_sync_primary_succeeds(self):
        fb = Fallback(lambda: "primary", lambda: "fallback")
        assert fb.execute() == "primary"

    def test_sync_fallback_on_failure(self):
        fb = Fallback(lambda: (_ for _ in ()).throw(RuntimeError("fail")), lambda: "safe")
        assert fb.execute() == "safe"


@pytest.mark.asyncio
class TestBulkheadLimiter:
    async def test_executes_function(self):
        bh = BulkheadLimiter(max_concurrent=3)

        async def work():
            return "done"

        result = await bh.execute(work)
        assert result == "done"

    async def test_stats_shape(self):
        bh = BulkheadLimiter(max_concurrent=5)
        stats = bh.get_stats()
        assert stats["max_concurrent"] == 5
        assert stats["current_concurrent"] == 0
        assert stats["available"] == 5

    async def test_concurrent_tracking(self):
        bh = BulkheadLimiter(max_concurrent=5)
        peak = []

        async def work():
            peak.append(bh.current)
            await asyncio.sleep(0.01)

        await asyncio.gather(bh.execute(work), bh.execute(work), bh.execute(work))
        assert max(peak) <= 3
