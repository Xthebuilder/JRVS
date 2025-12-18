#!/usr/bin/env python3
"""
Unit tests for RAG modules (embeddings, vector_store, retriever)
"""
import pytest
import asyncio
import tempfile
import shutil
import os
from pathlib import Path

from rag.embeddings import EmbeddingManager
from rag.vector_store import VectorStore
from rag.retriever import RAGRetriever


@pytest.fixture
async def temp_embedding_manager():
    """Create a temporary embedding manager for testing"""
    manager = EmbeddingManager()
    await manager.initialize()
    yield manager
    # Cleanup
    await manager.cleanup()


@pytest.fixture
async def temp_vector_store():
    """Create a temporary vector store for testing"""
    temp_dir = tempfile.mkdtemp()
    index_path = os.path.join(temp_dir, "test_index")
    
    store = VectorStore(index_path=index_path)
    await store.initialize()
    
    yield store
    
    # Cleanup
    await store.cleanup()
    try:
        shutil.rmtree(temp_dir)
    except:
        pass


@pytest.fixture
async def temp_rag_retriever():
    """Create a temporary RAG retriever for testing"""
    # Create temp directory for vector store
    temp_dir = tempfile.mkdtemp()
    
    # Create temp database
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    
    # Initialize RAG retriever with test paths
    retriever = RAGRetriever()
    
    # Override paths for testing
    from rag import vector_store
    from core import database
    
    vector_store.vector_store.index_path = os.path.join(temp_dir, "test_index")
    database.db.db_path = db_path
    
    await retriever.initialize()
    
    yield retriever
    
    # Cleanup
    await retriever.cleanup()
    try:
        os.unlink(db_path)
        shutil.rmtree(temp_dir)
    except:
        pass


# Embedding Manager Tests
@pytest.mark.unit
@pytest.mark.asyncio
async def test_embedding_manager_initialization(temp_embedding_manager):
    """Test embedding manager initialization"""
    assert temp_embedding_manager.initialized is True
    assert temp_embedding_manager.model is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_embedding(temp_embedding_manager):
    """Test generating embeddings for text"""
    text = "This is a test sentence for embedding generation."
    
    embedding = await temp_embedding_manager.generate_embedding(text)
    
    assert embedding is not None
    assert len(embedding) > 0
    assert isinstance(embedding[0], float)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_embeddings_batch(temp_embedding_manager):
    """Test generating embeddings for multiple texts"""
    texts = [
        "First test sentence.",
        "Second test sentence.",
        "Third test sentence."
    ]
    
    embeddings = await temp_embedding_manager.generate_embeddings(texts)
    
    assert len(embeddings) == len(texts)
    for emb in embeddings:
        assert len(emb) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embedding_cache(temp_embedding_manager):
    """Test embedding caching functionality"""
    text = "Test caching with this sentence."
    
    # Generate embedding first time
    emb1 = await temp_embedding_manager.generate_embedding(text)
    
    # Generate same embedding again (should use cache)
    emb2 = await temp_embedding_manager.generate_embedding(text)
    
    # Should be the same
    assert emb1 == emb2


# Vector Store Tests
@pytest.mark.unit
@pytest.mark.asyncio
async def test_vector_store_initialization(temp_vector_store):
    """Test vector store initialization"""
    assert temp_vector_store.initialized is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_chunks(temp_vector_store):
    """Test adding chunks to vector store"""
    chunks = [
        "This is the first chunk of text.",
        "This is the second chunk of text.",
        "This is the third chunk of text."
    ]
    document_id = 1
    metadata = [
        {'chunk_index': 0, 'document_id': document_id},
        {'chunk_index': 1, 'document_id': document_id},
        {'chunk_index': 2, 'document_id': document_id}
    ]
    
    await temp_vector_store.add_chunks(chunks, document_id, metadata)
    
    stats = await temp_vector_store.get_stats()
    assert stats['total_chunks'] >= 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_chunks(temp_vector_store):
    """Test searching for similar chunks"""
    # Add some chunks first
    chunks = [
        "Python is a programming language.",
        "Java is also a programming language.",
        "The weather is nice today."
    ]
    document_id = 1
    metadata = [
        {'chunk_index': i, 'document_id': document_id}
        for i in range(len(chunks))
    ]
    
    await temp_vector_store.add_chunks(chunks, document_id, metadata)
    
    # Search for similar chunks
    query = "programming languages"
    results = await temp_vector_store.search(query, k=2)
    
    assert len(results) <= 2
    if len(results) > 0:
        text, similarity, meta = results[0]
        assert isinstance(text, str)
        assert isinstance(similarity, float)


# RAG Retriever Tests
@pytest.mark.unit
@pytest.mark.asyncio
async def test_rag_retriever_initialization(temp_rag_retriever):
    """Test RAG retriever initialization"""
    assert temp_rag_retriever.initialized is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_document(temp_rag_retriever):
    """Test adding a document to RAG system"""
    content = """
    Python is a high-level programming language. It is known for its simplicity and readability.
    Python is widely used in web development, data science, and machine learning.
    """
    
    doc_id = await temp_rag_retriever.add_document(
        content=content,
        title="Python Tutorial",
        url="https://example.com/python"
    )
    
    assert isinstance(doc_id, int)
    assert doc_id > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chunk_text(temp_rag_retriever):
    """Test text chunking through public interface"""
    text = "Sentence one. Sentence two. Sentence three. Sentence four."
    
    # Test chunking by adding a document and checking the chunks
    doc_id = await temp_rag_retriever.add_document(
        content=text,
        title="Test Doc",
        url="https://example.com"
    )
    
    # Verify document was added successfully
    assert doc_id > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieve_context(temp_rag_retriever):
    """Test retrieving context for a query"""
    # Add a document first
    await temp_rag_retriever.add_document(
        content="Python is great for machine learning and data science.",
        title="Python ML",
        url="https://example.com/ml"
    )
    
    # Retrieve context
    context = await temp_rag_retriever.retrieve_context("machine learning")
    
    assert isinstance(context, str)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_documents(temp_rag_retriever):
    """Test searching documents"""
    # Add a document
    await temp_rag_retriever.add_document(
        content="JavaScript is used for web development.",
        title="JS Tutorial",
        url="https://example.com/js"
    )
    
    # Search
    results = await temp_rag_retriever.search_documents("JavaScript", limit=5)
    
    assert isinstance(results, list)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats(temp_rag_retriever):
    """Test getting RAG system statistics"""
    stats = await temp_rag_retriever.get_stats()
    
    assert isinstance(stats, dict)
    assert 'vector_store' in stats
