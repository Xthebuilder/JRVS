"""
Unit tests for google_integration/client.py

All Google API calls and RAG ingestion are mocked.
Tests focus on sync logic, deduplication, and background task management.
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timezone

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Import guard — skip all if google_integration is misconfigured
# ---------------------------------------------------------------------------

try:
    from google_integration.client import GoogleWorkspaceClient
    _IMPORT_OK = True
except Exception:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="google_integration module not importable (missing credentials OK in CI)"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_auth():
    auth = MagicMock()
    auth.get_credentials = MagicMock(return_value=MagicMock())
    return auth


def _mock_gmail():
    g = MagicMock()
    g.list_messages = MagicMock(return_value=[])
    g.get_message = MagicMock(return_value={"id": "1", "subject": "Test", "body": "Hello"})
    return g


def _mock_drive():
    d = MagicMock()
    d.list_files = MagicMock(return_value=[])
    return d


def _patched_client():
    """Build a GoogleWorkspaceClient with all sub-clients mocked."""
    with patch("google_integration.client.GoogleAuth", return_value=_mock_auth()), \
         patch("google_integration.client.GmailClient", return_value=_mock_gmail()), \
         patch("google_integration.client.GoogleDocsClient", return_value=MagicMock()), \
         patch("google_integration.client.GoogleSheetsClient", return_value=MagicMock()), \
         patch("google_integration.client.GoogleDriveClient", return_value=_mock_drive()), \
         patch("google_integration.client.AuditLog", return_value=MagicMock()):
        return GoogleWorkspaceClient()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestGoogleWorkspaceClientInit:
    def test_client_instantiates(self):
        client = _patched_client()
        assert client is not None

    def test_sync_task_initially_none(self):
        client = _patched_client()
        assert client._sync_task is None

    def test_ingested_counters_start_at_zero(self):
        client = _patched_client()
        assert client._ingested.get("gmail", 0) == 0
        assert client._ingested.get("drive", 0) == 0


# ---------------------------------------------------------------------------
# Background Sync
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBackgroundSync:
    async def test_start_creates_task(self):
        client = _patched_client()
        with patch.object(client, "_sync_loop", AsyncMock()):
            await client.start_background_sync()
            assert client._sync_task is not None
            client._sync_task.cancel()
            try:
                await client._sync_task
            except asyncio.CancelledError:
                pass

    async def test_start_is_idempotent(self):
        client = _patched_client()
        with patch.object(client, "_sync_loop", AsyncMock()):
            await client.start_background_sync()
            task1 = client._sync_task
            await client.start_background_sync()  # Should not create a second task
            assert client._sync_task is task1
            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                pass

    async def test_stop_cancels_task(self):
        client = _patched_client()
        with patch.object(client, "_sync_loop", AsyncMock()):
            await client.start_background_sync()
            await client.stop_background_sync()
            assert client._sync_task is None or client._sync_task.cancelled()


# ---------------------------------------------------------------------------
# sync_now
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSyncNow:
    async def test_sync_now_returns_dict(self):
        client = _patched_client()
        with patch.object(client, "_sync_gmail", AsyncMock(return_value=3)), \
             patch.object(client, "_sync_drive", AsyncMock(return_value=2)):
            result = await client.sync_now()
        assert isinstance(result, dict)
        assert result.get("emails_ingested") == 3
        assert result.get("docs_ingested") == 2

    async def test_sync_now_includes_timestamp(self):
        client = _patched_client()
        with patch.object(client, "_sync_gmail", AsyncMock(return_value=0)), \
             patch.object(client, "_sync_drive", AsyncMock(return_value=0)):
            result = await client.sync_now()
        assert "synced_at" in result


# ---------------------------------------------------------------------------
# _sync_gmail (deduplication)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSyncGmail:
    async def test_skips_already_indexed_emails(self):
        client = _patched_client()
        emails = [{"id": "1", "subject": "A", "body": "text", "from": "x@x.com", "date": "now"}]
        client.gmail.list_messages = MagicMock(return_value=emails)

        with patch("google_integration.client.db") as mock_db, \
             patch("google_integration.client.rag_retriever") as mock_rag:
            mock_db.check_document_exists = AsyncMock(return_value=True)
            count = await client._sync_gmail()

        assert count == 0

    async def test_ingests_new_emails(self):
        client = _patched_client()
        emails = [{"id": "1", "subject": "New", "body": "body text", "from": "a@b.com", "date": "now"}]
        client.gmail.list_messages = MagicMock(return_value=emails)

        with patch("google_integration.client.db") as mock_db, \
             patch("google_integration.client.rag_retriever") as mock_rag:
            mock_db.check_document_exists = AsyncMock(return_value=False)
            mock_rag.add_document = AsyncMock(return_value=1)
            count = await client._sync_gmail()

        assert count == 1
