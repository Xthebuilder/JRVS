"""
Unit tests for mcp/cache.py

Tests LRUCache, CacheManager, and cache_key helper.
No external dependencies.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.cache import LRUCache, CacheManager, cache_key


class TestLRUCacheBasics:
    def test_set_and_get(self):
        c = LRUCache()
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_missing_key_returns_none(self):
        c = LRUCache()
        assert c.get("nope") is None

    def test_overwrite_key(self):
        c = LRUCache()
        c.set("k", "first")
        c.set("k", "second")
        assert c.get("k") == "second"

    def test_delete_existing(self):
        c = LRUCache()
        c.set("k", "v")
        assert c.delete("k") is True
        assert c.get("k") is None

    def test_delete_nonexistent(self):
        c = LRUCache()
        assert c.delete("ghost") is False

    def test_clear_removes_all(self):
        c = LRUCache()
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.get("a") is None
        assert c.get("b") is None

    def test_clear_resets_stats(self):
        c = LRUCache()
        c.set("k", "v")
        c.get("k")
        c.clear()
        stats = c.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_can_store_any_type(self):
        c = LRUCache()
        c.set("list", [1, 2, 3])
        c.set("dict", {"a": 1})
        c.set("none", None)
        assert c.get("list") == [1, 2, 3]
        assert c.get("dict") == {"a": 1}
        # None is stored but get returns None — indistinguishable from miss
        # (this is a known limitation of the design)


class TestLRUCacheTTL:
    def test_entry_expires(self):
        c = LRUCache(default_ttl=1)
        c.set("k", "v")
        time.sleep(1.05)
        assert c.get("k") is None

    def test_custom_ttl_per_entry(self):
        c = LRUCache(default_ttl=300)
        c.set("short", "v", ttl=1)
        time.sleep(1.05)
        assert c.get("short") is None

    def test_not_expired_yet(self):
        c = LRUCache(default_ttl=300)
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_cleanup_expired_returns_count(self):
        c = LRUCache(default_ttl=1)
        c.set("a", 1)
        c.set("b", 2)
        time.sleep(1.05)
        removed = c.cleanup_expired()
        assert removed == 2

    def test_cleanup_leaves_valid_entries(self):
        c = LRUCache(default_ttl=300)
        c.set("alive", "yes", ttl=300)
        c.set("dead", "no", ttl=1)
        time.sleep(1.05)
        c.cleanup_expired()
        assert c.get("alive") == "yes"


class TestLRUCacheEviction:
    def test_evicts_oldest_when_full(self):
        c = LRUCache(max_size=3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.set("d", 4)  # Should evict "a"
        assert c.get("a") is None
        assert c.get("d") == 4

    def test_eviction_counter_increments(self):
        c = LRUCache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        stats = c.get_stats()
        assert stats["evictions"] == 1


class TestLRUCacheStats:
    def test_hit_increments(self):
        c = LRUCache()
        c.set("k", "v")
        c.get("k")
        c.get("k")
        assert c.get_stats()["hits"] == 2

    def test_miss_increments(self):
        c = LRUCache()
        c.get("missing")
        assert c.get_stats()["misses"] == 1

    def test_hit_rate_calculation(self):
        c = LRUCache()
        c.set("k", "v")
        c.get("k")   # hit
        c.get("no")  # miss
        stats = c.get_stats()
        assert stats["hit_rate"] == 50.0

    def test_zero_hit_rate_when_no_requests(self):
        c = LRUCache()
        assert c.get_stats()["hit_rate"] == 0.0

    def test_size_reflects_entries(self):
        c = LRUCache()
        c.set("a", 1)
        c.set("b", 2)
        assert c.get_stats()["size"] == 2


class TestLRUCacheEntryInfo:
    def test_get_entry_info_existing(self):
        c = LRUCache()
        c.set("k", "v")
        info = c.get_entry_info("k")
        assert info is not None
        assert info["key"] == "k"
        assert "created_at" in info
        assert "expires_at" in info
        assert info["hit_count"] == 0

    def test_get_entry_info_missing(self):
        c = LRUCache()
        assert c.get_entry_info("ghost") is None

    def test_hit_count_in_entry_info(self):
        c = LRUCache()
        c.set("k", "v")
        c.get("k")
        c.get("k")
        info = c.get_entry_info("k")
        assert info["hit_count"] == 2


class TestCacheManager:
    def test_get_known_cache_types(self):
        mgr = CacheManager()
        for cache_type in ("rag", "ollama", "scraper", "general"):
            cache = mgr.get_cache(cache_type)
            assert isinstance(cache, LRUCache)

    def test_unknown_type_falls_back_to_general(self):
        mgr = CacheManager()
        cache = mgr.get_cache("nonexistent")
        assert cache is mgr.general_cache

    def test_cleanup_all_returns_counts(self):
        mgr = CacheManager()
        result = mgr.cleanup_all()
        assert set(result.keys()) == {"rag", "ollama", "scraper", "general"}

    def test_get_all_stats_shape(self):
        mgr = CacheManager()
        stats = mgr.get_all_stats()
        assert set(stats.keys()) == {"rag", "ollama", "scraper", "general"}
        for v in stats.values():
            assert "hits" in v
            assert "misses" in v

    def test_clear_all_empties_caches(self):
        mgr = CacheManager()
        mgr.rag_cache.set("x", 1)
        mgr.general_cache.set("y", 2)
        mgr.clear_all()
        assert mgr.rag_cache.get("x") is None
        assert mgr.general_cache.get("y") is None


class TestCacheKey:
    def test_simple_args(self):
        k = cache_key("a", "b")
        assert "a" in k and "b" in k

    def test_kwargs_included(self):
        k = cache_key(query="hello", limit=5)
        assert "query=hello" in k or "hello" in k

    def test_long_key_is_hashed(self):
        k = cache_key("x" * 300)
        assert len(k) == 32  # MD5 hex digest

    def test_same_args_same_key(self):
        assert cache_key("a", "b") == cache_key("a", "b")

    def test_different_args_different_key(self):
        assert cache_key("a") != cache_key("b")
