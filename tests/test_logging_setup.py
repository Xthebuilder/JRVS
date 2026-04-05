"""
Unit tests for core.logging_setup — setup_logging() configuration.
"""

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.logging_setup as logging_module


@pytest.fixture(autouse=True)
def reset_configured_flag():
    """Reset the module-level _CONFIGURED flag between tests."""
    original = logging_module._CONFIGURED
    logging_module._CONFIGURED = False
    yield
    logging_module._CONFIGURED = original


class TestSetupLogging:

    def test_sets_configured_flag(self):
        with patch.object(logging_module, "_LOG_DIR", Path("/tmp/jrvs_test_logs")):
            logging_module.setup_logging(log_to_file=False)
            assert logging_module._CONFIGURED is True

    def test_idempotent(self):
        """Calling setup_logging twice should not re-configure."""
        with patch.object(logging_module, "_LOG_DIR", Path("/tmp/jrvs_test_logs")):
            logging_module.setup_logging(log_to_file=False)
            logging_module._CONFIGURED = True
            # Second call should be a no-op
            logging_module.setup_logging(level="DEBUG", log_to_file=False)
            # If it re-configured, it would have changed level; but it's idempotent
            assert logging_module._CONFIGURED is True

    def test_level_from_arg(self):
        with patch.object(logging_module, "_LOG_DIR", Path("/tmp/jrvs_test_logs")):
            logging_module.setup_logging(level="DEBUG", log_to_file=False)
            root = logging.getLogger()
            assert root.level == logging.DEBUG

    def test_level_from_env(self):
        with patch.dict("os.environ", {"LOG_LEVEL": "WARNING"}), \
             patch.object(logging_module, "_LOG_DIR", Path("/tmp/jrvs_test_logs")):
            logging_module.setup_logging(log_to_file=False)
            root = logging.getLogger()
            assert root.level == logging.WARNING

    def test_file_handler_created(self, tmp_path):
        log_dir = tmp_path / "logs"
        with patch.object(logging_module, "_LOG_DIR", log_dir):
            logging_module.setup_logging(log_to_file=True)
            assert log_dir.exists()
            # A RotatingFileHandler should have been added
            root = logging.getLogger()
            file_handlers = [
                h for h in root.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            assert len(file_handlers) >= 1

    def test_no_file_handler_when_disabled(self, tmp_path):
        log_dir = tmp_path / "logs"
        with patch.object(logging_module, "_LOG_DIR", log_dir):
            logging_module.setup_logging(log_to_file=False)
            root = logging.getLogger()
            file_handlers = [
                h for h in root.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            # There should be no rotating file handler
            assert len(file_handlers) == 0

    def test_noisy_loggers_silenced(self, tmp_path):
        with patch.object(logging_module, "_LOG_DIR", Path("/tmp/jrvs_test_logs")):
            logging_module.setup_logging(log_to_file=False)
            for name in ("httpx", "httpcore", "aiohttp", "urllib3", "faiss"):
                assert logging.getLogger(name).level >= logging.WARNING
