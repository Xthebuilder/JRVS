"""
Unit tests for scraper.web_scraper module
Tests web scraping functionality
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

from scraper.web_scraper import WebScraper


class TestWebScraper:
    """Test suite for WebScraper class"""
    
    @pytest.fixture
    def scraper(self):
        """Create a web scraper for testing"""
        return WebScraper()
    
    def test_initialization(self, scraper):
        """Test scraper initialization"""
        assert scraper.session is None
        assert scraper.headers is not None
        assert 'User-Agent' in scraper.headers
    
    @pytest.mark.asyncio
    async def test_get_session_creates_new(self, scraper):
        """Test that _get_session creates a new session"""
        session = await scraper._get_session()
        
        assert session is not None
        assert not session.closed
        
        # Cleanup
        await session.close()
    
    @pytest.mark.asyncio
    async def test_get_session_reuses_existing(self, scraper):
        """Test that _get_session reuses existing session"""
        session1 = await scraper._get_session()
        session2 = await scraper._get_session()
        
        assert session1 is session2
        
        # Cleanup
        await session1.close()
    
    def test_clean_text(self, scraper):
        """Test text cleaning"""
        text = "  Multiple   spaces  \n\n\n  and   newlines  "
        
        cleaned = scraper._clean_text(text)
        
        # Remove multiple spaces and newlines
        assert "Multiple" in cleaned
        assert "spaces" in cleaned
    
    def test_clean_text_empty(self, scraper):
        """Test cleaning empty text"""
        text = "   \n\n   "
        
        cleaned = scraper._clean_text(text)
        
        assert len(cleaned.strip()) == 0
    
    def test_extract_content_with_title(self, scraper):
        """Test extracting content with title"""
        html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <p>First paragraph.</p>
                <p>Second paragraph.</p>
            </body>
        </html>
        """
        
        result = scraper._extract_content(html, "https://example.com")
        
        assert result is not None
        assert result['title'] == "Test Page"
        assert 'content' in result
        assert 'url' in result
        assert 'metadata' in result
    
    def test_extract_content_with_h1(self, scraper):
        """Test extracting content using h1 as title"""
        html = """
        <html>
            <body>
                <h1>Main Header</h1>
                <p>Content here.</p>
            </body>
        </html>
        """
        
        result = scraper._extract_content(html, "https://example.com")
        
        assert result is not None
        assert result['title'] == "Main Header"
    
    def test_extract_content_fallback_title(self, scraper):
        """Test extracting content with fallback title"""
        html = "<html><body><p>Content without title</p></body></html>"
        
        result = scraper._extract_content(html, "https://example.com/page")
        
        assert result is not None
        assert result['title'] == "example.com"  # Domain as fallback
    
    def test_extract_content_removes_scripts(self, scraper):
        """Test that scripts and styles are removed"""
        html = """
        <html>
            <head><title>Test</title></head>
            <body>
                <script>console.log('test');</script>
                <style>.test { color: red; }</style>
                <p>Visible content</p>
            </body>
        </html>
        """
        
        result = scraper._extract_content(html, "https://example.com")
        
        assert "console.log" not in result['content']
        assert "color: red" not in result['content']
        assert "Visible content" in result['content']
    
    def test_extract_content_prefers_main(self, scraper):
        """Test that main content area is preferred"""
        html = """
        <html><body>
            <nav>Navigation</nav>
            <main>Main content here</main>
            <footer>Footer</footer>
        </body></html>
        """
        
        result = scraper._extract_content(html, "https://example.com")
        
        assert "Main content" in result['content']
        # Nav and footer should be removed
        assert "Navigation" not in result['content']
    
    @pytest.mark.asyncio
    async def test_scrape_url_success(self, scraper):
        """Test successful URL scraping"""
        test_html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        
        with patch.object(scraper, '_get_session') as mock_get_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text.return_value = test_html
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            
            mock_session = AsyncMock()
            mock_session.get.return_value = mock_response
            mock_get_session.return_value = mock_session
            
            result = await scraper.scrape_url("https://example.com")
            
            assert result is not None
            assert result['title'] == "Test"
            assert "Content" in result['content']
    
    @pytest.mark.asyncio
    async def test_scrape_url_404(self, scraper):
        """Test scraping URL that returns 404"""
        with patch.object(scraper, '_get_session') as mock_get_session:
            mock_response = AsyncMock()
            mock_response.status = 404
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            
            mock_session = AsyncMock()
            mock_session.get.return_value = mock_response
            mock_get_session.return_value = mock_session
            
            result = await scraper.scrape_url("https://example.com/notfound")
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_scrape_url_timeout(self, scraper):
        """Test scraping URL with timeout"""
        with patch.object(scraper, '_get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_session.get.side_effect = asyncio.TimeoutError()
            mock_get_session.return_value = mock_session
            
            result = await scraper.scrape_url("https://example.com")
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_scrape_url_exception(self, scraper):
        """Test scraping URL with exception"""
        with patch.object(scraper, '_get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_session.get.side_effect = Exception("Network error")
            mock_get_session.return_value = mock_session
            
            result = await scraper.scrape_url("https://example.com")
            
            assert result is None
    
    def test_extract_metadata(self, scraper):
        """Test metadata extraction"""
        html = """
        <html>
            <head>
                <meta name="description" content="Test description">
                <meta name="keywords" content="test, keywords">
            </head>
            <body></body>
        </html>
        """
        
        soup = BeautifulSoup(html, 'html.parser')
        metadata = scraper._extract_metadata(soup, "https://example.com")
        
        assert isinstance(metadata, dict)
    
    @pytest.mark.asyncio
    async def test_scrape_and_store_success(self, scraper):
        """Test scraping and storing"""
        test_html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        
        with patch.object(scraper, 'scrape_url') as mock_scrape:
            mock_scrape.return_value = {
                'title': 'Test',
                'content': 'Content',
                'url': 'https://example.com',
                'metadata': {}
            }
            
            with patch('scraper.web_scraper.rag_retriever') as mock_rag:
                mock_rag.add_document.return_value = 1
                
                result = await scraper.scrape_and_store("https://example.com")
                
                assert result is not None


class TestGlobalWebScraperInstance:
    """Test the global web_scraper instance"""
    
    def test_global_instance_exists(self):
        """Test that global web_scraper instance exists"""
        from scraper.web_scraper import web_scraper
        
        assert web_scraper is not None
        assert isinstance(web_scraper, WebScraper)
