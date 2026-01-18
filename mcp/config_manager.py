"""
Configuration management and validation for JRVS MCP Server

Provides schema validation, environment variable support,
and runtime configuration management.
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

from .exceptions import InvalidConfigError, MissingConfigError

logger = logging.getLogger(__name__)


class LogLevel(Enum):
    """Logging levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class OllamaConfig:
    """Ollama service configuration"""
    base_url: str = "http://localhost:11434"
    default_model: str = "deepseek-r1:14b"
    timeout_seconds: int = 300
    max_retries: int = 3


@dataclass
class DatabaseConfig:
    """Database configuration"""
    path: str = "data/jarvis.db"
    max_connections: int = 10
    timeout_seconds: int = 30


@dataclass
class RAGConfig:
    """RAG system configuration"""
    vector_index_path: str = "data/faiss_index"
    embedding_model: str = "all-MiniLM-L6-v2"
    max_context_length: int = 4000
    max_retrieved_chunks: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 50
    embedding_batch_size: int = 64


@dataclass
class CacheConfig:
    """Cache configuration"""
    enabled: bool = True
    max_size: int = 1000
    default_ttl_seconds: int = 300
    cleanup_interval_seconds: int = 60


@dataclass
class RateLimitConfig:
    """Rate limiting configuration"""
    enabled: bool = True
    default_rate_per_minute: int = 60
    default_burst: int = 10
    per_client_limits: Dict[str, Dict[str, int]] = field(default_factory=dict)


@dataclass
class ResourceConfig:
    """Resource management configuration"""
    max_memory_mb: int = 2048
    max_concurrent_requests: int = 100
    max_request_duration_seconds: int = 300


@dataclass
class AuthConfig:
    """Authentication configuration"""
    enabled: bool = False
    require_api_key: bool = False
    development_mode: bool = True  # Generate dev keys on startup


@dataclass
class MonitoringConfig:
    """Monitoring configuration"""
    enabled: bool = True
    metrics_interval_seconds: int = 30
    health_check_interval_seconds: int = 60


@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "localhost"
    port: int = 3000
    log_level: LogLevel = LogLevel.INFO
    log_file: Optional[str] = "logs/jrvs-mcp.log"
    json_logs: bool = True


