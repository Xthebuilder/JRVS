#!/usr/bin/env python3
"""
JRVS MCP Server - Model Context Protocol server for Jarvis AI Agent

This server exposes JRVS capabilities (RAG, web scraping, calendar, Ollama models)
as MCP tools that can be used by any MCP-compatible client.

Usage:
    python mcp/server.py

Or with uv:
    uv run mcp/server.py
"""

import sys
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

# Import MCP first (before modifying sys.path)
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP package not installed. Install with: pip install 'mcp[cli]'")
    sys.exit(1)

# Add project root to path for JRVS components
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import JRVS components
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from core.database import db
from core.calendar import calendar
from scraper.web_scraper import web_scraper
from mcp_gateway.coding_agent import jarcore
from config import OLLAMA_BASE_URL, DEFAULT_MODEL

# Initialize MCP server
mcp = FastMCP("JRVS")

# ============================================================================
# RAG & Knowledge Base Tools
# ============================================================================

@mcp.tool()
async def search_knowledge_base(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search JRVS's knowledge base using semantic vector search.

    Args:
        query: Search query text
        limit: Maximum number of results to return (default: 5)

    Returns:
        List of documents with title, URL, similarity score, and preview
    """
    await rag_retriever.initialize()
    results = await rag_retriever.search_documents(query, limit=limit)

    return [
        {
            "document_id": r["document_id"],
            "title": r["title"],
            "url": r["url"],
            "similarity": round(r["similarity"], 4),
            "preview": r["preview"]
        }
        for r in results
    ]


@mcp.tool()
async def get_context_for_query(query: str, session_id: Optional[str] = None) -> str:
    """
    Get enriched context from JRVS's RAG system for a given query.
    Includes relevant document chunks and recent conversation history.

    Args:
        query: The query to get context for
        session_id: Optional session ID to include conversation history

    Returns:
        Formatted context string with relevant information
    """
    await rag_retriever.initialize()
    context = await rag_retriever.retrieve_context(query, session_id=session_id)

    return context if context else "No relevant context found."


@mcp.tool()
async def add_document_to_knowledge_base(
    content: str,
    title: str = "Untitled Document",
    url: str = "",
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Add a document to JRVS's knowledge base for future retrieval.
    The document will be chunked, embedded, and indexed.

    Args:
        content: The text content of the document
        title: Document title
        url: Optional source URL
        metadata: Optional metadata dictionary

    Returns:
        Document info including ID and number of chunks created
    """
    await rag_retriever.initialize()

    doc_id = await rag_retriever.add_document(
        content=content,
        title=title,
        url=url,
        metadata=metadata or {}
    )

    return {
        "document_id": doc_id,
        "title": title,
        "status": "indexed",
        "message": f"Document '{title}' added to knowledge base"
    }


@mcp.tool()
async def scrape_and_index_url(url: str) -> Dict[str, Any]:
    """
    Scrape a website and add its content to JRVS's knowledge base.

    Args:
        url: The URL to scrape

    Returns:
        Result with document ID and scraping status
    """
    try:
        doc_id = await web_scraper.scrape_and_store(url)

        if doc_id:
            return {
                "success": True,
                "document_id": doc_id,
                "url": url,
                "message": f"Successfully scraped and indexed {url}"
            }
        else:
            return {
                "success": False,
                "url": url,
                "message": "Failed to scrape URL"
            }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "error": str(e),
            "message": f"Error scraping URL: {e}"
        }


@mcp.tool()
async def get_rag_stats() -> Dict[str, Any]:
    """
    Get statistics about JRVS's RAG system.

    Returns:
        Stats including vector store size, embedding cache, etc.
    """
    await rag_retriever.initialize()
    stats = await rag_retriever.get_stats()

    return stats


# ============================================================================
# Ollama LLM Tools
# ============================================================================

