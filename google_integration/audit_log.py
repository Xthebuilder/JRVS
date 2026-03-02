"""Structured write-action audit logger for Google Workspace operations.

Every write action is logged TWICE:
  1. BEFORE execution (intent) — returns an audit_id
  2. AFTER execution (result)  — records success or error

Log file: data/logs/google_audit.log (rotating, 5 MB × 3 backups)
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def _build_audit_logger(log_dir: Path) -> logging.Logger:
    """Create a dedicated logger that writes JSON lines to google_audit.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "google_audit.log"

    logger = logging.getLogger("jrvs.google_audit")
    if logger.handlers:
        return logger  # already configured (e.g., imported twice)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # do NOT forward to root logger

    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


class AuditLog:
    """Write-action audit logger.

    Usage::

        audit_id = audit_log.log_write_intent("send_email", "alice@example.com", body)
        try:
            result = await gmail.send(...)
            audit_log.log_write_result(audit_id, success=True)
        except Exception as exc:
            audit_log.log_write_result(audit_id, success=False, error=str(exc))
            raise
    """

    def __init__(self, log_dir: Path):
        self._logger = _build_audit_logger(log_dir)
        self._session_id: Optional[str] = None

    def set_session_id(self, session_id: str) -> None:
        """Bind a session ID to all subsequent log entries."""
        self._session_id = session_id

    def log_write_intent(
        self,
        action: str,
        target: str,
        content: str = "",
    ) -> str:
        """Log a write *intent* (before execution). Returns a unique audit_id."""
        audit_id = str(uuid.uuid4())
        record = {
            "audit_id": audit_id,
            "phase": "intent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self._session_id,
            "action": action,
            "target": target,
            "content_preview": content[:200],
        }
        self._logger.info(json.dumps(record))
        return audit_id

    def log_write_result(
        self,
        audit_id: str,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """Log a write *result* (after execution)."""
        record = {
            "audit_id": audit_id,
            "phase": "result",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self._session_id,
            "success": success,
            "error": error,
        }
        self._logger.info(json.dumps(record))


# Module-level singleton — initialised lazily from client.py when DATA_DIR is known
audit_log: Optional[AuditLog] = None


def init_audit_log(log_dir: Path) -> AuditLog:
    """Initialise (or re-use) the module-level audit_log singleton."""
    global audit_log
    if audit_log is None:
        audit_log = AuditLog(log_dir)
    return audit_log