@dataclass
class JRVSConfig:
    """Complete JRVS MCP Server configuration"""
    server: ServerConfig = field(default_factory=ServerConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    resource: ResourceConfig = field(default_factory=ResourceConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)

        # Convert enums to values
        if 'server' in data and 'log_level' in data['server']:
            if hasattr(data['server']['log_level'], 'value'):
                data['server']['log_level'] = data['server']['log_level'].value

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JRVSConfig':
        """Create from dictionary"""
        # Handle log_level enum conversion
        server_data = data.get('server', {})
        if 'log_level' in server_data and isinstance(server_data['log_level'], str):
            server_data['log_level'] = LogLevel[server_data['log_level']]

        return cls(
            server=ServerConfig(**server_data),
            ollama=OllamaConfig(**data.get('ollama', {})),
            database=DatabaseConfig(**data.get('database', {})),
            rag=RAGConfig(**data.get('rag', {})),
            cache=CacheConfig(**data.get('cache', {})),
            rate_limit=RateLimitConfig(**data.get('rate_limit', {})),
            resource=ResourceConfig(**data.get('resource', {})),
            auth=AuthConfig(**data.get('auth', {})),
            monitoring=MonitoringConfig(**data.get('monitoring', {}))
        )


class ConfigManager:
    """Manage configuration with validation and environment variable support"""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else None
        self.config: JRVSConfig = JRVSConfig()

    def load_config(self, config_path: Optional[str] = None) -> JRVSConfig:
        """
        Load configuration from file and environment variables

        Priority:
        1. Environment variables (highest)
        2. Config file
        3. Defaults (lowest)
        """
        if config_path:
            self.config_path = Path(config_path)

        # Start with defaults
        config_dict = {}

        # Load from file if exists
        if self.config_path and self.config_path.exists():
            logger.info(f"Loading config from {self.config_path}")
            with open(self.config_path, 'r') as f:
                config_dict = json.load(f)

        # Override with environment variables
        self._apply_env_overrides(config_dict)

        # Create config object
        self.config = JRVSConfig.from_dict(config_dict)

        # Validate
        self._validate_config()

        logger.info("Configuration loaded successfully")
        return self.config

    def save_config(self, path: Optional[str] = None):
        """Save current configuration to file"""
        save_path = Path(path) if path else self.config_path

        if save_path is None:
            raise ValueError("No config path specified")

        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, 'w') as f:
            json.dump(self.config.to_dict(), f, indent=2)

        logger.info(f"Configuration saved to {save_path}")

    def _apply_env_overrides(self, config_dict: Dict[str, Any]):
        """Apply environment variable overrides"""
        # Server config
        if os.getenv('JRVS_HOST'):
            config_dict.setdefault('server', {})['host'] = os.getenv('JRVS_HOST')
        if os.getenv('JRVS_PORT'):
            config_dict.setdefault('server', {})['port'] = int(os.getenv('JRVS_PORT'))
        if os.getenv('JRVS_LOG_LEVEL'):
            config_dict.setdefault('server', {})['log_level'] = os.getenv('JRVS_LOG_LEVEL')

        # Ollama config
        if os.getenv('OLLAMA_BASE_URL'):
            config_dict.setdefault('ollama', {})['base_url'] = os.getenv('OLLAMA_BASE_URL')
        if os.getenv('OLLAMA_DEFAULT_MODEL'):
            config_dict.setdefault('ollama', {})['default_model'] = os.getenv('OLLAMA_DEFAULT_MODEL')

        # Database config
        if os.getenv('JRVS_DB_PATH'):
            config_dict.setdefault('database', {})['path'] = os.getenv('JRVS_DB_PATH')

        # Auth config
        if os.getenv('JRVS_AUTH_ENABLED'):
            config_dict.setdefault('auth', {})['enabled'] = os.getenv('JRVS_AUTH_ENABLED').lower() == 'true'
        if os.getenv('JRVS_REQUIRE_API_KEY'):
            config_dict.setdefault('auth', {})['require_api_key'] = os.getenv('JRVS_REQUIRE_API_KEY').lower() == 'true'

        # Cache config
        if os.getenv('JRVS_CACHE_ENABLED'):
            config_dict.setdefault('cache', {})['enabled'] = os.getenv('JRVS_CACHE_ENABLED').lower() == 'true'

        # Rate limit config
        if os.getenv('JRVS_RATE_LIMIT_ENABLED'):
            config_dict.setdefault('rate_limit', {})['enabled'] = os.getenv('JRVS_RATE_LIMIT_ENABLED').lower() == 'true'
        if os.getenv('JRVS_RATE_LIMIT_PER_MINUTE'):
            config_dict.setdefault('rate_limit', {})['default_rate_per_minute'] = int(os.getenv('JRVS_RATE_LIMIT_PER_MINUTE'))

    def _validate_config(self):
        """Validate configuration values"""
        # Validate Ollama URL
        if not self.config.ollama.base_url.startswith('http'):
            raise InvalidConfigError(
                field='ollama.base_url',
                reason='Must be a valid HTTP/HTTPS URL'
            )

        # Validate paths
        if not self.config.database.path:
            raise MissingConfigError(field='database.path')

        # Validate resource limits
        if self.config.resource.max_concurrent_requests < 1:
            raise InvalidConfigError(
                field='resource.max_concurrent_requests',
                reason='Must be at least 1'
            )

        if self.config.resource.max_memory_mb < 512:
            raise InvalidConfigError(
                field='resource.max_memory_mb',
                reason='Must be at least 512 MB'
            )

        # Validate rate limits
        if self.config.rate_limit.default_rate_per_minute < 1:
            raise InvalidConfigError(
                field='rate_limit.default_rate_per_minute',
                reason='Must be at least 1'
            )

        # Validate RAG config
        if self.config.rag.chunk_size < 1:
            raise InvalidConfigError(
                field='rag.chunk_size',
                reason='Must be at least 1'
            )

        if self.config.rag.chunk_overlap >= self.config.rag.chunk_size:
            raise InvalidConfigError(
                field='rag.chunk_overlap',
                reason='Must be less than chunk_size'
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-notation key"""
        parts = key.split('.')
        value = self.config

        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            else:
                return default

        return value

    def get_summary(self) -> Dict[str, Any]:
        """Get configuration summary for logging"""
        return {
            "ollama_url": self.config.ollama.base_url,
            "default_model": self.config.ollama.default_model,
            "database_path": self.config.database.path,
            "cache_enabled": self.config.cache.enabled,
            "rate_limit_enabled": self.config.rate_limit.enabled,
            "auth_enabled": self.config.auth.enabled,
            "log_level": self.config.server.log_level.value,
        }


# Global config manager
config_manager = ConfigManager()


def create_default_config(output_path: str = "mcp/config.json"):
    """Create a default configuration file"""
    config = JRVSConfig()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)

    logger.info(f"Created default config at {output_path}")
    return output_path
