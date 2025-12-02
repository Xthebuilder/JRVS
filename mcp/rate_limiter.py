"""
Rate limiting and resource management for JRVS MCP Server

Implements token bucket algorithm for rate limiting and
resource quota management to prevent abuse and ensure fair usage.
"""

import time
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock
import logging

from .exceptions import RateLimitExceededError, ResourceExhaustedError

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket for rate limiting"""
    capacity: int
    refill_rate: float  # tokens per second
    tokens: float
    last_refill: float

    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket

        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        self._refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True

        return False

    def _refill(self):
        """Refill tokens based on time elapsed"""
        now = time.time()
        elapsed = now - self.last_refill

        # Add tokens based on time elapsed
        self.tokens = min(
            self.capacity,
            self.tokens + (elapsed * self.refill_rate)
        )
        self.last_refill = now

    def get_wait_time(self, tokens: int = 1) -> float:
        """Get time to wait until tokens are available"""
        self._refill()

        if self.tokens >= tokens:
            return 0.0

        tokens_needed = tokens - self.tokens
        return tokens_needed / self.refill_rate


class RateLimiter:
    """
    Rate limiter using token bucket algorithm

    Supports per-client rate limiting with configurable limits
    """

    def __init__(
        self,
        default_rate: int = 60,  # requests per minute
        default_burst: int = 10,  # burst capacity
    ):
        self.default_rate = default_rate
        self.default_burst = default_burst
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = Lock()

        # Custom limits per client
        self._custom_limits: Dict[str, tuple] = {}  # client_id -> (rate, burst)

    def set_custom_limit(self, client_id: str, rate: int, burst: int):
        """Set custom rate limit for a client"""
        with self._lock:
            self._custom_limits[client_id] = (rate, burst)

            # Reset bucket if exists
            if client_id in self._buckets:
                del self._buckets[client_id]

    def check_rate_limit(self, client_id: str, tokens: int = 1) -> bool:
        """
        Check if request is within rate limit

        Args:
            client_id: Client identifier
            tokens: Number of tokens to consume

        Returns:
            True if within limit, raises RateLimitExceededError otherwise
        """
        with self._lock:
            bucket = self._get_or_create_bucket(client_id)

            if bucket.consume(tokens):
                return True

            # Rate limit exceeded
            wait_time = bucket.get_wait_time(tokens)

            raise RateLimitExceededError(
                limit=self._get_rate(client_id),
                window="minute",
                client_id=client_id
            )

    async def wait_for_token(self, client_id: str, tokens: int = 1):
        """
        Wait until tokens are available (async)

        Args:
            client_id: Client identifier
            tokens: Number of tokens needed
        """
        while True:
            with self._lock:
                bucket = self._get_or_create_bucket(client_id)

                if bucket.consume(tokens):
                    return

                wait_time = bucket.get_wait_time(tokens)

            # Wait outside lock
            await asyncio.sleep(min(wait_time, 1.0))  # Check at least every second

    def _get_or_create_bucket(self, client_id: str) -> TokenBucket:
        """Get or create token bucket for client"""
        if client_id not in self._buckets:
            rate, burst = self._get_limits(client_id)

            self._buckets[client_id] = TokenBucket(
                capacity=burst,
                refill_rate=rate / 60.0,  # per second
                tokens=burst,  # Start with full bucket
                last_refill=time.time()
            )

        return self._buckets[client_id]

    def _get_limits(self, client_id: str) -> tuple:
        """Get rate and burst limits for client"""
        if client_id in self._custom_limits:
            return self._custom_limits[client_id]
        return (self.default_rate, self.default_burst)

    def _get_rate(self, client_id: str) -> int:
        """Get rate limit for client"""
        return self._get_limits(client_id)[0]

    def get_remaining_tokens(self, client_id: str) -> int:
        """Get remaining tokens for client"""
        with self._lock:
            bucket = self._get_or_create_bucket(client_id)
            bucket._refill()
            return int(bucket.tokens)

    def get_stats(self) -> Dict[str, any]:
        """Get rate limiter statistics"""
        with self._lock:
            return {
                "total_clients": len(self._buckets),
                "default_rate": self.default_rate,
                "default_burst": self.default_burst,
                "custom_limits": len(self._custom_limits),
            }


class ResourceManager:
    """
    Manage system resource quotas

    Tracks and limits resource usage like memory, concurrent requests,
    and computation time.
    """

    def __init__(
        self,
        max_memory_mb: int = 2048,
        max_concurrent_requests: int = 100,
        max_request_duration_seconds: int = 300,
    ):
        self.max_memory_mb = max_memory_mb
        self.max_concurrent_requests = max_concurrent_requests
        self.max_request_duration_seconds = max_request_duration_seconds

        self._current_requests = 0
        self._request_start_times: Dict[str, datetime] = {}
        self._lock = Lock()

    def acquire_request_slot(self, request_id: str) -> bool:
        """
        Acquire a request slot

        Returns:
            True if slot acquired, raises ResourceExhaustedError otherwise
        """
        with self._lock:
            if self._current_requests >= self.max_concurrent_requests:
                raise ResourceExhaustedError(
                    resource_type="concurrent_requests",
                    current=self._current_requests,
                    limit=self.max_concurrent_requests
                )

            self._current_requests += 1
            self._request_start_times[request_id] = datetime.utcnow()
            return True

    def release_request_slot(self, request_id: str):
        """Release a request slot"""
        with self._lock:
            if self._current_requests > 0:
                self._current_requests -= 1

            self._request_start_times.pop(request_id, None)

    def check_request_duration(self, request_id: str):
        """
        Check if request has exceeded max duration

        Raises:
            ResourceExhaustedError if duration exceeded
        """
        with self._lock:
            start_time = self._request_start_times.get(request_id)

            if start_time is None:
                return

            duration = (datetime.utcnow() - start_time).total_seconds()

            if duration > self.max_request_duration_seconds:
                raise ResourceExhaustedError(
                    resource_type="request_duration",
                    current=duration,
                    limit=self.max_request_duration_seconds
                )

    def get_stats(self) -> Dict[str, any]:
        """Get resource usage statistics"""
        with self._lock:
            # Calculate request durations
            durations = []
            now = datetime.utcnow()

            for start_time in self._request_start_times.values():
                duration = (now - start_time).total_seconds()
                durations.append(duration)

            return {
                "concurrent_requests": {
                    "current": self._current_requests,
                    "max": self.max_concurrent_requests,
                    "utilization": round(self._current_requests / self.max_concurrent_requests * 100, 2)
                },
                "request_durations": {
                    "count": len(durations),
                    "avg_seconds": round(sum(durations) / len(durations), 2) if durations else 0,
                    "max_seconds": round(max(durations), 2) if durations else 0,
                }
            }


class QuotaManager:
    """
    Manage per-client quotas

    Track and enforce quotas for different resources per client
    """

    def __init__(self):
        # client_id -> resource_type -> usage
        self._usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # client_id -> resource_type -> limit
        self._limits: Dict[str, Dict[str, int]] = defaultdict(dict)

        self._lock = Lock()

        # Reset tracking
        self._last_reset: Dict[str, datetime] = defaultdict(lambda: datetime.utcnow())
        self._reset_interval = timedelta(hours=1)  # Reset hourly

    def set_quota(self, client_id: str, resource_type: str, limit: int):
        """Set quota limit for client and resource type"""
        with self._lock:
            self._limits[client_id][resource_type] = limit

    def consume(self, client_id: str, resource_type: str, amount: int = 1) -> bool:
        """
        Consume quota

        Returns:
            True if quota consumed, raises ResourceExhaustedError otherwise
        """
        with self._lock:
            self._check_reset(client_id)

            # Check if limit is set
            if resource_type not in self._limits.get(client_id, {}):
                # No limit set, allow
                self._usage[client_id][resource_type] += amount
                return True

            limit = self._limits[client_id][resource_type]
            current = self._usage[client_id][resource_type]

            if current + amount > limit:
                raise ResourceExhaustedError(
                    resource_type=f"quota_{resource_type}",
                    current=current,
                    limit=limit
                )

            self._usage[client_id][resource_type] += amount
            return True

    def get_usage(self, client_id: str, resource_type: str) -> int:
        """Get current usage for client and resource"""
        with self._lock:
            self._check_reset(client_id)
            return self._usage[client_id][resource_type]

    def get_remaining(self, client_id: str, resource_type: str) -> Optional[int]:
        """Get remaining quota for client and resource"""
        with self._lock:
            self._check_reset(client_id)

            if resource_type not in self._limits.get(client_id, {}):
                return None  # No limit

            limit = self._limits[client_id][resource_type]
            current = self._usage[client_id][resource_type]

            return max(0, limit - current)

    def _check_reset(self, client_id: str):
        """Check if quota should be reset"""
        now = datetime.utcnow()
        last_reset = self._last_reset[client_id]

        if now - last_reset > self._reset_interval:
            self._usage[client_id].clear()
            self._last_reset[client_id] = now

    def get_stats(self, client_id: str) -> Dict[str, any]:
        """Get quota statistics for client"""
        with self._lock:
            self._check_reset(client_id)

            stats = {}
            for resource_type in self._limits.get(client_id, {}):
                limit = self._limits[client_id][resource_type]
                current = self._usage[client_id][resource_type]

                stats[resource_type] = {
                    "current": current,
                    "limit": limit,
                    "remaining": max(0, limit - current),
                    "utilization": round(current / limit * 100, 2) if limit > 0 else 0
                }

            return stats


# Global instances
rate_limiter = RateLimiter(
    default_rate=60,   # 60 requests per minute
    default_burst=10   # burst of 10
)

resource_manager = ResourceManager(
    max_memory_mb=2048,
    max_concurrent_requests=100,
    max_request_duration_seconds=300
)

quota_manager = QuotaManager()
