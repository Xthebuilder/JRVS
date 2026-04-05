"""
Unit tests for mcp/exceptions.py

Tests the full exception hierarchy — no external dependencies.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.exceptions import (
    JRVSMCPException,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaGenerationError,
    VectorStoreError,
    EmbeddingError,
    DocumentNotFoundError,
    EventNotFoundError,
    InvalidEventDateError,
    URLFetchError,
    ContentParseError,
    RateLimitExceededError,
    ResourceExhaustedError,
    CacheConnectionError,
    InvalidAPIKeyError,
    UnauthorizedError,
    InvalidConfigError,
    MissingConfigError,
    OllamaException,
    RAGException,
    CalendarException,
    ScraperException,
    ResourceException,
    CacheException,
    AuthenticationException,
    ConfigurationException,
)


class TestBaseException:
    def test_message_stored(self):
        ex = JRVSMCPException("oops")
        assert ex.message == "oops"
        assert str(ex) == "oops"

    def test_default_details_empty_dict(self):
        ex = JRVSMCPException("x")
        assert ex.details == {}

    def test_custom_details_stored(self):
        ex = JRVSMCPException("x", details={"key": "val"})
        assert ex.details["key"] == "val"

    def test_recoverable_false_by_default(self):
        ex = JRVSMCPException("x")
        assert ex.recoverable is False

    def test_recoverable_true(self):
        ex = JRVSMCPException("x", recoverable=True)
        assert ex.recoverable is True

    def test_to_dict_shape(self):
        ex = JRVSMCPException("msg", details={"a": 1}, recoverable=True)
        d = ex.to_dict()
        assert d["error_type"] == "JRVSMCPException"
        assert d["message"] == "msg"
        assert d["details"] == {"a": 1}
        assert d["recoverable"] is True

    def test_is_exception(self):
        ex = JRVSMCPException("x")
        assert isinstance(ex, Exception)


class TestOllamaExceptions:
    def test_connection_error_message(self):
        ex = OllamaConnectionError("http://localhost:11434")
        assert "localhost:11434" in ex.message
        assert ex.details["url"] == "http://localhost:11434"
        assert ex.recoverable is True

    def test_connection_error_with_original(self):
        orig = ConnectionRefusedError("refused")
        ex = OllamaConnectionError("http://x", orig)
        assert "refused" in ex.details["original_error"]

    def test_model_not_found(self):
        ex = OllamaModelNotFoundError("llama3")
        assert "llama3" in ex.message
        assert ex.details["model"] == "llama3"
        assert ex.recoverable is False

    def test_generation_error(self):
        ex = OllamaGenerationError("context too long", "llama3")
        assert "context too long" in ex.message
        assert ex.details["model"] == "llama3"
        assert ex.recoverable is True

    def test_ollama_exception_is_base(self):
        ex = OllamaConnectionError("http://x")
        assert isinstance(ex, OllamaException)
        assert isinstance(ex, JRVSMCPException)


class TestRAGExceptions:
    def test_vector_store_error(self):
        ex = VectorStoreError("search", RuntimeError("faiss fail"))
        assert "search" in ex.message
        assert ex.details["operation"] == "search"
        assert ex.recoverable is True

    def test_embedding_error(self):
        ex = EmbeddingError(512, ValueError("bad input"))
        assert ex.details["text_length"] == 512
        assert ex.recoverable is True

    def test_document_not_found(self):
        ex = DocumentNotFoundError(42)
        assert "42" in ex.message
        assert ex.details["document_id"] == 42
        assert ex.recoverable is False

    def test_rag_exception_hierarchy(self):
        ex = VectorStoreError("add")
        assert isinstance(ex, RAGException)
        assert isinstance(ex, JRVSMCPException)


class TestCalendarExceptions:
    def test_event_not_found(self):
        ex = EventNotFoundError(7)
        assert "7" in ex.message
        assert ex.details["event_id"] == 7
        assert ex.recoverable is False

    def test_invalid_event_date(self):
        ex = InvalidEventDateError("32-13-2025", "YYYY-MM-DD")
        assert "32-13-2025" in ex.message
        assert ex.details["expected_format"] == "YYYY-MM-DD"
        assert ex.recoverable is False

    def test_hierarchy(self):
        ex = EventNotFoundError(1)
        assert isinstance(ex, CalendarException)
        assert isinstance(ex, JRVSMCPException)


class TestScraperExceptions:
    def test_url_fetch_error(self):
        ex = URLFetchError("https://example.com", 404)
        assert "example.com" in ex.message
        assert ex.details["status_code"] == 404
        assert ex.recoverable is True

    def test_content_parse_error(self):
        ex = ContentParseError("https://example.com", Exception("bad html"))
        assert "example.com" in ex.message
        assert ex.recoverable is False

    def test_hierarchy(self):
        ex = URLFetchError("https://x.com")
        assert isinstance(ex, ScraperException)
        assert isinstance(ex, JRVSMCPException)


class TestResourceExceptions:
    def test_rate_limit_exceeded(self):
        ex = RateLimitExceededError(60, "minute", "client-1")
        assert "60" in ex.message
        assert ex.details["client_id"] == "client-1"
        assert ex.recoverable is True

    def test_resource_exhausted(self):
        ex = ResourceExhaustedError("memory", 2048, 2048)
        assert ex.details["resource_type"] == "memory"
        assert ex.details["current"] == 2048
        assert ex.recoverable is True

    def test_hierarchy(self):
        ex = RateLimitExceededError(10, "second")
        assert isinstance(ex, ResourceException)
        assert isinstance(ex, JRVSMCPException)


class TestCacheExceptions:
    def test_cache_connection_error(self):
        ex = CacheConnectionError("redis", ConnectionRefusedError("no redis"))
        assert "redis" in ex.message
        assert ex.recoverable is True

    def test_hierarchy(self):
        ex = CacheConnectionError("memcached")
        assert isinstance(ex, CacheException)
        assert isinstance(ex, JRVSMCPException)


class TestAuthExceptions:
    def test_invalid_api_key(self):
        ex = InvalidAPIKeyError("sk-***")
        assert "Invalid" in ex.message
        assert ex.details["key_preview"] == "sk-***"
        assert ex.recoverable is False

    def test_unauthorized(self):
        ex = UnauthorizedError("admin")
        assert "admin" in ex.message
        assert ex.recoverable is False

    def test_hierarchy(self):
        ex = InvalidAPIKeyError()
        assert isinstance(ex, AuthenticationException)
        assert isinstance(ex, JRVSMCPException)


class TestConfigExceptions:
    def test_invalid_config(self):
        ex = InvalidConfigError("timeout", "must be positive")
        assert "timeout" in ex.message
        assert ex.details["reason"] == "must be positive"
        assert ex.recoverable is False

    def test_missing_config(self):
        ex = MissingConfigError("OLLAMA_BASE_URL")
        assert "OLLAMA_BASE_URL" in ex.message
        assert ex.details["field"] == "OLLAMA_BASE_URL"
        assert ex.recoverable is False

    def test_hierarchy(self):
        ex = MissingConfigError("key")
        assert isinstance(ex, ConfigurationException)
        assert isinstance(ex, JRVSMCPException)
