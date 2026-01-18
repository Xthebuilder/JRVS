"""
Comprehensive test suite for JRVS Enhanced MCP Server

Tests all major components including:
- Error handling and resilience
- Caching
- Rate limiting
- Health checks
- Metrics collection
"""

import pytest
import asyncio
from datetime import datetime
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from mcp.exceptions import *
from mcp.cache import LRUCache, cache_manager
from mcp.rate_limiter import RateLimiter, ResourceManager
from mcp.resilience import CircuitBreaker, retry, timeout
from mcp.metrics import MetricsCollector, RequestMetrics
from mcp.health import HealthChecker, ComponentHealth, HealthStatus


# ============================================================================
# Exception Tests
# ============================================================================

def test_custom_exceptions():
    """Test custom exception hierarchy"""
    # Test base exception
    exc = JRVSMCPException("Test error", details={"foo": "bar"}, recoverable=True)
    assert exc.message == "Test error"
    assert exc.details["foo"] == "bar"
    assert exc.recoverable == True

    exc_dict = exc.to_dict()
    assert exc_dict["error_type"] == "JRVSMCPException"
    assert exc_dict["message"] == "Test error"
    assert exc_dict["recoverable"] == True


def test_specific_exceptions():
    """Test specific exception types"""
    # Ollama exceptions
    exc = OllamaConnectionError("http://localhost:11434")
    assert "localhost:11434" in exc.message
    assert exc.recoverable == True

    exc = OllamaModelNotFoundError("llama3")
    assert "llama3" in exc.message
    assert exc.recoverable == False

    # RAG exceptions
    exc = VectorStoreError("index", original_error=ValueError("test"))
    assert "index" in exc.message

    exc = DocumentNotFoundError(123)
    assert exc.details["document_id"] == 123

    # Rate limit exceptions
    exc = RateLimitExceededError(60, "minute", "client_1")
    assert exc.details["limit"] == 60
    assert exc.details["window"] == "minute"


# ============================================================================
# Cache Tests
# ============================================================================

def test_lru_cache_basic():
    """Test basic LRU cache operations"""
    cache = LRUCache(max_size=3, default_ttl=60)

    # Test set and get
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    # Test miss
    assert cache.get("nonexistent") is None

    # Test stats
    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1


def test_lru_cache_eviction():
    """Test LRU eviction policy"""
    cache = LRUCache(max_size=2, default_ttl=60)

    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")  # Should evict key1

    assert cache.get("key1") is None
    assert cache.get("key2") == "value2"
    assert cache.get("key3") == "value3"

    stats = cache.get_stats()
    assert stats["size"] == 2
    assert stats["evictions"] == 1


def test_cache_expiration():
    """Test TTL expiration"""
    cache = LRUCache(max_size=10, default_ttl=1)

    cache.set("key1", "value1", ttl=0)  # Expires immediately

    import time
    time.sleep(0.1)

    assert cache.get("key1") is None


def test_cache_manager():
    """Test cache manager with multiple caches"""
    manager = cache_manager

    # Test different cache types
    manager.rag_cache.set("test", "value")
    assert manager.rag_cache.get("test") == "value"

    # Test stats
    stats = manager.get_all_stats()
    assert "rag" in stats
    assert "ollama" in stats
    assert "scraper" in stats


# ============================================================================
# Rate Limiter Tests
# ============================================================================

def test_rate_limiter_basic():
    """Test basic rate limiting"""
    limiter = RateLimiter(default_rate=10, default_burst=5)

    # Should allow up to burst
    for i in range(5):
        assert limiter.check_rate_limit("client1") == True

    # Should exceed limit
    with pytest.raises(RateLimitExceededError):
        limiter.check_rate_limit("client1")


def test_rate_limiter_custom_limits():
    """Test custom client limits"""
    limiter = RateLimiter(default_rate=10, default_burst=2)

    # Set custom limit for client
    limiter.set_custom_limit("vip_client", rate=100, burst=20)

    # VIP should have higher limit
    for i in range(20):
        assert limiter.check_rate_limit("vip_client") == True

    # Regular client should hit limit faster
    limiter.check_rate_limit("regular")
    limiter.check_rate_limit("regular")

    with pytest.raises(RateLimitExceededError):
        limiter.check_rate_limit("regular")


@pytest.mark.asyncio
async def test_rate_limiter_async():
    """Test async rate limiting with wait"""
    limiter = RateLimiter(default_rate=60, default_burst=2)

    # Consume burst
    limiter.check_rate_limit("async_client")
    limiter.check_rate_limit("async_client")

    # Wait for token (should take ~1 second for 60/min rate)
    import time
    start = time.time()
    await limiter.wait_for_token("async_client")
    elapsed = time.time() - start

    assert elapsed >= 0.9  # At least close to 1 second


