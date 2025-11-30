#!/usr/bin/env python3
"""Quick test to verify MCP server tools are working"""

import sys
import asyncio
from pathlib import Path

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def test_tools():
    """Test basic MCP tool functionality"""
    print("Testing JRVS MCP Server Tools...\n")

    # Import after path setup
    from llm.ollama_client import ollama_client
    from rag.retriever import rag_retriever
    from core.database import db
    from core.calendar import calendar

    results = []

    # Test 1: Database initialization
    try:
        await db.initialize()
        results.append(("✓", "Database initialized"))
    except Exception as e:
        results.append(("✗", f"Database failed: {e}"))

    # Test 2: RAG system
    try:
        await rag_retriever.initialize()
        stats = await rag_retriever.get_stats()
        results.append(("✓", f"RAG initialized (vectors: {stats.get('vector_store', {}).get('total_vectors', 0)})"))
    except Exception as e:
        results.append(("✗", f"RAG failed: {e}"))

    # Test 3: Calendar
    try:
        await calendar.initialize()
        events = await calendar.get_upcoming_events(days=7)
        results.append(("✓", f"Calendar initialized ({len(events)} events)"))
    except Exception as e:
        results.append(("✗", f"Calendar failed: {e}"))

    # Test 4: Ollama connection
    try:
        models = await ollama_client.discover_models()
        if models:
            results.append(("✓", f"Ollama connected ({len(models)} models)"))
        else:
            results.append(("⚠", "Ollama connected but no models found"))
    except Exception as e:
        results.append(("⚠", f"Ollama not available: {e}"))

    # Print results
    print("\nTest Results:")
    print("-" * 60)
    for status, message in results:
        print(f"{status} {message}")

    # Summary
    passed = sum(1 for s, _ in results if s == "✓")
    failed = sum(1 for s, _ in results if s == "✗")
    warnings = sum(1 for s, _ in results if s == "⚠")

    print("-" * 60)
    print(f"Passed: {passed} | Failed: {failed} | Warnings: {warnings}")

    if failed == 0:
        print("\n✓ MCP server components are ready!")
        return True
    else:
        print("\n✗ Some components failed. Check errors above.")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_tools())
    sys.exit(0 if success else 1)
