"""
Unit tests for the database layer.

Uses a temporary SQLite DB — no external dependencies.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database


@pytest.fixture
async def test_db(tmp_path):
    """Create a temporary database instance."""
    db = Database(db_path=str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.mark.asyncio
class TestDatabaseInit:
    """Test database initialization and schema creation."""

    async def test_initialize_creates_db_file(self, tmp_path):
        db_path = str(tmp_path / "init_test.db")
        db = Database(db_path=db_path)
        await db.initialize()
        assert Path(db_path).exists()

    async def test_double_initialize_is_safe(self, tmp_path):
        db_path = str(tmp_path / "double_init.db")
        db = Database(db_path=db_path)
        await db.initialize()
        await db.initialize()  # Should not raise


@pytest.mark.asyncio
class TestConversations:
    """Test conversation storage and retrieval."""

    async def test_add_and_retrieve_conversation(self, test_db):
        conv_id = await test_db.add_conversation(
            session_id="test-session",
            user_message="Hello",
            ai_response="Hi there!",
            model_used="test-model",
        )
        assert conv_id > 0

        history = await test_db.get_recent_conversations("test-session", limit=10)
        assert len(history) == 1
        assert history[0]["user_message"] == "Hello"
        assert history[0]["ai_response"] == "Hi there!"

    async def test_multiple_sessions_are_isolated(self, test_db):
        await test_db.add_conversation("session-a", "Q1", "A1", "model")
        await test_db.add_conversation("session-b", "Q2", "A2", "model")

        a_history = await test_db.get_recent_conversations("session-a")
        b_history = await test_db.get_recent_conversations("session-b")

        assert len(a_history) == 1
        assert len(b_history) == 1
        assert a_history[0]["user_message"] == "Q1"
        assert b_history[0]["user_message"] == "Q2"

    async def test_limit_works(self, test_db):
        for i in range(20):
            await test_db.add_conversation("sess", f"Q{i}", f"A{i}", "model")

        limited = await test_db.get_recent_conversations("sess", limit=5)
        assert len(limited) == 5


@pytest.mark.asyncio
class TestDocuments:
    """Test document storage and deduplication."""

    async def test_add_document(self, test_db):
        doc_id = await test_db.add_document(
            url="https://example.com",
            title="Test",
            content="Test content",
        )
        assert doc_id > 0

    async def test_check_document_exists(self, test_db):
        await test_db.add_document("https://example.com", "Test", "Content")
        assert await test_db.check_document_exists("https://example.com") is True
        assert await test_db.check_document_exists("https://nonexistent.com") is False

    async def test_empty_url_not_found(self, test_db):
        assert await test_db.check_document_exists("") is False


@pytest.mark.asyncio
class TestFeedback:
    """Test the feedback loop database operations."""

    async def test_log_and_retrieve_feedback(self, test_db):
        fb_id = await test_db.log_feedback("What is AI?", "Bad answer", "Too vague")
        assert fb_id > 0

        pending = await test_db.get_pending_feedback()
        assert len(pending) == 1
        assert pending[0]["question"] == "What is AI?"

    async def test_mark_feedback_processed(self, test_db):
        fb_id = await test_db.log_feedback("Q", "A", "note")
        await test_db.mark_feedback_processed(fb_id)

        pending = await test_db.get_pending_feedback()
        assert len(pending) == 0


@pytest.mark.asyncio
class TestPreferences:
    """Test user preferences storage."""

    async def test_set_and_get_preference(self, test_db):
        await test_db.set_preference("theme", "cyberpunk")
        value = await test_db.get_preference("theme")
        assert value == "cyberpunk"

    async def test_default_for_missing_preference(self, test_db):
        value = await test_db.get_preference("nonexistent", default="fallback")
        assert value == "fallback"

    async def test_overwrite_preference(self, test_db):
        await test_db.set_preference("key", "value1")
        await test_db.set_preference("key", "value2")
        assert await test_db.get_preference("key") == "value2"
