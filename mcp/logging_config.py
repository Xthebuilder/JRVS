"""
Structured logging configuration for JRVS MCP Server

Provides JSON-formatted logging with request tracking, performance metrics,
and error aggregation.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path
import traceback


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for better machine readability"""

    def __init__(self, service_name: str = "jrvs-mcp"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "service": self.service_name,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }

        # Add custom fields from extra
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with colors"""

    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format with colors for console"""
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']

        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')

        # Build message
        msg = f"{color}[{timestamp}] {record.levelname:8}{reset} {record.name}: {record.getMessage()}"

        # Add exception if present
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"

        return msg


class LoggerAdapter(logging.LoggerAdapter):
    """Adapter to add context to log messages"""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Add context information to log records"""
        extra = kwargs.get('extra', {})

        # Merge context with extra
        if self.extra:
            extra = {**self.extra, **extra}

        kwargs['extra'] = {'extra_data': extra}
        return msg, kwargs


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    json_logs: bool = True,
    service_name: str = "jrvs-mcp"
) -> logging.Logger:
    """
    Setup logging configuration

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for logs
        json_logs: Use JSON formatting for file logs
        service_name: Service name for log identification

    Returns:
        Configured root logger
    """

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler (human-readable)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler (JSON)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)

        if json_logs:
            file_handler.setFormatter(JSONFormatter(service_name))
        else:
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )

        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str, **context) -> LoggerAdapter:
    """
    Get a logger with context

    Args:
        name: Logger name
        **context: Context to add to all log messages

    Returns:
        Logger adapter with context
    """
    logger = logging.getLogger(name)
    return LoggerAdapter(logger, context)


# Request tracking utilities
class RequestContext:
    """Track request context for logging"""

    def __init__(self, request_id: str, tool_name: str, client_id: str = None):
        self.request_id = request_id
        self.tool_name = tool_name
        self.client_id = client_id
        self.start_time = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "client_id": self.client_id,
            "start_time": self.start_time.isoformat() + "Z"
        }

    def log_completion(self, logger: logging.Logger, success: bool, error: str = None):
        """Log request completion"""
        duration_ms = (datetime.utcnow() - self.start_time).total_seconds() * 1000

        log_data = {
            **self.to_dict(),
            "success": success,
            "duration_ms": round(duration_ms, 2),
        }

        if error:
            log_data["error"] = error

        if success:
            logger.info(
                f"Request completed: {self.tool_name}",
                extra=log_data
            )
        else:
            logger.error(
                f"Request failed: {self.tool_name}",
                extra=log_data
            )
