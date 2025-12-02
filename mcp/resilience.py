"""
Resilience patterns for JRVS MCP Server

Implements retry logic, circuit breakers, and fallback mechanisms
for robust error handling and service reliability.
"""

import asyncio
import time
from typing import Callable, Any, Optional, TypeVar, Union
from functools import wraps
from datetime import datetime, timedelta
from enum import Enum
import logging

from .exceptions import JRVSMCPException

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern implementation

    Prevents cascading failures by stopping requests to a failing service
    and allowing time for recovery.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception(f"Circuit breaker is OPEN. Service unavailable.")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    async def call_async(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute async function with circuit breaker protection"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception(f"Circuit breaker is OPEN. Service unavailable.")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call"""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )

    def _should_attempt_reset(self) -> bool:
        """Check if we should try to reset the circuit"""
        if self.last_failure_time is None:
            return False

        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    Retry decorator with exponential backoff

    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Backoff multiplier for exponential backoff
        exceptions: Tuple of exceptions to catch and retry
        on_retry: Optional callback function called on each retry
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"Failed after {max_attempts} attempts: {func.__name__}",
                            extra={"error": str(e)}
                        )
                        raise

                    if on_retry:
                        on_retry(attempt + 1, e)

                    logger.warning(
                        f"Retry {attempt + 1}/{max_attempts} for {func.__name__} after {current_delay}s",
                        extra={"error": str(e)}
                    )

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"Failed after {max_attempts} attempts: {func.__name__}",
                            extra={"error": str(e)}
                        )
                        raise

                    if on_retry:
                        on_retry(attempt + 1, e)

                    logger.warning(
                        f"Retry {attempt + 1}/{max_attempts} for {func.__name__} after {current_delay}s",
                        extra={"error": str(e)}
                    )

                    time.sleep(current_delay)
                    current_delay *= backoff

        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def timeout(seconds: float):
    """
    Timeout decorator for async functions

    Args:
        seconds: Timeout in seconds
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                logger.error(
                    f"Timeout after {seconds}s: {func.__name__}",
                )
                raise TimeoutError(f"{func.__name__} exceeded timeout of {seconds}s")

        return wrapper
    return decorator


class Fallback:
    """Fallback mechanism for graceful degradation"""

    def __init__(self, primary: Callable, fallback: Callable, exceptions: tuple = (Exception,)):
        self.primary = primary
        self.fallback = fallback
        self.exceptions = exceptions

    async def execute_async(self, *args, **kwargs) -> Any:
        """Execute with fallback for async functions"""
        try:
            return await self.primary(*args, **kwargs)
        except self.exceptions as e:
            logger.warning(
                f"Primary function failed, using fallback",
                extra={"error": str(e), "function": self.primary.__name__}
            )
            return await self.fallback(*args, **kwargs)

    def execute(self, *args, **kwargs) -> Any:
        """Execute with fallback for sync functions"""
        try:
            return self.primary(*args, **kwargs)
        except self.exceptions as e:
            logger.warning(
                f"Primary function failed, using fallback",
                extra={"error": str(e), "function": self.primary.__name__}
            )
            return self.fallback(*args, **kwargs)


class BulkheadLimiter:
    """
    Bulkhead pattern to limit concurrent operations

    Prevents resource exhaustion by limiting concurrent execution
    of resource-intensive operations.
    """

    def __init__(self, max_concurrent: int):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.current = 0

    async def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with concurrency limit"""
        async with self.semaphore:
            self.current += 1
            try:
                return await func(*args, **kwargs)
            finally:
                self.current -= 1

    def get_stats(self) -> dict:
        """Get current bulkhead stats"""
        return {
            "max_concurrent": self.max_concurrent,
            "current_concurrent": self.current,
            "available": self.max_concurrent - self.current
        }


# Global circuit breakers for different services
ollama_circuit = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=Exception
)

rag_circuit = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=30,
    expected_exception=Exception
)

scraper_circuit = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=120,
    expected_exception=Exception
)

# Bulkhead limiters
embedding_bulkhead = BulkheadLimiter(max_concurrent=5)
scraping_bulkhead = BulkheadLimiter(max_concurrent=3)
ollama_bulkhead = BulkheadLimiter(max_concurrent=10)
