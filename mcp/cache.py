"""
Caching layer for JRVS MCP Server

Provides in-memory caching with TTL support for improved performance.
Reduces load on Ollama, RAG, and other compute-intensive operations.
"""

import asyncio
import time
import hashlib
import json
from typing import Any, Optional, Dict, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import OrderedDict
from threading import Lock
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    key: str
    value: Any
    created_at: datetime
    expires_at: datetime
    hit_count: int = 0
    last_accessed: Optional[datetime] = None


class LRUCache:
    """
    Thread-safe LRU cache with TTL support

    Features:
    - Automatic expiration based on TTL
    - LRU eviction when max size reached
    - Hit/miss statistics
    - Background cleanup of expired entries
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()

        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self.misses += 1
                return None

            # Check if expired
            if datetime.utcnow() > entry.expires_at:
                self._cache.pop(key)
                self.misses += 1
                return None

            # Update stats and move to end (most recently used)
            entry.hit_count += 1
            entry.last_accessed = datetime.utcnow()
            self.hits += 1

            # Move to end (LRU)
            self._cache.move_to_end(key)

            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache"""
        with self._lock:
            ttl = ttl or self.default_ttl

            entry = CacheEntry(
                key=key,
                value=value,
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(seconds=ttl)
            )

            # If key exists, update it
            if key in self._cache:
                self._cache[key] = entry
                self._cache.move_to_end(key)
            else:
                # Add new entry
                self._cache[key] = entry

                # Evict if over max size
                if len(self._cache) > self.max_size:
                    self._cache.popitem(last=False)  # Remove oldest
                    self.evictions += 1

    def delete(self, key: str) -> bool:
        """Delete entry from cache"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self):
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0

    def cleanup_expired(self) -> int:
        """Remove expired entries, return count removed"""
        with self._lock:
            now = datetime.utcnow()
            expired_keys = [
                key for key, entry in self._cache.items()
                if now > entry.expires_at
            ]

            for key in expired_keys:
                del self._cache[key]

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(hit_rate, 2),
                "evictions": self.evictions,
            }

    def get_entry_info(self, key: str) -> Optional[Dict[str, Any]]:
        """Get metadata about a cache entry"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            return {
                "key": entry.key,
                "created_at": entry.created_at.isoformat(),
                "expires_at": entry.expires_at.isoformat(),
                "hit_count": entry.hit_count,
                "last_accessed": entry.last_accessed.isoformat() if entry.last_accessed else None,
            }


class CacheManager:
    """Manage multiple cache instances for different purposes"""

    def __init__(self):
        # Different caches for different use cases
        self.rag_cache = LRUCache(max_size=500, default_ttl=600)  # 10 min
        self.ollama_cache = LRUCache(max_size=200, default_ttl=300)  # 5 min
        self.scraper_cache = LRUCache(max_size=100, default_ttl=1800)  # 30 min
        self.general_cache = LRUCache(max_size=300, default_ttl=300)  # 5 min

    def get_cache(self, cache_type: str) -> LRUCache:
        """Get specific cache by type"""
        caches = {
            "rag": self.rag_cache,
            "ollama": self.ollama_cache,
            "scraper": self.scraper_cache,
            "general": self.general_cache,
        }
        return caches.get(cache_type, self.general_cache)

    def cleanup_all(self) -> Dict[str, int]:
        """Cleanup all caches, return counts"""
        return {
            "rag": self.rag_cache.cleanup_expired(),
            "ollama": self.ollama_cache.cleanup_expired(),
            "scraper": self.scraper_cache.cleanup_expired(),
            "general": self.general_cache.cleanup_expired(),
        }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all caches"""
        return {
            "rag": self.rag_cache.get_stats(),
            "ollama": self.ollama_cache.get_stats(),
            "scraper": self.scraper_cache.get_stats(),
            "general": self.general_cache.get_stats(),
        }

    def clear_all(self):
        """Clear all caches"""
        self.rag_cache.clear()
        self.ollama_cache.clear()
        self.scraper_cache.clear()
        self.general_cache.clear()


def cache_key(*args, **kwargs) -> str:
    """Generate cache key from arguments"""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = ":".join(key_parts)

    # Hash long keys
    if len(key_str) > 200:
        return hashlib.md5(key_str.encode()).hexdigest()

    return key_str


def cached(cache_type: str = "general", ttl: Optional[int] = None):
    """
    Decorator to cache function results

    Args:
        cache_type: Type of cache to use (rag, ollama, scraper, general)
        ttl: Time to live in seconds (None = use cache default)
    """
    def decorator(func: Callable):
        async def async_wrapper(*args, **kwargs):
            # Generate cache key
            key = f"{func.__name__}:{cache_key(*args, **kwargs)}"

            # Try to get from cache
            cache = cache_manager.get_cache(cache_type)
            cached_value = cache.get(key)

            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value

            # Execute function
            logger.debug(f"Cache miss for {func.__name__}")
            result = await func(*args, **kwargs)

            # Store in cache
            cache.set(key, result, ttl)

            return result

        def sync_wrapper(*args, **kwargs):
            # Generate cache key
            key = f"{func.__name__}:{cache_key(*args, **kwargs)}"

            # Try to get from cache
            cache = cache_manager.get_cache(cache_type)
            cached_value = cache.get(key)

            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value

            # Execute function
            logger.debug(f"Cache miss for {func.__name__}")
            result = func(*args, **kwargs)

            # Store in cache
            cache.set(key, result, ttl)

            return result

        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# Global cache manager
cache_manager = CacheManager()


async def cache_cleanup_task(interval_seconds: int = 60):
    """Background task to cleanup expired cache entries"""
    while True:
        try:
            removed = cache_manager.cleanup_all()
            total = sum(removed.values())

            if total > 0:
                logger.info(f"Cleaned up {total} expired cache entries", extra=removed)

            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
            await asyncio.sleep(interval_seconds)