def test_resource_manager():
    """Test resource management"""
    manager = ResourceManager(
        max_concurrent_requests=2,
        max_request_duration_seconds=60
    )

    # Acquire slots
    manager.acquire_request_slot("req1")
    manager.acquire_request_slot("req2")

    # Should fail to acquire third
    with pytest.raises(ResourceExhaustedError):
        manager.acquire_request_slot("req3")

    # Release and retry
    manager.release_request_slot("req1")
    manager.acquire_request_slot("req3")  # Should succeed

    stats = manager.get_stats()
    assert stats["concurrent_requests"]["current"] == 2


# ============================================================================
# Resilience Tests
# ============================================================================

def test_circuit_breaker():
    """Test circuit breaker pattern"""
    circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=1)

    # Simulate failures
    def failing_func():
        raise Exception("Service down")

    for i in range(3):
        try:
            circuit.call(failing_func)
        except Exception:
            pass

    # Circuit should now be open
    with pytest.raises(Exception, match="Circuit breaker is OPEN"):
        circuit.call(failing_func)


@pytest.mark.asyncio
async def test_retry_decorator():
    """Test retry decorator"""
    call_count = 0

    @retry(max_attempts=3, delay=0.1, backoff=1.0)
    async def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Temporary error")
        return "success"

    result = await flaky_function()
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_timeout_decorator():
    """Test timeout decorator"""

    @timeout(0.5)
    async def slow_function():
        await asyncio.sleep(2)
        return "done"

    with pytest.raises(TimeoutError):
        await slow_function()


# ============================================================================
# Metrics Tests
# ============================================================================

def test_metrics_collector():
    """Test metrics collection"""
    collector = MetricsCollector(retention_seconds=3600)

    # Record some requests
    for i in range(10):
        metrics = RequestMetrics(
            tool_name="test_tool",
            success=i % 2 == 0,  # 50% success rate
            duration_ms=100 + i * 10,
            timestamp=datetime.utcnow(),
            error_type="TestError" if i % 2 != 0 else None
        )
        collector.record_request(metrics)

    # Check stats
    stats = collector.get_request_stats("test_tool")
    assert stats["total_requests"] == 10
    assert stats["successful_requests"] == 5
    assert stats["failed_requests"] == 5
    assert stats["success_rate"] == 50.0
    assert "performance" in stats


def test_metrics_tool_breakdown():
    """Test per-tool metrics breakdown"""
    collector = MetricsCollector()

    # Record requests for different tools
    tools = ["tool_a", "tool_b", "tool_c"]
    for tool in tools:
        for i in range(5):
            metrics = RequestMetrics(
                tool_name=tool,
                success=True,
                duration_ms=50,
                timestamp=datetime.utcnow()
            )
            collector.record_request(metrics)

    tool_stats = collector.get_tool_stats()
    assert len(tool_stats) == 3
    assert all(stats["total_requests"] == 5 for stats in tool_stats.values())


# ============================================================================
# Health Check Tests
# ============================================================================

@pytest.mark.asyncio
async def test_health_checker():
    """Test health check system"""
    checker = HealthChecker()

    # Register a healthy check
    async def healthy_check():
        return ComponentHealth(
            component="test_service",
            status=HealthStatus.HEALTHY,
            message="All good",
            last_check=datetime.utcnow()
        )

    # Register an unhealthy check
    async def unhealthy_check():
        return ComponentHealth(
            component="failing_service",
            status=HealthStatus.UNHEALTHY,
            message="Service down",
            last_check=datetime.utcnow()
        )

    checker.register_check("test_service", healthy_check)
    checker.register_check("failing_service", unhealthy_check)

    # Run checks
    await checker.check_all()

    # Check overall status
    overall = checker.get_overall_status()
    assert overall == HealthStatus.UNHEALTHY  # One failing component

    # Check report
    report = checker.get_health_report()
    assert report["status"] == "unhealthy"
    assert "test_service" in report["components"]
    assert "failing_service" in report["components"]


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_full_request_flow():
    """Test complete request flow with all middleware"""
    from mcp.rate_limiter import rate_limiter
    from mcp.metrics import metrics
    from mcp.cache import cache_manager

    # Reset state
    cache_manager.clear_all()

    # Define a test tool
    @retry(max_attempts=2, delay=0.1)
    @timeout(5)
    async def test_tool(query: str):
        # Check rate limit
        rate_limiter.check_rate_limit("test_client")

        # Simulate some work
        await asyncio.sleep(0.1)

        return f"Result for: {query}"

    # Execute tool
    result = await test_tool("test query")
    assert "Result for: test query" in result

    # Record metrics
    request_metrics = RequestMetrics(
        tool_name="test_tool",
        success=True,
        duration_ms=100,
        timestamp=datetime.utcnow()
    )
    metrics.record_request(request_metrics)

    # Verify metrics
    stats = metrics.get_request_stats("test_tool")
    assert stats["total_requests"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
