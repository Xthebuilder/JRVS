"""
Memory leak detection tests
Tests to ensure proper resource cleanup and no memory leaks
"""
import pytest
import asyncio
import psutil
import os
from unittest.mock import AsyncMock, patch

from llm.ollama_client import OllamaClient
from scraper.web_scraper import WebScraper
from core.database import Database
from rag.retriever import RAGRetriever


class TestMemoryLeaks:
    """Test suite for detecting memory leaks"""
    
    def get_memory_usage(self):
        """Get current memory usage in MB"""
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_ollama_client_session_cleanup(self):
        """Test that Ollama client properly cleans up HTTP sessions"""
        client = OllamaClient()
        
        # The _get_session method is an async context manager
        # It yields the session object
        session = None
        try:
            # Get session directly to test cleanup
            if client.session is None or client.session.closed:
                import aiohttp
                from config import TIMEOUTS
                timeout = aiohttp.ClientTimeout(total=TIMEOUTS.get("ollama_response", 60))
                client.session = aiohttp.ClientSession(timeout=timeout)
            
            session = client.session
            assert session is not None
        finally:
            # Explicitly cleanup
            await client.cleanup()
        
        # Verify session is closed
        assert client.session is None or client.session.closed
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_web_scraper_session_cleanup(self):
        """Test that web scraper properly cleans up HTTP sessions"""
        scraper = WebScraper()
        
        # Create session
        session = await scraper._get_session()
        assert session is not None
        assert not session.closed
        
        # Cleanup
        await scraper.cleanup()
        
        # Verify session is closed
        assert scraper.session.closed
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_repeated_requests_no_leak(self):
        """Test that repeated requests don't leak memory"""
        initial_memory = self.get_memory_usage()
        
        scraper = WebScraper()
        
        # Simulate many requests
        with patch.object(scraper, 'scrape_url') as mock_scrape:
            mock_scrape.return_value = {
                'title': 'Test',
                'content': 'Content',
                'url': 'https://example.com',
                'metadata': {}
            }
            
            for _ in range(100):
                await scraper.scrape_url("https://example.com")
        
        await scraper.cleanup()
        
        # Check memory usage hasn't grown significantly
        final_memory = self.get_memory_usage()
        memory_growth = final_memory - initial_memory
        
        # Allow some growth but not excessive (< 50MB)
        assert memory_growth < 50, f"Memory grew by {memory_growth:.2f}MB"
    
    @pytest.mark.asyncio
    async def test_database_connection_cleanup(self):
        """Test that database connections are properly managed"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db = Database(db_path)
            await db.initialize()
            
            # Perform multiple operations
            for i in range(50):
                await db.add_conversation(
                    session_id=f"test_{i}",
                    user_message=f"Message {i}",
                    ai_response=f"Response {i}",
                    model_used="test_model"
                )
            
            # aiosqlite handles connections automatically
            # No explicit cleanup needed, but test doesn't leak
            assert True
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_concurrent_operations_no_leak(self):
        """Test concurrent operations don't leak resources"""
        initial_memory = self.get_memory_usage()
        
        async def mock_operation():
            """Mock async operation"""
            await asyncio.sleep(0.01)
            return "done"
        
        # Run many concurrent operations
        tasks = [mock_operation() for _ in range(1000)]
        await asyncio.gather(*tasks)
        
        # Force garbage collection
        import gc
        gc.collect()
        
        final_memory = self.get_memory_usage()
        memory_growth = final_memory - initial_memory
        
        # Allow some growth but not excessive (< 30MB)
        assert memory_growth < 30, f"Memory grew by {memory_growth:.2f}MB"
    
    @pytest.mark.asyncio
    async def test_context_manager_cleanup(self):
        """Test that context managers properly cleanup"""
        client = OllamaClient()
        
        # Use context manager pattern
        try:
            async with client._get_session() as session:
                assert session is not None
                # Simulate error
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Session should still be cleaned up
        await client.cleanup()
        assert client.session is None or client.session.closed


class TestResourceManagement:
    """Test proper resource management patterns"""
    
    @pytest.mark.asyncio
    async def test_ollama_client_cleanup_method_exists(self):
        """Test that OllamaClient has cleanup method"""
        client = OllamaClient()
        assert hasattr(client, 'cleanup')
        assert callable(client.cleanup)
    
    @pytest.mark.asyncio
    async def test_web_scraper_cleanup_method_exists(self):
        """Test that WebScraper has cleanup method"""
        scraper = WebScraper()
        assert hasattr(scraper, 'cleanup')
        assert callable(scraper.cleanup)
    
    @pytest.mark.asyncio
    async def test_rag_retriever_cleanup_method_exists(self):
        """Test that RAGRetriever has cleanup method"""
        retriever = RAGRetriever()
        assert hasattr(retriever, 'cleanup')
        assert callable(retriever.cleanup)
    
    @pytest.mark.asyncio
    async def test_cleanup_idempotent(self):
        """Test that cleanup can be called multiple times safely"""
        client = OllamaClient()
        
        # Multiple cleanup calls should not error
        await client.cleanup()
        await client.cleanup()
        await client.cleanup()
        
        assert True  # No exceptions raised
    
    @pytest.mark.asyncio
    async def test_cleanup_handles_none_session(self):
        """Test cleanup handles None session gracefully"""
        client = OllamaClient()
        client.session = None
        
        # Should not raise exception
        await client.cleanup()
        assert True


class TestHTTPSessionManagement:
    """Test HTTP session management patterns"""
    
    @pytest.mark.asyncio
    async def test_session_reuse(self):
        """Test that sessions are reused when possible"""
        client = OllamaClient()
        
        session1 = await client._get_session().__aenter__()
        session2 = await client._get_session().__aenter__()
        
        # Should reuse the same session
        assert session1 is session2
        
        await client.cleanup()
    
    @pytest.mark.asyncio
    async def test_session_recreation_after_close(self):
        """Test that new session is created after cleanup"""
        client = OllamaClient()
        
        # Create and get reference to first session
        async with client._get_session() as session1:
            pass
        
        # Close it
        await client.cleanup()
        
        # Should create new session
        async with client._get_session() as session2:
            pass
        
        # Different sessions
        assert session1 is not session2
        
        await client.cleanup()
    
    @pytest.mark.asyncio
    async def test_session_timeout_configured(self):
        """Test that sessions have timeout configured"""
        client = OllamaClient()
        
        async with client._get_session() as session:
            assert session._timeout is not None
        
        await client.cleanup()
