"""
Logging configuration for JRVS.

Call setup_logging() once at application entry (main.py / api/server.py).
Every module then just does:

    import logging
    log = logging.getLogger(__name__)
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "data" / "logs"
_CONFIGURED = False


def setup_logging(level: str | None = None, log_to_file: bool = True) -> None:
    """
    Configure root logger.

    level     — override via LOG_LEVEL env var or pass directly ("DEBUG" / "INFO" / …)
    log_to_file — also write a rotating file log under data/logs/jrvs.log
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    raw_level = level or os.environ.get("LOG_LEVEL", "INFO")
    numeric_level = getattr(logging, raw_level.upper(), logging.INFO)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    handlers: list[logging.Handler] = []

    # Console handler — only WARNING+ by default so the CLI stays clean
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # File handler — captures DEBUG+ for post-mortem inspection
    if log_to_file:
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                _LOG_DIR / "jrvs.log",
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError:
            pass  # read-only filesystem — fall back to console only

    logging.basicConfig(level=numeric_level, handlers=handlers, force=True)

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "aiohttp", "urllib3", "faiss"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
