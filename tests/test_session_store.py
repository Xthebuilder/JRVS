"""Tests for core.session_store — unified PostgreSQL session history."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.session_store import SessionStore


# ---------------------------------------------------------------------------
# Helpers — build a fake asyncpg pool + connection
# ---------------------------------------------------------------------------

def _make_fake_pool():
    """Return a mock asyncpg pool that tracks INSERT/SELECT calls."""
    pool = AsyncMock()
    conn = AsyncMock()

    # pool.acquire() must return an async context manager, not a coroutine.
    # asyncpg's real acquire() returns a PoolAcquireContext.
    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire

    # conn.transaction() must also be an async context manager.
    @asynccontextmanager
    async def _transaction():
        yield None

    conn.transaction = _transaction

    return pool, conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionStoreLifecycle:
    """Verify initialize / close lifecycle."""

    @pytest.mark.asyncio
    async def test_require_pool_raises_before_init(self):
        store = SessionStore()
        with pytest.raises(RuntimeError, match="not been initialized"):
            store._require_pool()

    @pytest.mark.asyncio
    @patch("core.session_store.asyncpg")
    async def test_initialize_with_dsn(self, mock_asyncpg):
        pool, _ = _make_fake_pool()
        mock_asyncpg.create_pool = AsyncMock(return_value=pool)

        store = SessionStore()
        with patch("core.session_store.SESSION_DATABASE_URL", "postgresql://u:p@host/db"):
            await store.initialize()

        mock_asyncpg.create_pool.assert_called_once()
        call_kwargs = mock_asyncpg.create_pool.call_args
        assert call_kwargs.kwargs["dsn"] == "postgresql://u:p@host/db"
        assert store._initialized is True

    @pytest.mark.asyncio
    @patch("core.session_store.asyncpg")
    async def test_initialize_with_individual_vars(self, mock_asyncpg):
        pool, _ = _make_fake_pool()
        mock_asyncpg.create_pool = AsyncMock(return_value=pool)

        store = SessionStore()
        with patch("core.session_store.SESSION_DATABASE_URL", ""), \
             patch("core.session_store.SESSION_PG_HOST", "myhost"), \
             patch("core.session_store.SESSION_PG_PORT", 5433), \
             patch("core.session_store.SESSION_PG_USER", "myuser"), \
             patch("core.session_store.SESSION_PG_PASSWORD", "secret"), \
             patch("core.session_store.SESSION_PG_DATABASE", "mydb"):
            await store.initialize()

        call_kwargs = mock_asyncpg.create_pool.call_args.kwargs
        assert call_kwargs["host"] == "myhost"
        assert call_kwargs["port"] == 5433
        assert call_kwargs["user"] == "myuser"
        assert call_kwargs["password"] == "secret"
        assert call_kwargs["database"] == "mydb"

    @pytest.mark.asyncio
    @patch("core.session_store.asyncpg")
    async def test_close(self, mock_asyncpg):
        pool, _ = _make_fake_pool()
        mock_asyncpg.create_pool = AsyncMock(return_value=pool)

        store = SessionStore()
        with patch("core.session_store.SESSION_DATABASE_URL", "postgresql://u:p@h/d"):
            await store.initialize()

        await store.close()
        pool.close.assert_awaited_once()
        assert store._initialized is False

    @pytest.mark.asyncio
    @patch("core.session_store.asyncpg")
    async def test_double_initialize_is_noop(self, mock_asyncpg):
        pool, _ = _make_fake_pool()
        mock_asyncpg.create_pool = AsyncMock(return_value=pool)

        store = SessionStore()
        with patch("core.session_store.SESSION_DATABASE_URL", "postgresql://u:p@h/d"):
            await store.initialize()
            await store.initialize()

        # create_pool called only once
        assert mock_asyncpg.create_pool.call_count == 1


class TestSessionStoreWrite:
    """Verify add_message and add_turn."""

    @pytest.mark.asyncio
    async def test_add_message(self):
        store = SessionStore()
        pool, _ = _make_fake_pool()
        pool.fetchval = AsyncMock(return_value=42)
        store._pool = pool
        store._initialized = True

        msg_id = await store.add_message("sess1", "user", "hello", metadata={"extra": 1})
        assert msg_id == 42
        pool.fetchval.assert_awaited_once()
        args = pool.fetchval.call_args[0]
        assert args[1] == "sess1"
        assert args[2] == "user"
        assert args[3] == "hello"
        assert json.loads(args[4]) == {"extra": 1}

    @pytest.mark.asyncio
    async def test_add_turn_inserts_two_rows(self):
        store = SessionStore()
        pool, conn = _make_fake_pool()
        store._pool = pool
        store._initialized = True

        await store.add_turn("sess1", "hi", "hello back", metadata={"model": "test"})

        # Should have two execute() calls inside the transaction
        assert conn.execute.call_count == 2
        first_call = conn.execute.call_args_list[0][0]
        second_call = conn.execute.call_args_list[1][0]
        assert "'user'" in first_call[0]
        assert "'assistant'" in second_call[0]


class TestSessionStoreRead:
    """Verify get_recent and get_recent_as_pairs."""

    @pytest.mark.asyncio
    async def test_get_recent_returns_chronological(self):
        store = SessionStore()
        pool, _ = _make_fake_pool()

        # Simulate DB returning most-recent-first (as our ORDER BY does)
        pool.fetch = AsyncMock(return_value=[
            {"role": "assistant", "content": "I'm fine"},
            {"role": "user", "content": "how are you"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "hello"},
        ])
        store._pool = pool
        store._initialized = True

        result = await store.get_recent("sess1", limit=2)
        assert len(result) == 4
        # oldest first
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"
        assert result[-1]["role"] == "assistant"
        assert result[-1]["content"] == "I'm fine"

    @pytest.mark.asyncio
    async def test_get_recent_as_pairs(self):
        store = SessionStore()
        pool, _ = _make_fake_pool()

        pool.fetch = AsyncMock(return_value=[
            {"role": "assistant", "content": "I'm fine"},
            {"role": "user", "content": "how are you"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "hello"},
        ])
        store._pool = pool
        store._initialized = True

        pairs = await store.get_recent_as_pairs("sess1", limit=2)
        assert len(pairs) == 2
        assert pairs[0] == {"user": "hello", "assistant": "hi there"}
        assert pairs[1] == {"user": "how are you", "assistant": "I'm fine"}

    @pytest.mark.asyncio
    async def test_get_recent_as_pairs_skips_orphans(self):
        store = SessionStore()
        pool, _ = _make_fake_pool()

        # Orphaned assistant at the start
        pool.fetch = AsyncMock(return_value=[
            {"role": "assistant", "content": "I'm fine"},
            {"role": "user", "content": "how are you"},
            {"role": "assistant", "content": "orphan"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ])
        store._pool = pool
        store._initialized = True

        pairs = await store.get_recent_as_pairs("sess1", limit=5)
        # "hello" + "hi there" is a clean pair
        # "orphan" is an assistant without a preceding user — skipped
        # Then "how are you" + "I'm fine" is next pair
        assert len(pairs) == 2


class TestSessionStoreCount:
    """Verify count method."""

    @pytest.mark.asyncio
    async def test_count(self):
        store = SessionStore()
        pool, _ = _make_fake_pool()
        pool.fetchval = AsyncMock(return_value=10)
        store._pool = pool
        store._initialized = True

        c = await store.count("sess1")
        assert c == 10
        pool.fetchval.assert_awaited_once()
