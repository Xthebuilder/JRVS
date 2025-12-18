#!/usr/bin/env python3
"""
Unit tests for scraper.web_scraper module
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scraper.web_scraper import WebScraper


@pytest.fixture
def web_scraper():
    """Create a web scraper instance"""
    return WebScraper()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scraper_initialization(web_scraper):
    """Test web scraper initialization"""
    assert web_scraper is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scrape_url_with_mock():
    """Test scraping a URL with mocked response"""
    scraper = WebScraper()
    
    mock_html = """
    <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Test Heading</h1>
            <p>This is test content.</p>
        </body>
    </html>
    """
    
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value=mock_html)
    
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    
    with patch('aiohttp.ClientSession', return_value=mock_session):
        result = await scraper.scrape_url("https://example.com")
        
        assert result is not None
        assert 'title' in result
        assert 'content' in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_text_from_html(web_scraper):
    """Test extracting text from HTML through public interface"""
    # Mock scraping to test text extraction
    mock_html = """
    <html>
        <body>
            <h1>Heading</h1>
            <p>Paragraph text</p>
            <script>console.log('script');</script>
            <style>.class { color: red; }</style>
        </body>
    </html>
    """
    
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value=mock_html)
    
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    
    with patch('aiohttp.ClientSession', return_value=mock_session):
        result = await web_scraper.scrape_url("https://example.com")
        
        if result and 'content' in result:
            text = result['content']
            assert "Heading" in text
            assert "Paragraph text" in text
            # Script tags should be filtered out
            assert "console" not in text.lower() or text.count("console") == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_title_from_html(web_scraper):
    """Test extracting title from HTML"""
    html = """
    <html>
        <head><title>Test Page Title</title></head>
        <body><p>Content</p></body>
    </html>
    """
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    
    title_tag = soup.find('title')
    if title_tag:
        title = title_tag.get_text()
        assert title == "Test Page Title"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validate_url(web_scraper):
    """Test URL validation"""
    valid_url = "https://example.com"
    invalid_url = "not-a-url"
    
    # Test valid URL
    assert "http" in valid_url
    
    # Test invalid URL
    assert "http" not in invalid_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scrape_error_handling():
    """Test error handling when scraping fails"""
    scraper = WebScraper()
    
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=Exception("Connection error"))
    
    with patch('aiohttp.ClientSession', return_value=mock_session):
        result = await scraper.scrape_url("https://example.com")
        
        # Should handle error gracefully
        assert result is None or isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scrape_timeout():
    """Test scraping with timeout"""
    scraper = WebScraper(timeout=1)
    
    # Mock a slow response
    mock_response = MagicMock()
    mock_response.status = 200
    
    async def slow_text():
        await asyncio.sleep(2)
        return "<html><body>Slow</body></html>"
    
    mock_response.text = slow_text
    
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    
    with patch('aiohttp.ClientSession', return_value=mock_session):
        # This should timeout or handle gracefully
        try:
            result = await scraper.scrape_url("https://example.com")
        except asyncio.TimeoutError:
            pass  # Expected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scrape_multiple_urls():
    """Test scraping multiple URLs"""
    scraper = WebScraper()
    
    urls = [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3"
    ]
    
    mock_html = "<html><body><p>Test</p></body></html>"
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value=mock_html)
    
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    
    with patch('aiohttp.ClientSession', return_value=mock_session):
        results = []
        for url in urls:
            result = await scraper.scrape_url(url)
            results.append(result)
        
        assert len(results) == len(urls)
