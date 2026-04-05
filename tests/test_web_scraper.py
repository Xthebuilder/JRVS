"""
Unit tests for scraper/web_scraper.py

All HTTP and RAG calls are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.web_scraper import WebScraper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scraper():
    return WebScraper()


SAMPLE_HTML = """
<html>
<head>
  <title>Test Page</title>
  <meta name="description" content="A test description">
  <meta name="author" content="Tester">
</head>
<body>
  <p>Hello world. This is test content.</p>
  <a href="https://example.com/page1">Link 1</a>
  <a href="https://example.com/page2">Link 2</a>
  <a href="/relative">Relative</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_collapses_whitespace(self):
        s = WebScraper()
        result = s._clean_text("hello   world\n\t foo")
        assert "  " not in result

    def test_empty_string(self):
        s = WebScraper()
        assert s._clean_text("") == ""

    def test_single_word_unchanged(self):
        s = WebScraper()
        assert s._clean_text("hello") == "hello"


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------

class TestExtractContent:
    def test_extracts_title(self):
        s = _scraper()
        result = s._extract_content(SAMPLE_HTML, "https://example.com")
        assert result["title"] == "Test Page"

    def test_extracts_content_text(self):
        s = _scraper()
        result = s._extract_content(SAMPLE_HTML, "https://example.com")
        assert "Hello world" in result["content"]

    def test_url_stored(self):
        s = _scraper()
        result = s._extract_content(SAMPLE_HTML, "https://example.com")
        assert result["url"] == "https://example.com"

    def test_metadata_key_present(self):
        s = _scraper()
        result = s._extract_content(SAMPLE_HTML, "https://example.com")
        assert "metadata" in result

    def test_no_title_fallback(self):
        s = _scraper()
        result = s._extract_content("<html><body>text</body></html>", "https://x.com")
        # Should not raise; title may be empty or default
        assert "title" in result


# ---------------------------------------------------------------------------
# _extract_metadata
# ---------------------------------------------------------------------------

class TestExtractMetadata:
    def test_extracts_description(self):
        from bs4 import BeautifulSoup
        s = _scraper()
        soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
        meta = s._extract_metadata(soup, "https://example.com")
        assert meta.get("description") == "A test description"

    def test_extracts_author(self):
        from bs4 import BeautifulSoup
        s = _scraper()
        soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
        meta = s._extract_metadata(soup, "https://example.com")
        assert meta.get("author") == "Tester"

    def test_url_in_metadata(self):
        from bs4 import BeautifulSoup
        s = _scraper()
        soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
        meta = s._extract_metadata(soup, "https://example.com")
        assert meta.get("url") == "https://example.com"


# ---------------------------------------------------------------------------
# extract_links
# ---------------------------------------------------------------------------

class TestExtractLinks:
    def test_extracts_absolute_https_links(self):
        s = _scraper()
        links = s.extract_links(SAMPLE_HTML, "https://example.com")
        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links

    def test_deduplicates_links(self):
        html = '<a href="https://x.com">1</a><a href="https://x.com">2</a>'
        s = _scraper()
        links = s.extract_links(html, "https://base.com")
        assert links.count("https://x.com") == 1

    def test_excludes_non_http_links(self):
        html = '<a href="mailto:test@test.com">email</a><a href="https://ok.com">ok</a>'
        s = _scraper()
        links = s.extract_links(html, "https://base.com")
        assert not any("mailto" in l for l in links)

    def test_empty_html_returns_empty(self):
        s = _scraper()
        assert s.extract_links("", "https://base.com") == []


# ---------------------------------------------------------------------------
# scrape_url (mocked HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestScrapeUrl:
    async def test_returns_dict_on_success(self):
        s = _scraper()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=SAMPLE_HTML)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)

        with patch.object(s, "_get_session", AsyncMock(return_value=mock_session)):
            result = await s.scrape_url("https://example.com")

        assert result is not None
        assert "title" in result
        assert "content" in result

    async def test_returns_none_on_http_error(self):
        s = _scraper()
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.text = AsyncMock(return_value="Not Found")

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)

        with patch.object(s, "_get_session", AsyncMock(return_value=mock_session)):
            result = await s.scrape_url("https://example.com/404")

        assert result is None

    async def test_returns_none_on_exception(self):
        s = _scraper()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)

        with patch.object(s, "_get_session", AsyncMock(return_value=mock_session)):
            result = await s.scrape_url("https://unreachable.com")

        assert result is None


# ---------------------------------------------------------------------------
# scrape_and_store (mocked HTTP + DB + RAG)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestScrapeAndStore:
    async def test_returns_none_for_already_indexed_url(self):
        s = _scraper()

        with patch("scraper.web_scraper.db") as mock_db:
            mock_db.check_document_exists = AsyncMock(return_value=True)
            result = await s.scrape_and_store("https://already-indexed.com")

        assert result is None

    async def test_returns_doc_id_on_success(self):
        s = _scraper()
        scraped = {
            "title": "T",
            "content": "Content here",
            "url": "https://new.com",
            "metadata": {},
        }

        with patch("scraper.web_scraper.db") as mock_db, \
             patch("scraper.web_scraper.rag_retriever") as mock_rag:
            mock_db.check_document_exists = AsyncMock(return_value=False)
            mock_rag.add_document = AsyncMock(return_value=99)
            with patch.object(s, "scrape_url", AsyncMock(return_value=scraped)):
                result = await s.scrape_and_store("https://new.com")

        assert result == 99

    async def test_returns_none_when_scrape_fails(self):
        s = _scraper()

        with patch("scraper.web_scraper.db") as mock_db:
            mock_db.check_document_exists = AsyncMock(return_value=False)
            with patch.object(s, "scrape_url", AsyncMock(return_value=None)):
                result = await s.scrape_and_store("https://bad.com")

        assert result is None


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCleanup:
    async def test_cleanup_closes_session(self):
        s = _scraper()
        mock_session = AsyncMock()
        mock_session.close = AsyncMock()
        s.session = mock_session
        await s.cleanup()
        mock_session.close.assert_called_once()

    async def test_cleanup_with_no_session_is_safe(self):
        s = _scraper()
        s.session = None
        await s.cleanup()  # Should not raise
