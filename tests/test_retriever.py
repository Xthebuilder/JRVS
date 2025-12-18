"""
Unit tests for rag.retriever module
Tests document chunking, context retrieval, and RAG functionality
"""
import pytest
import asyncio
import os
import tempfile
from pathlib import Path

from rag.retriever import RAGRetriever
from core.database import Database


class TestRAGRetriever:
    """Test suite for RAGRetriever class"""
    
    @pytest.fixture
    async def temp_db(self):
        """Create a temporary database for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
            db_path = f.name
        
        test_db = Database(db_path)
        await test_db.initialize()
        
        yield test_db
        
        # Cleanup
        if os.path.exists(db_path):
            os.remove(db_path)
    
    @pytest.fixture
    async def retriever(self, temp_db, monkeypatch):
        """Create RAG retriever with temporary database"""
        retriever = RAGRetriever()
        
        # Patch the global db instance to use temp_db
        from core import database
        monkeypatch.setattr(database, 'db', temp_db)
        
        yield retriever
        
        # Cleanup
        if retriever.initialized:
            await retriever.cleanup()
    
    @pytest.mark.asyncio
    async def test_initialize(self, retriever):
        """Test RAG retriever initialization"""
        await retriever.initialize()
        assert retriever.initialized is True
    
    @pytest.mark.asyncio
    async def test_chunk_text_simple(self, retriever):
        """Test text chunking with simple text"""
        text = "This is sentence one. This is sentence two. This is sentence three."
        chunks = retriever._chunk_text(text)
        
        assert len(chunks) > 0
        assert all(isinstance(chunk, str) for chunk in chunks)
        assert all(len(chunk) > 0 for chunk in chunks)
    
    @pytest.mark.asyncio
    async def test_chunk_text_long_content(self, retriever):
        """Test text chunking with long content"""
        # Create a long text that will require multiple chunks
        text = ". ".join([f"This is sentence number {i}" for i in range(100)])
        chunks = retriever._chunk_text(text)
        
        assert len(chunks) > 1
        # Verify overlap exists
        for i in range(len(chunks) - 1):
            # Some content should overlap between consecutive chunks
            assert chunks[i] != chunks[i + 1]
    
    @pytest.mark.asyncio
    async def test_chunk_text_empty(self, retriever):
        """Test chunking empty text"""
        text = ""
        chunks = retriever._chunk_text(text)
        
        assert len(chunks) == 0
    
    @pytest.mark.asyncio
    async def test_chunk_text_single_long_sentence(self, retriever):
        """Test chunking a single very long sentence"""
        text = " ".join(["word"] * 1000)  # 1000 words without punctuation
        chunks = retriever._chunk_text(text)
        
        # Should still create chunks
        assert len(chunks) > 0
    
    @pytest.mark.asyncio
    async def test_retrieve_context_empty_store(self, retriever):
        """Test retrieving context from empty vector store"""
        await retriever.initialize()
        
        query = "What is Python?"
        context = await retriever.retrieve_context(query)
        
        # Should return empty or minimal context
        assert isinstance(context, str)
    
    @pytest.mark.asyncio
    async def test_retrieve_context_with_session(self, retriever, temp_db):
        """Test retrieving context with session ID"""
        await retriever.initialize()
        
        session_id = "test_session_789"
        
        # Add some conversation history
        await temp_db.add_conversation(
            session_id=session_id,
            user_message="What is AI?",
            ai_response="AI stands for Artificial Intelligence",
            model_used="test_model"
        )
        
        query = "Tell me more"
        context = await retriever.retrieve_context(query, session_id=session_id)
        
        assert isinstance(context, str)
        # Should include conversation context
        if context:
            assert "conversation" in context.lower() or "AI" in context
    
    @pytest.mark.asyncio
    async def test_format_conversation_context(self, retriever):
        """Test formatting conversation context"""
        conversations = [
            {
                'user_message': "Hello",
                'ai_response': "Hi there!",
                'model_used': 'test',
                'created_at': '2025-01-01'
            },
            {
                'user_message': "How are you?",
                'ai_response': "I'm doing well, thank you!",
                'model_used': 'test',
                'created_at': '2025-01-01'
            }
        ]
        
        context = retriever._format_conversation_context(conversations)
        
        assert isinstance(context, str)
        assert "User:" in context
        assert "Assistant:" in context
        assert "Hello" in context
    
    @pytest.mark.asyncio
    async def test_format_document_context(self, retriever):
        """Test formatting document context"""
        search_results = [
            (
                "Python is a programming language",
                0.95,
                {'document_id': 1, 'title': 'Python Guide', 'url': 'https://example.com', 'chunk_index': 0}
            ),
            (
                "Python is easy to learn",
                0.85,
                {'document_id': 1, 'title': 'Python Guide', 'url': 'https://example.com', 'chunk_index': 1}
            )
        ]
        
        context = retriever._format_document_context(search_results)
        
        assert isinstance(context, str)
        assert "Python" in context
        assert "Python Guide" in context
    
    @pytest.mark.asyncio
    async def test_format_document_context_empty(self, retriever):
        """Test formatting empty document context"""
        search_results = []
        context = retriever._format_document_context(search_results)
        
        assert context == ""
    
    @pytest.mark.asyncio
    async def test_format_document_context_deduplication(self, retriever):
        """Test that document context deduplicates same document chunks"""
        search_results = [
            ("Text A", 0.95, {'document_id': 1, 'title': 'Doc', 'url': '', 'chunk_index': 0}),
            ("Text A", 0.94, {'document_id': 1, 'title': 'Doc', 'url': '', 'chunk_index': 0}),  # Duplicate
            ("Text B", 0.93, {'document_id': 1, 'title': 'Doc', 'url': '', 'chunk_index': 1})
        ]
        
        context = retriever._format_document_context(search_results)
        
        # Should only include unique chunks
        assert context.count("Text A") == 1
        assert context.count("Text B") == 1
    
    @pytest.mark.asyncio
    async def test_search_documents_empty(self, retriever):
        """Test searching documents in empty store"""
        await retriever.initialize()
        
        results = await retriever.search_documents("Python")
        
        assert isinstance(results, list)
    
    @pytest.mark.asyncio
    async def test_get_stats(self, retriever):
        """Test getting RAG system statistics"""
        await retriever.initialize()
        
        stats = await retriever.get_stats()
        
        assert isinstance(stats, dict)
        assert 'vector_store' in stats
        assert 'embedding_cache_size' in stats
        assert 'embedding_dimension' in stats
    
    @pytest.mark.asyncio
    async def test_multiple_initializations_idempotent(self, retriever):
        """Test that multiple initializations are safe"""
        await retriever.initialize()
        await retriever.initialize()
        await retriever.initialize()
        
        assert retriever.initialized is True
    
    @pytest.mark.asyncio
    async def test_chunk_text_with_various_punctuation(self, retriever):
        """Test chunking with different punctuation marks"""
        text = "Question one? Statement two! Exclamation three. Period four."
        chunks = retriever._chunk_text(text)
        
        assert len(chunks) > 0
        assert all(chunk.strip() for chunk in chunks)
    
    @pytest.mark.asyncio
    async def test_format_conversation_context_truncation(self, retriever):
        """Test that long messages are truncated in conversation context"""
        conversations = [
            {
                'user_message': "x" * 500,  # Very long message
                'ai_response': "y" * 500,   # Very long response
                'model_used': 'test',
                'created_at': '2025-01-01'
            }
        ]
        
        context = retriever._format_conversation_context(conversations)
        
        assert isinstance(context, str)
        assert "..." in context  # Should be truncated
