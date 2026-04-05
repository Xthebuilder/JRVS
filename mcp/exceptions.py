"""
Custom exceptions for JRVS MCP Server

Provides a hierarchical exception system for better error handling and debugging.
"""


class JRVSMCPException(Exception):
    """Base exception for all JRVS MCP errors"""

    def __init__(self, message: str, details: dict = None, recoverable: bool = False):
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)

    def to_dict(self):
        """Convert exception to dictionary for JSON serialization"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable
        }


# Component-specific exceptions
class OllamaException(JRVSMCPException):
    """Exceptions related to Ollama operations"""
    pass


class OllamaConnectionError(OllamaException):
    """Failed to connect to Ollama service"""
    def __init__(self, url: str, original_error: Exception = None):
        super().__init__(
            f"Cannot connect to Ollama at {url}",
            details={"url": url, "original_error": str(original_error)},
            recoverable=True
        )


class OllamaModelNotFoundError(OllamaException):
    """Requested model not available"""
    def __init__(self, model_name: str):
        super().__init__(
            f"Model '{model_name}' not found",
            details={"model": model_name},
            recoverable=False
        )


class OllamaGenerationError(OllamaException):
    """Error during text generation"""
    def __init__(self, message: str, model: str):
        super().__init__(
            f"Generation failed: {message}",
            details={"model": model},
            recoverable=True
        )


class RAGException(JRVSMCPException):
    """Exceptions related to RAG operations"""
    pass


class VectorStoreError(RAGException):
    """Vector store operation failed"""
    def __init__(self, operation: str, original_error: Exception = None):
        super().__init__(
            f"Vector store {operation} failed",
            details={"operation": operation, "original_error": str(original_error)},
            recoverable=True
        )


class EmbeddingError(RAGException):
    """Embedding generation failed"""
    def __init__(self, text_length: int, original_error: Exception = None):
        super().__init__(
            f"Failed to generate embeddings",
            details={"text_length": text_length, "original_error": str(original_error)},
            recoverable=True
        )


class DocumentNotFoundError(RAGException):
    """Document not found in database"""
    def __init__(self, doc_id: int):
        super().__init__(
            f"Document {doc_id} not found",
            details={"document_id": doc_id},
            recoverable=False
        )


class CalendarException(JRVSMCPException):
    """Exceptions related to calendar operations"""
    pass


class EventNotFoundError(CalendarException):
    """Event not found"""
    def __init__(self, event_id: int):
        super().__init__(
            f"Event {event_id} not found",
            details={"event_id": event_id},
            recoverable=False
        )


class InvalidEventDateError(CalendarException):
    """Invalid event date format"""
    def __init__(self, date_str: str, expected_format: str):
        super().__init__(
            f"Invalid date format: {date_str}",
            details={"date": date_str, "expected_format": expected_format},
            recoverable=False
        )


class ScraperException(JRVSMCPException):
    """Exceptions related to web scraping"""
    pass


class URLFetchError(ScraperException):
    """Failed to fetch URL"""
    def __init__(self, url: str, status_code: int = None, original_error: Exception = None):
        super().__init__(
            f"Failed to fetch {url}",
            details={"url": url, "status_code": status_code, "original_error": str(original_error)},
            recoverable=True
        )


class ContentParseError(ScraperException):
    """Failed to parse content"""
    def __init__(self, url: str, original_error: Exception = None):
        super().__init__(
            f"Failed to parse content from {url}",
            details={"url": url, "original_error": str(original_error)},
            recoverable=False
        )


# Resource management exceptions
class ResourceException(JRVSMCPException):
    """Exceptions related to resource management"""
    pass


class RateLimitExceededError(ResourceException):
    """Rate limit exceeded"""
    def __init__(self, limit: int, window: str, client_id: str = None):
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window}",
            details={"limit": limit, "window": window, "client_id": client_id},
            recoverable=True
        )


class ResourceExhaustedError(ResourceException):
    """System resources exhausted"""
    def __init__(self, resource_type: str, current: float, limit: float):
        super().__init__(
            f"{resource_type} exhausted: {current}/{limit}",
            details={"resource_type": resource_type, "current": current, "limit": limit},
            recoverable=True
        )


class CacheException(JRVSMCPException):
    """Exceptions related to caching"""
    pass


class CacheConnectionError(CacheException):
    """Failed to connect to cache"""
    def __init__(self, cache_backend: str, original_error: Exception = None):
        super().__init__(
            f"Cannot connect to cache backend: {cache_backend}",
            details={"backend": cache_backend, "original_error": str(original_error)},
            recoverable=True
        )


# Authentication exceptions
class AuthenticationException(JRVSMCPException):
    """Exceptions related to authentication"""
    pass


class InvalidAPIKeyError(AuthenticationException):
    """Invalid API key provided"""
    def __init__(self, key_preview: str = None):
        super().__init__(
            "Invalid or expired API key",
            details={"key_preview": key_preview},
            recoverable=False
        )


class UnauthorizedError(AuthenticationException):
    """Insufficient permissions"""
    def __init__(self, required_permission: str):
        super().__init__(
            f"Unauthorized: requires '{required_permission}' permission",
            details={"required_permission": required_permission},
            recoverable=False
        )


# Configuration exceptions
class ConfigurationException(JRVSMCPException):
    """Exceptions related to configuration"""
    pass


class InvalidConfigError(ConfigurationException):
    """Invalid configuration"""
    def __init__(self, field: str, reason: str):
        super().__init__(
            f"Invalid configuration for '{field}': {reason}",
            details={"field": field, "reason": reason},
            recoverable=False
        )


class MissingConfigError(ConfigurationException):
    """Required configuration missing"""
    def __init__(self, field: str):
        super().__init__(
            f"Required configuration missing: {field}",
            details={"field": field},
            recoverable=False
        )
