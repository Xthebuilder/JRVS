"""
Unit tests for core.file_handler — file listing, reading, and path traversal protection.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.file_handler as fh_module
from core.file_handler import FileHandler, SUPPORTED_EXTENSIONS, _SIZE_LIMIT


class TestFileHandlerListFiles:
    """Tests for FileHandler.list_files()."""

    def test_list_files_empty_dir(self, tmp_path):
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler.list_files() == []

    def test_list_files_returns_metadata(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            files = handler.list_files()
            assert len(files) == 1
            f = files[0]
            assert f["name"] == "notes.txt"
            assert f["extension"] == ".txt"
            assert f["supported"] is True
            assert f["size"] > 0

    def test_list_files_skips_hidden(self, tmp_path):
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "visible.txt").write_text("ok")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            names = [f["name"] for f in handler.list_files()]
            assert ".hidden" not in names
            assert "visible.txt" in names

    def test_list_files_supported_flag(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            files = {f["name"]: f["supported"] for f in handler.list_files()}
            assert files["data.csv"] is True
            assert files["image.png"] is False


class TestFileHandlerReadFile:
    """Tests for FileHandler.read_file() and path-traversal safety."""

    def test_read_existing_file(self, tmp_path):
        (tmp_path / "hello.txt").write_text("world")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler.read_file("hello.txt") == "world"

    def test_read_nonexistent_returns_none(self, tmp_path):
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler.read_file("nope.txt") is None

    def test_path_traversal_blocked(self, tmp_path):
        # Create a file outside uploads
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("top secret")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler.read_file("../secret.txt") is None

    def test_oversized_file_returns_none(self, tmp_path):
        big = tmp_path / "big.txt"
        big.write_text("x")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path), \
             patch.object(fh_module, "_SIZE_LIMIT", 0):
            handler = FileHandler()
            assert handler.read_file("big.txt") is None


class TestFileHandlerResolveSafe:
    """Tests for the private _resolve_safe method."""

    def test_resolve_safe_valid(self, tmp_path):
        (tmp_path / "ok.txt").write_text("data")
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler._resolve_safe("ok.txt") is not None

    def test_resolve_safe_traversal(self, tmp_path):
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler._resolve_safe("../../etc/passwd") is None

    def test_resolve_safe_directory(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            assert handler._resolve_safe("subdir") is None


class TestFileHandlerIngest:
    """Tests for the async ingest_file and ingest_all methods."""

    @pytest.mark.asyncio
    async def test_ingest_file_success(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Hello\nSome content")
        mock_rag = AsyncMock()
        mock_rag.add_document.return_value = "doc-id-123"
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            result = await handler.ingest_file("doc.md", mock_rag)
            assert result is True
            mock_rag.add_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_file_unsupported_ext(self, tmp_path):
        (tmp_path / "photo.png").write_bytes(b"\x89PNG")
        mock_rag = AsyncMock()
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            result = await handler.ingest_file("photo.png", mock_rag)
            assert result is False

    @pytest.mark.asyncio
    async def test_ingest_file_nonexistent(self, tmp_path):
        mock_rag = AsyncMock()
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            result = await handler.ingest_file("nope.txt", mock_rag)
            assert result is False

    @pytest.mark.asyncio
    async def test_ingest_all_mixed(self, tmp_path):
        (tmp_path / "good.py").write_text("print('hello')")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        mock_rag = AsyncMock()
        mock_rag.add_document.return_value = "id"
        with patch.object(fh_module, "UPLOADS_DIR", tmp_path):
            handler = FileHandler()
            results = await handler.ingest_all(mock_rag)
            assert "good.py" in results["success"]
            assert "image.png" in results["skipped"]
