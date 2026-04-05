"""
Unit tests for core.validators — input validation and sanitization.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.validators import (
    MAX_EMAIL_LEN,
    MAX_FILENAME_LEN,
    MAX_MESSAGE_LEN,
    MAX_SESSION_ID_LEN,
    MAX_URL_LEN,
    sanitize_filename,
    sanitize_text,
    validate_email,
    validate_iso_date,
    validate_session_id,
    validate_url,
)


# -------------------------------------------------------------------------
# sanitize_text
# -------------------------------------------------------------------------

class TestSanitizeText:

    def test_passthrough_clean_input(self):
        assert sanitize_text("Hello world") == "Hello world"

    def test_strips_whitespace_by_default(self):
        assert sanitize_text("  hello  ") == "hello"

    def test_preserves_newlines_and_tabs(self):
        text = "line1\nline2\ttab"
        assert sanitize_text(text) == text

    def test_removes_null_bytes(self):
        assert sanitize_text("he\x00llo") == "hello"

    def test_removes_control_characters(self):
        # \x01 (SOH) and \x7f (DEL) should be stripped
        assert sanitize_text("a\x01b\x7fc") == "abc"

    def test_removes_script_tags(self):
        assert sanitize_text('before<script>alert(1)</script>after') == "beforeafter"

    def test_removes_script_tags_case_insensitive(self):
        assert sanitize_text('<SCRIPT>x</SCRIPT>ok') == "ok"

    def test_removes_event_handlers(self):
        result = sanitize_text('onerror="alert(1)"')
        assert "onerror" not in result

    def test_removes_javascript_protocol(self):
        result = sanitize_text('javascript:alert(1)')
        assert "javascript:" not in result.lower()

    def test_removes_sql_injection_markers(self):
        result = sanitize_text("'; DROP TABLE users; --")
        assert "DROP TABLE" not in result

    def test_enforces_max_length(self):
        result = sanitize_text("a" * 20_000)
        assert len(result) <= MAX_MESSAGE_LEN

    def test_custom_max_length(self):
        result = sanitize_text("a" * 200, max_length=50)
        assert len(result) == 50

    def test_unicode_normalization(self):
        # é as combining e + accent (NFD) should normalise to NFC
        nfd = "e\u0301"  # NFD form
        result = sanitize_text(nfd)
        assert result == "\u00e9"  # NFC form

    def test_raises_on_non_string(self):
        with pytest.raises(TypeError):
            sanitize_text(123)

    def test_empty_string_returns_empty(self):
        assert sanitize_text("") == ""

    def test_whitespace_only_returns_empty(self):
        assert sanitize_text("   ") == ""

    def test_multiline_script_removal(self):
        text = '<script type="text/javascript">\nalert("xss")\n</script>safe'
        assert sanitize_text(text) == "safe"

    def test_no_strip_mode(self):
        assert sanitize_text("  hi  ", strip=False) == "  hi  "


# -------------------------------------------------------------------------
# validate_url
# -------------------------------------------------------------------------

class TestValidateUrl:

    def test_valid_https(self):
        assert validate_url("https://example.com") == "https://example.com"

    def test_valid_http(self):
        assert validate_url("http://example.com/path?q=1") == "http://example.com/path?q=1"

    def test_rejects_ftp(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_url("ftp://example.com")

    def test_rejects_javascript(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_url("javascript:alert(1)")

    def test_rejects_no_host(self):
        with pytest.raises(ValueError, match="no host"):
            validate_url("http://")

    def test_rejects_localhost(self):
        with pytest.raises(ValueError, match="Internal"):
            validate_url("http://localhost/admin")

    def test_rejects_127(self):
        with pytest.raises(ValueError, match="Internal"):
            validate_url("http://127.0.0.1:8080")

    def test_rejects_private_10(self):
        with pytest.raises(ValueError, match="Internal"):
            validate_url("http://10.0.0.1")

    def test_rejects_private_192(self):
        with pytest.raises(ValueError, match="Internal"):
            validate_url("http://192.168.1.1")

    def test_rejects_private_172(self):
        with pytest.raises(ValueError, match="Internal"):
            validate_url("http://172.16.0.1")

    def test_rejects_link_local(self):
        with pytest.raises(ValueError, match="Internal"):
            validate_url("http://169.254.1.1")

    def test_rejects_too_long(self):
        long_url = "https://example.com/" + "a" * 2500
        with pytest.raises(ValueError, match="maximum length"):
            validate_url(long_url)

    def test_strips_whitespace(self):
        assert validate_url("  https://example.com  ") == "https://example.com"

    def test_raises_on_non_string(self):
        with pytest.raises(TypeError):
            validate_url(42)


# -------------------------------------------------------------------------
# validate_email
# -------------------------------------------------------------------------

class TestValidateEmail:

    def test_valid_email(self):
        assert validate_email("user@example.com") == "user@example.com"

    def test_valid_with_dots(self):
        assert validate_email("first.last@sub.domain.com") == "first.last@sub.domain.com"

    def test_strips_whitespace(self):
        assert validate_email("  user@example.com  ") == "user@example.com"

    def test_rejects_no_at(self):
        with pytest.raises(ValueError, match="Invalid email"):
            validate_email("not-an-email")

    def test_rejects_no_domain(self):
        with pytest.raises(ValueError, match="Invalid email"):
            validate_email("user@")

    def test_rejects_too_long(self):
        long_email = "a" * 310 + "@example.com"  # 322 chars > MAX_EMAIL_LEN (320)
        with pytest.raises(ValueError, match="maximum length"):
            validate_email(long_email)

    def test_raises_on_non_string(self):
        with pytest.raises(TypeError):
            validate_email(None)


# -------------------------------------------------------------------------
# validate_session_id
# -------------------------------------------------------------------------

class TestValidateSessionId:

    def test_uuid_style(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_session_id(sid) == sid

    def test_plain_alphanumeric(self):
        assert validate_session_id("session123") == "session123"

    def test_underscore_and_dash(self):
        assert validate_session_id("my_session-1") == "my_session-1"

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            validate_session_id("session; DROP TABLE")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            validate_session_id("a" * 200)

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_session_id("")

    def test_strips_whitespace(self):
        assert validate_session_id("  abc123  ") == "abc123"


# -------------------------------------------------------------------------
# validate_iso_date
# -------------------------------------------------------------------------

class TestValidateIsoDate:

    def test_full_iso(self):
        from datetime import datetime

        dt = validate_iso_date("2025-11-10T14:30:00")
        assert isinstance(dt, datetime)
        assert dt.year == 2025
        assert dt.hour == 14

    def test_date_only(self):
        dt = validate_iso_date("2025-06-15")
        assert dt.day == 15

    def test_space_separator(self):
        dt = validate_iso_date("2025-06-15 09:00")
        assert dt.hour == 9

    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="Invalid ISO date"):
            validate_iso_date("not-a-date")

    def test_rejects_partial(self):
        with pytest.raises(ValueError, match="Invalid ISO date"):
            validate_iso_date("2025-13-40")

    def test_raises_on_non_string(self):
        with pytest.raises(TypeError):
            validate_iso_date(12345)


# -------------------------------------------------------------------------
# sanitize_filename
# -------------------------------------------------------------------------

class TestSanitizeFilename:

    def test_simple_name(self):
        assert sanitize_filename("report.csv") == "report.csv"

    def test_strips_directory_path(self):
        assert sanitize_filename("/etc/passwd") == "passwd"

    def test_strips_windows_path(self):
        assert sanitize_filename("C:\\Users\\admin\\evil.exe") == "evil.exe"

    def test_strips_traversal(self):
        assert sanitize_filename("../../etc/shadow") == "shadow"

    def test_rejects_dot_file(self):
        with pytest.raises(ValueError, match="start with a dot"):
            sanitize_filename(".htaccess")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            sanitize_filename("")

    def test_removes_null_bytes(self):
        assert sanitize_filename("fi\x00le.txt") == "file.txt"

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="exceeds"):
            sanitize_filename("a" * 300)

    def test_raises_on_non_string(self):
        with pytest.raises(TypeError):
            sanitize_filename(42)


# -------------------------------------------------------------------------
# Integration: Pydantic model validation (api/server.py style)
# -------------------------------------------------------------------------

class TestPydanticIntegration:
    """Verify that the validators raise cleanly when wired into Field+validator patterns."""

    def test_sanitize_text_in_validator_flow(self):
        """Simulates @validator('message') calling sanitize_text()."""
        raw = '  <script>alert(1)</script>Hello  '
        cleaned = sanitize_text(raw)
        assert cleaned == "Hello"
        assert "<script>" not in cleaned

    def test_validate_url_in_validator_flow(self):
        url = validate_url("https://api.example.com/v1?key=abc")
        assert url.startswith("https://")

    def test_chained_sanitization(self):
        """Multiple dangerous patterns in one string."""
        raw = '\x00javascript:alert(1) onclick="steal()" DROP TABLE; -- normal text'
        cleaned = sanitize_text(raw)
        assert "javascript:" not in cleaned.lower()
        assert "onclick" not in cleaned
        assert "DROP TABLE" not in cleaned
        assert "normal text" in cleaned