@mcp.tool()
async def list_ollama_models() -> List[Dict[str, Any]]:
    """
    List all available Ollama models in JRVS.

    Returns:
        List of models with name, size, and current status
    """
    models = await ollama_client.list_models()

    return [
        {
            "name": m["name"],
            "current": m["current"],
            "size_bytes": m["size"],
            "modified_at": m["modified_at"]
        }
        for m in models
    ]


@mcp.tool()
async def get_current_model() -> Dict[str, str]:
    """
    Get the currently active Ollama model in JRVS.

    Returns:
        Current model name and base URL
    """
    return {
        "model": ollama_client.current_model,
        "ollama_url": ollama_client.base_url
    }


@mcp.tool()
async def switch_ollama_model(model_name: str) -> Dict[str, Any]:
    """
    Switch JRVS to a different Ollama model.

    Args:
        model_name: Name of the model to switch to

    Returns:
        Result with success status and new model name
    """
    success = await ollama_client.switch_model(model_name)

    return {
        "success": success,
        "model": ollama_client.current_model if success else None,
        "message": f"Switched to {ollama_client.current_model}" if success else f"Failed to switch to {model_name}"
    }


@mcp.tool()
async def generate_with_ollama(
    prompt: str,
    context: Optional[str] = None,
    system_prompt: Optional[str] = None
) -> str:
    """
    Generate a response using JRVS's Ollama LLM with optional RAG context.

    Args:
        prompt: The prompt/question
        context: Optional context to inject (will use RAG if not provided)
        system_prompt: Optional system prompt

    Returns:
        Generated response text
    """
    # If no context provided, try to get it from RAG
    if context is None:
        await rag_retriever.initialize()
        context = await rag_retriever.retrieve_context(prompt)

    response = await ollama_client.generate(
        prompt=prompt,
        context=context,
        system_prompt=system_prompt,
        stream=False
    )

    return response if response else "Failed to generate response."


# ============================================================================
# Calendar Tools
# ============================================================================

@mcp.tool()
async def get_calendar_events(days: int = 7) -> List[Dict[str, Any]]:
    """
    Get upcoming calendar events from JRVS.

    Args:
        days: Number of days ahead to retrieve events for (default: 7)

    Returns:
        List of events with title, date, description, and completion status
    """
    await calendar.initialize()
    events = await calendar.get_upcoming_events(days=days)

    return events


@mcp.tool()
async def get_today_events() -> List[Dict[str, Any]]:
    """
    Get today's calendar events from JRVS.

    Returns:
        List of today's events
    """
    await calendar.initialize()
    events = await calendar.get_today_events()

    return events


@mcp.tool()
async def create_calendar_event(
    title: str,
    event_date: str,
    description: str = "",
    reminder_minutes: int = 0
) -> Dict[str, Any]:
    """
    Create a new calendar event in JRVS.

    Args:
        title: Event title
        event_date: Event date/time in ISO format (e.g., "2025-11-15T14:30:00")
        description: Optional event description
        reminder_minutes: Minutes before event to remind (0 = no reminder)

    Returns:
        Event info with ID and success status
    """
    from datetime import datetime

    await calendar.initialize()

    try:
        event_datetime = datetime.fromisoformat(event_date)
        event_id = await calendar.add_event(
            title=title,
            event_date=event_datetime,
            description=description,
            reminder_minutes=reminder_minutes
        )

        return {
            "success": True,
            "event_id": event_id,
            "title": title,
            "event_date": event_date,
            "message": f"Created event: {title}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to create event: {e}"
        }


@mcp.tool()
async def delete_calendar_event(event_id: int) -> Dict[str, Any]:
    """
    Delete a calendar event from JRVS.

    Args:
        event_id: ID of the event to delete

    Returns:
        Success status
    """
    await calendar.initialize()

    try:
        await calendar.delete_event(event_id)
        return {
            "success": True,
            "event_id": event_id,
            "message": f"Deleted event {event_id}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to delete event: {e}"
        }


