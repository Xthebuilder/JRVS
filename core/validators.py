"""
Shared input validation and sanitization utilities for JRVS.

This module provides:
  - sanitize_text()       — strip dangerous characters / injection patterns
  - validate_url()        — allow only http(s), block internal IPs
  - validate_email()      — lightweight RFC-ish email check
  - validate_session_id() — alphanumeric / UUID only
  - validate_iso_date()   — strict ISO-8601 datetime parsing
  - sanitize_filename()   — safe filename (no path traversal)
  - MAX constants         — shared size limits

Usage in Pydantic models:
    from core.validators import sanitize_text, MAX_MESSAGE_LEN
    from pydantic import field_validator

    class MyRequest(BaseModel):
        message: str = Field(..., max_length=MAX_MESSAGE_LEN)

        @field_validator("message")
        @classmethod
        def clean(cls, v):
            return sanitize_text(v)
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Size limits (importable by Pydantic models anywhere)
# ---------------------------------------------------------------------------

MAX_MESSAGE_LEN: int = 10_000          # chat messages
MAX_URL_LEN: int = 2_000               # URLs submitted for scraping
MAX_SESSION_ID_LEN: int = 128          # session identifiers
MAX_TITLE_LEN: int = 500               # event / doc titles
MAX_EMAIL_LEN: int = 320               # RFC 5321 practical max
MAX_CODE_LEN: int = 50_000             # code execution payloads
MAX_FILENAME_LEN: int = 255

# ---------------------------------------------------------------------------
# Dangerous-pattern regexes (compiled once)
# ---------------------------------------------------------------------------

# Null bytes / C0+C1 control characters  (keep \n \r \t)
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')

# Simplistic <script> / on-event / javascript: patterns — catch obvious XSS
_SCRIPT_TAG = re.compile(r'<\s*script[^>]*>.*?<\s*/\s*script\s*>', re.I | re.S)
_EVENT_HANDLER = re.compile(r'\bon\w+\s*=', re.I)
_JS_PROTOCOL = re.compile(r'javascript\s*:', re.I)

# SQL injection markers (not a WAF — just a best-effort safety net)
_SQL_MARKERS = re.compile(
    r"(?:--|;)\s*(?:DROP|ALTER|DELETE|INSERT|UPDATE|EXEC)\b"
    r"|\b(?:DROP|ALTER)\s+TABLE\b"
    r"|\bEXEC(?:UTE)?\s*\(",
    re.I,
)

# Internal / reserved IP patterns for SSRF protection
_BLOCKED_HOSTS = re.compile(
    r'^('
    r'localhost'
    r'|127\.\d+\.\d+\.\d+'
    r'|0\.0\.0\.0'
    r'|10\.\d+\.\d+\.\d+'
    r'|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+'
    r'|192\.168\.\d+\.\d+'
    r'|169\.254\.\d+\.\d+'
    r'|\[?::1\]?'
    r'|\[?fe80:'
    r'|\[?fd[0-9a-f]{2}:'
    r')$',
    re.I,
)

# Valid session-id: UUID-shaped or plain alphanumeric+dashes
_SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,128}$')

# Minimal email regex (not fully RFC 5322 — intentionally simple)
_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$'
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def sanitize_text(text: str, *, max_length: int = MAX_MESSAGE_LEN, strip: bool = True) -> str:
    """Return *text* with dangerous content stripped.

    - Removes null bytes and non-printable control characters
    - Strips <script> tags and ``on*=`` event handlers
    - Strips ``javascript:`` protocol prefixes
    - Removes obvious SQL injection markers
    - Normalises Unicode to NFC
    - Optionally trims whitespace and enforces *max_length*
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str, got {type(text).__name__}")

    # Normalise Unicode (prevents homoglyph-based bypass)
    text = unicodedata.normalize("NFC", text)

    # Strip control characters (preserve \n \r \t)
    text = _CONTROL_CHARS.sub('', text)

    # Remove <script>...</script> blocks
    text = _SCRIPT_TAG.sub('', text)

    # Remove on-event handlers (onerror=, onclick=, etc.)
    text = _EVENT_HANDLER.sub('', text)

    # Remove javascript: protocol
    text = _JS_PROTOCOL.sub('', text)

    # Remove obvious SQL injection fragments
    text = _SQL_MARKERS.sub('', text)

    if strip:
        text = text.strip()

    if max_length and len(text) > max_length:
        text = text[:max_length]

    return text


def validate_url(url: str) -> str:
    """Validate and return *url*, or raise ``ValueError``.

    Rules:
    - Must be http or https
    - Must have a valid netloc
    - Must not point to internal / reserved IP ranges (SSRF protection)
    - Length ≤ MAX_URL_LEN
    """
    if not isinstance(url, str):
        raise TypeError(f"Expected str, got {type(url).__name__}")

    url = url.strip()
    if len(url) > MAX_URL_LEN:
        raise ValueError(f"URL exceeds maximum length ({MAX_URL_LEN})")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")

    if not parsed.netloc:
        raise ValueError("URL has no host")

    hostname = parsed.hostname or ""
    if _BLOCKED_HOSTS.match(hostname):
        raise ValueError("Internal / reserved addresses are not allowed")

    return url


def validate_email(email: str) -> str:
    """Basic email format check. Raises ``ValueError`` on failure."""
    if not isinstance(email, str):
        raise TypeError(f"Expected str, got {type(email).__name__}")
    email = email.strip()
    if len(email) > MAX_EMAIL_LEN:
        raise ValueError(f"Email exceeds maximum length ({MAX_EMAIL_LEN})")
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email address format")
    return email


def validate_session_id(sid: str) -> str:
    """Ensure *sid* is a safe alphanumeric / UUID string."""
    if not isinstance(sid, str):
        raise TypeError(f"Expected str, got {type(sid).__name__}")
    sid = sid.strip()
    if not _SESSION_ID_RE.match(sid):
        raise ValueError("Session ID must be alphanumeric, dashes, or underscores (max 128 chars)")
    return sid


def validate_iso_date(value: str) -> datetime:
    """Parse an ISO-8601 datetime string and return a ``datetime`` object.

    Accepts formats like ``2025-11-10T14:30:00`` or ``2025-11-10 14:30``.
    Raises ``ValueError`` on bad input.
    """
    if not isinstance(value, str):
        raise TypeError(f"Expected str, got {type(value).__name__}")
    value = value.strip()
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid ISO date: {value!r}") from exc


def sanitize_filename(name: str) -> str:
    """Return a safe filename string — no path separators or traversal.

    Raises ``ValueError`` if the result is empty or starts with a dot.
    """
    if not isinstance(name, str):
        raise TypeError(f"Expected str, got {type(name).__name__}")

    # Strip path components
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # Remove null bytes and control chars
    name = _CONTROL_CHARS.sub('', name)
    name = name.strip()

    if not name or name.startswith('.'):
        raise ValueError("Filename must not be empty or start with a dot")

    if len(name) > MAX_FILENAME_LEN:
        raise ValueError(f"Filename exceeds {MAX_FILENAME_LEN} characters")

    return name
