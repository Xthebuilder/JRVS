#!/usr/bin/env python3
"""
Integration tests for JRVS
"""
import pytest
import asyncio
import tempfile
import os
from pathlib import Path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_document_flow():
    """Test end-to-end flow: add document, retrieve context"""
    from rag.retriever import RAGRetriever
    from core.database import Database
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    
    try:
        # Initialize components
        db = Database(db_path)
        await db.initialize()
        
        retriever = RAGRetriever()
        await retriever.initialize()
        
        # Add a document
        doc_id = await retriever.add_document(
            content="Machine learning is a subset of artificial intelligence.",
            title="ML Tutorial",
            url="https://example.com/ml"
        )
        
        assert doc_id > 0
        
        # Retrieve context
        context = await retriever.retrieve_context("machine learning")
        
        assert isinstance(context, str)
        
        # Cleanup
        await retriever.cleanup()
        
    finally:
        try:
            os.unlink(db_path)
        except:
            pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_and_calendar_integration():
    """Test integration between database and calendar"""
    from core.database import Database
    from core.calendar import Calendar
    from datetime import datetime
    
    # Create temporary databases
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        cal_path = f.name
    
    try:
        db = Database(db_path)
        await db.initialize()
        
        cal = Calendar(cal_path)
        await cal.initialize()
        
        # Add an event
        event_id = await cal.add_event(
            title="Test Event",
            event_date=datetime.now(),
            description="Integration test event"
        )
        
        assert event_id > 0
        
        # Get events
        events = await cal.get_today_events()
        assert len(events) >= 1
        
    finally:
        try:
            os.unlink(db_path)
            os.unlink(cal_path)
        except:
            pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rag_with_multiple_documents():
    """Test RAG with multiple documents"""
    from rag.retriever import RAGRetriever
    
    retriever = RAGRetriever()
    
    try:
        await retriever.initialize()
        
        # Add multiple documents
        docs = [
            ("Python is great for data science.", "Python DS", "https://example.com/1"),
            ("JavaScript is used for web development.", "JS Web", "https://example.com/2"),
            ("Machine learning uses algorithms.", "ML Intro", "https://example.com/3")
        ]
        
        for content, title, url in docs:
            await retriever.add_document(content, title, url)
        
        # Search for documents
        results = await retriever.search_documents("Python", limit=5)
        
        assert len(results) >= 1
        
    finally:
        await retriever.cleanup()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conversation_memory():
    """Test conversation memory across multiple interactions"""
    from core.database import Database
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    
    try:
        db = Database(db_path)
        await db.initialize()
        
        session_id = "test_session_memory"
        
        # Add multiple conversations
        conversations = [
            ("Hello", "Hi there!", "llama3.1"),
            ("How are you?", "I'm doing well!", "llama3.1"),
            ("Tell me about Python", "Python is a programming language.", "llama3.1")
        ]
        
        for user_msg, ai_resp, model in conversations:
            await db.add_conversation(session_id, user_msg, ai_resp, model)
        
        # Retrieve conversation history
        history = await db.get_recent_conversations(session_id, limit=3)
        
        assert len(history) == 3
        
    finally:
        try:
            os.unlink(db_path)
        except:
            pass