@mcp.tool()
async def mark_event_completed(event_id: int) -> Dict[str, Any]:
    """
    Mark a calendar event as completed in JRVS.

    Args:
        event_id: ID of the event to mark as completed

    Returns:
        Success status
    """
    await calendar.initialize()

    try:
        await calendar.mark_completed(event_id)
        return {
            "success": True,
            "event_id": event_id,
            "message": f"Marked event {event_id} as completed"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to mark event as completed: {e}"
        }


# ============================================================================
# Conversation History Tools
# ============================================================================

@mcp.tool()
async def get_conversation_history(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get conversation history for a session from JRVS.

    Args:
        session_id: Session ID to retrieve history for
        limit: Maximum number of conversations to return (default: 10)

    Returns:
        List of conversations with user messages and AI responses
    """
    await db.initialize()
    history = await db.get_recent_conversations(session_id=session_id, limit=limit)

    return [
        {
            "timestamp": conv["timestamp"],
            "user_message": conv["user_message"],
            "ai_response": conv["ai_response"],
            "model_used": conv["model_used"]
        }
        for conv in history
    ]


# ============================================================================
# JARCORE - JARVIS Autonomous Reasoning & Coding Engine
# ============================================================================

@mcp.tool()
async def generate_code(
    task: str,
    language: str = "python",
    context: Optional[str] = None,
    include_tests: bool = False
) -> Dict[str, Any]:
    """
    Generate code from natural language using JARCORE (JARVIS coding engine).

    Args:
        task: Natural language description of what the code should do
        language: Programming language (python, javascript, go, rust, etc.)
        context: Optional additional context or requirements
        include_tests: Whether to generate test cases

    Returns:
        Generated code with explanation, dependencies, and usage example
    """
    return await jarcore.generate_code(task, language, context, include_tests)


@mcp.tool()
async def analyze_code(
    code: str,
    language: str = "python",
    analysis_type: str = "comprehensive"
) -> Dict[str, Any]:
    """
    Analyze code for bugs, security issues, performance, and best practices.

    Args:
        code: Code to analyze
        language: Programming language
        analysis_type: "comprehensive", "security", "performance", or "style"

    Returns:
        Analysis with issues, suggestions, and metrics
    """
    return await jarcore.analyze_code(code, language, analysis_type)


@mcp.tool()
async def refactor_code(
    code: str,
    language: str = "python",
    refactor_goal: str = "improve readability and maintainability"
) -> Dict[str, Any]:
    """
    Refactor code according to specified goals using AI.

    Args:
        code: Code to refactor
        language: Programming language
        refactor_goal: What to optimize for

    Returns:
        Refactored code with explanation of changes
    """
    return await jarcore.refactor_code(code, language, refactor_goal)


@mcp.tool()
async def explain_code(
    code: str,
    language: str = "python",
    detail_level: str = "medium"
) -> str:
    """
    Get natural language explanation of code.

    Args:
        code: Code to explain
        language: Programming language
        detail_level: "brief", "medium", or "detailed"

    Returns:
        Natural language explanation
    """
    return await jarcore.explain_code(code, language, detail_level)


@mcp.tool()
async def fix_code_errors(
    code: str,
    error_message: str,
    language: str = "python"
) -> Dict[str, Any]:
    """
    Automatically fix code based on error messages.

    Args:
        code: Code with errors
        error_message: Error message from execution/linting
        language: Programming language

    Returns:
        Fixed code with explanation
    """
    return await jarcore.fix_code_errors(code, error_message, language)


@mcp.tool()
async def read_code_file(file_path: str) -> Dict[str, Any]:
    """
    Read a code file with syntax detection and metadata.

    Args:
        file_path: Path to file (relative to JRVS workspace or absolute)

    Returns:
        File content, detected language, lines, size, and modification time
    """
    return await jarcore.read_file(file_path)


@mcp.tool()
async def write_code_file(
    file_path: str,
    content: str,
    create_dirs: bool = True,
    backup: bool = True
) -> Dict[str, Any]:
    """
    Write code to a file with automatic backup.

    Args:
        file_path: Path to file
        content: Code content to write
        create_dirs: Create parent directories if needed
        backup: Create backup of existing file

    Returns:
        Write operation result with path and statistics
    """
    return await jarcore.write_file(file_path, content, create_dirs, backup)


@mcp.tool()
async def execute_code(
    code: str,
    language: str = "python",
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Execute code safely and return results.

    Args:
        code: Code to execute
        language: Programming language (python, bash, javascript supported)
        timeout: Execution timeout in seconds

    Returns:
        Execution results including output, errors, and exit code
    """
    return await jarcore.execute_code(code, language, timeout)


@mcp.tool()
async def generate_tests(
    code: str,
    language: str = "python",
    test_framework: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate comprehensive unit tests for code.

    Args:
        code: Code to generate tests for
        language: Programming language
        test_framework: Specific test framework (pytest, jest, etc.)

    Returns:
        Generated test code with setup instructions
    """
    return await jarcore.generate_tests(code, language, test_framework)


@mcp.tool()
async def get_code_completion(
    partial_code: str,
    language: str = "python",
    cursor_position: Optional[int] = None
) -> List[str]:
    """
    Get intelligent code completion suggestions.

    Args:
        partial_code: Code written so far
        language: Programming language
        cursor_position: Position where completion is needed

    Returns:
        List of completion suggestions
    """
    return await jarcore.code_completion(partial_code, cursor_position, language)


@mcp.tool()
async def get_edit_history(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent code editing history from JARCORE.

    Args:
        limit: Maximum number of edits to return

    Returns:
        List of recent edit operations with timestamps
    """
    return jarcore.get_edit_history(limit)


# ============================================================================
# Resources (data endpoints)
# ============================================================================

@mcp.resource("jrvs://config")
def get_jrvs_config() -> str:
    """Get JRVS configuration information"""
    return f"""JRVS Configuration:
- Ollama URL: {OLLAMA_BASE_URL}
- Default Model: {DEFAULT_MODEL}
- Current Model: {ollama_client.current_model}
- Database Path: {db.db_path if hasattr(db, 'db_path') else 'N/A'}
"""


@mcp.resource("jrvs://status")
async def get_jrvs_status() -> str:
    """Get JRVS system status"""
    try:
        # Check Ollama connection
        models = await ollama_client.discover_models()
        ollama_status = f"✓ Connected ({len(models)} models available)"
    except Exception as e:
        ollama_status = f"✗ Error: {e}"

    try:
        # Check RAG system
        await rag_retriever.initialize()
        stats = await rag_retriever.get_stats()
        rag_status = f"✓ Initialized (Vector store size: {stats.get('vector_store', {}).get('total_vectors', 0)})"
    except Exception as e:
        rag_status = f"✗ Error: {e}"

    return f"""JRVS System Status:
- Ollama: {ollama_status}
- RAG System: {rag_status}
- Current Model: {ollama_client.current_model}
"""


# ============================================================================
# Server Entry Point
# ============================================================================

async def main():
    """Main entry point for MCP server"""
    print("Starting JRVS MCP Server...", file=sys.stderr)
    print(f"Ollama URL: {OLLAMA_BASE_URL}", file=sys.stderr)
    print(f"Default Model: {DEFAULT_MODEL}", file=sys.stderr)

    # Initialize JRVS components
    try:
        await db.initialize()
        await rag_retriever.initialize()
        await calendar.initialize()
        await ollama_client.discover_models()
        print("✓ JRVS components initialized", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Some components failed to initialize: {e}", file=sys.stderr)

    # Run MCP server
    print("✓ MCP server ready", file=sys.stderr)
    await mcp.run()


if __name__ == "__main__":
    asyncio.run(main())
