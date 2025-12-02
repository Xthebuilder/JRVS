#!/usr/bin/env python3
"""
JRVS MCP Server - Enhanced Production-Ready Version

A robust, production-ready MCP server with:
- Comprehensive error handling and retry mechanisms
- Caching for improved performance
- Rate limiting and resource management
- Authentication and authorization
- Health checks and monitoring
- Graceful shutdown
- Structured logging and metrics

Usage:
    python mcp/server_enhanced.py

Or with custom config:
    python mcp/server_enhanced.py --config config.json
"""

import sys
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

# Import MCP first
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP package not installed. Install with: pip install 'mcp[cli]'")
    sys.exit(1)

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import JRVS components
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from core.database import db
from core.calendar import calendar
from scraper.web_scraper import web_scraper

# Import enhanced MCP components
from mcp.exceptions import *
from mcp.logging_config import setup_logging, get_logger, RequestContext
from mcp.metrics import metrics, metrics_monitor_task, RequestMetrics
from mcp.cache import cache_manager, cached, cache_cleanup_task
from mcp.resilience import (
    retry, timeout, CircuitBreaker,
    ollama_circuit, rag_circuit, scraper_circuit,
    embedding_bulkhead, scraping_bulkhead, ollama_bulkhead
)
from mcp.rate_limiter import rate_limiter, resource_manager
from mcp.health import health_checker, register_default_checks, health_monitor_task
from mcp.auth import auth_manager, setup_development_keys
from mcp.config_manager import config_manager
from mcp.shutdown import shutdown_handler, register_default_cleanup_tasks

# Initialize logging
logger = get_logger(__name__)

# Initialize MCP server
mcp = FastMCP("JRVS-Enhanced")

# ============================================================================
# Helper Functions
# ============================================================================

def track_request(tool_name: str):
    """Decorator to track request metrics"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            request_id = str(uuid.uuid4())
            request_ctx = RequestContext(
                request_id=request_id,
                tool_name=tool_name,
                client_id="unknown"  # Would come from auth
            )

            start_time = datetime.utcnow()
            success = False
            error_type = None

            try:
                # Check rate limit
                rate_limiter.check_rate_limit("default")

                # Acquire resource slot
                resource_manager.acquire_request_slot(request_id)

                # Execute function
                result = await func(*args, **kwargs)
                success = True

                return result

            except RateLimitExceededError as e:
                error_type = "RateLimitExceeded"
                logger.warning(f"Rate limit exceeded for {tool_name}")
                raise

            except Exception as e:
                error_type = type(e).__name__
                logger.error(f"Error in {tool_name}: {e}", exc_info=True)
                raise

            finally:
                # Release resource slot
                resource_manager.release_request_slot(request_id)

                # Record metrics
                duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

                request_metrics = RequestMetrics(
                    tool_name=tool_name,
                    success=success,
                    duration_ms=duration_ms,
                    timestamp=datetime.utcnow(),
                    error_type=error_type
                )
                metrics.record_request(request_metrics)

                # Log completion
                request_ctx.log_completion(
                    logger,
                    success=success,
                    error=error_type
                )

        return wrapper
    return decorator


# ============================================================================
# RAG & Knowledge Base Tools (Enhanced)
# ============================================================================

@mcp.tool()
@track_request("search_knowledge_base")
@cached(cache_type="rag", ttl=600)
@retry(max_attempts=3, delay=1.0, exceptions=(VectorStoreError,))
@timeout(30)
async def search_knowledge_base(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search JRVS's knowledge base using semantic vector search.

    Enhanced with caching, retry logic, and timeout protection.
    """
    try:
        await rag_retriever.initialize()

        results = await rag_circuit.call_async(
            rag_retriever.search_documents,
            query,
            limit=limit
        )

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
    except Exception as e:
        logger.error(f"Knowledge base search failed: {e}")
        raise RAGException(f"Search failed: {str(e)}")


@mcp.tool()
@track_request("get_context_for_query")
@cached(cache_type="rag", ttl=300)
@retry(max_attempts=2, delay=1.0)
@timeout(45)
async def get_context_for_query(query: str, session_id: Optional[str] = None) -> str:
    """
    Get enriched context from JRVS's RAG system for a given query.
    Enhanced with caching and error handling.
    """
    try:
        await rag_retriever.initialize()

        context = await rag_circuit.call_async(
            rag_retriever.retrieve_context,
            query,
            session_id=session_id
        )

        return context if context else "No relevant context found."

    except Exception as e:
        logger.error(f"Context retrieval failed: {e}")
        raise RAGException(f"Context retrieval failed: {str(e)}")


@mcp.tool()
@track_request("add_document_to_knowledge_base")
@timeout(120)
async def add_document_to_knowledge_base(
    content: str,
    title: str = "Untitled Document",
    url: str = "",
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Add a document to JRVS's knowledge base.
    Enhanced with bulkhead limiting for embedding generation.
    """
    try:
        await rag_retriever.initialize()

        # Use bulkhead to limit concurrent embedding operations
        doc_id = await embedding_bulkhead.execute(
            rag_retriever.add_document,
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

    except Exception as e:
        logger.error(f"Document indexing failed: {e}")
        raise RAGException(f"Failed to add document: {str(e)}")


@mcp.tool()
@track_request("scrape_and_index_url")
@retry(max_attempts=3, delay=2.0, backoff=2.0)
@timeout(90)
async def scrape_and_index_url(url: str) -> Dict[str, Any]:
    """
    Scrape a website and add to knowledge base.
    Enhanced with retry, timeout, and circuit breaker.
    """
    try:
        # Use bulkhead to limit concurrent scraping
        doc_id = await scraping_bulkhead.execute(
            lambda: scraper_circuit.call_async(
                web_scraper.scrape_and_store,
                url
            )
        )

        if doc_id:
            return {
                "success": True,
                "document_id": doc_id,
                "url": url,
                "message": f"Successfully scraped and indexed {url}"
            }
        else:
            raise URLFetchError(url=url)

    except Exception as e:
        logger.error(f"URL scraping failed for {url}: {e}")
        return {
            "success": False,
            "url": url,
            "error": str(e),
            "message": f"Error scraping URL: {e}"
        }


@mcp.tool()
@track_request("get_rag_stats")
async def get_rag_stats() -> Dict[str, Any]:
    """Get RAG system statistics"""
    try:
        await rag_retriever.initialize()
        stats = await rag_retriever.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get RAG stats: {e}")
        raise RAGException(f"Stats retrieval failed: {str(e)}")


# ============================================================================
# Ollama LLM Tools (Enhanced)
# ============================================================================

@mcp.tool()
@track_request("list_ollama_models")
@cached(cache_type="ollama", ttl=60)
@retry(max_attempts=2, delay=1.0)
@timeout(10)
async def list_ollama_models() -> List[Dict[str, Any]]:
    """List available Ollama models with caching"""
    try:
        models = await ollama_circuit.call_async(
            ollama_client.list_models
        )

        return [
            {
                "name": m["name"],
                "current": m["current"],
                "size_bytes": m["size"],
                "modified_at": m["modified_at"]
            }
            for m in models
        ]
    except Exception as e:
        logger.error(f"Failed to list Ollama models: {e}")
        raise OllamaConnectionError(url=ollama_client.base_url, original_error=e)


@mcp.tool()
@track_request("get_current_model")
async def get_current_model() -> Dict[str, str]:
    """Get currently active Ollama model"""
    return {
        "model": ollama_client.current_model,
        "ollama_url": ollama_client.base_url
    }


@mcp.tool()
@track_request("switch_ollama_model")
@retry(max_attempts=2, delay=1.0)
async def switch_ollama_model(model_name: str) -> Dict[str, Any]:
    """Switch to a different Ollama model"""
    try:
        success = await ollama_circuit.call_async(
            ollama_client.switch_model,
            model_name
        )

        return {
            "success": success,
            "model": ollama_client.current_model if success else None,
            "message": f"Switched to {ollama_client.current_model}" if success else f"Failed to switch to {model_name}"
        }
    except Exception as e:
        logger.error(f"Model switch failed: {e}")
        raise OllamaModelNotFoundError(model_name=model_name)


@mcp.tool()
@track_request("generate_with_ollama")
@timeout(300)
async def generate_with_ollama(
    prompt: str,
    context: Optional[str] = None,
    system_prompt: Optional[str] = None
) -> str:
    """
    Generate response using Ollama LLM.
    Enhanced with circuit breaker and bulkhead.
    """
    try:
        # Get context from RAG if not provided
        if context is None:
            await rag_retriever.initialize()
            context = await rag_retriever.retrieve_context(prompt)

        # Use bulkhead to limit concurrent Ollama requests
        response = await ollama_bulkhead.execute(
            lambda: ollama_circuit.call_async(
                ollama_client.generate,
                prompt=prompt,
                context=context,
                system_prompt=system_prompt,
                stream=False
            )
        )

        return response if response else "Failed to generate response."

    except Exception as e:
        logger.error(f"Ollama generation failed: {e}")
        raise OllamaGenerationError(message=str(e), model=ollama_client.current_model)


# ============================================================================
# Calendar Tools (Enhanced)
# ============================================================================

@mcp.tool()
@track_request("get_calendar_events")
@cached(cache_type="general", ttl=300)
async def get_calendar_events(days: int = 7) -> List[Dict[str, Any]]:
    """Get upcoming calendar events with caching"""
    try:
        await calendar.initialize()
        events = await calendar.get_upcoming_events(days=days)
        return events
    except Exception as e:
        logger.error(f"Failed to get calendar events: {e}")
        raise CalendarException(f"Failed to retrieve events: {str(e)}")


@mcp.tool()
@track_request("get_today_events")
@cached(cache_type="general", ttl=60)
async def get_today_events() -> List[Dict[str, Any]]:
    """Get today's events with caching"""
    try:
        await calendar.initialize()
        events = await calendar.get_today_events()
        return events
    except Exception as e:
        logger.error(f"Failed to get today's events: {e}")
        raise CalendarException(f"Failed to retrieve today's events: {str(e)}")


@mcp.tool()
@track_request("create_calendar_event")
async def create_calendar_event(
    title: str,
    event_date: str,
    description: str = "",
    reminder_minutes: int = 0
) -> Dict[str, Any]:
    """Create calendar event with validation"""
    from datetime import datetime

    try:
        await calendar.initialize()

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
    except ValueError as e:
        raise InvalidEventDateError(date_str=event_date, expected_format="ISO format (YYYY-MM-DDTHH:MM:SS)")
    except Exception as e:
        logger.error(f"Event creation failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to create event: {e}"
        }


@mcp.tool()
@track_request("delete_calendar_event")
async def delete_calendar_event(event_id: int) -> Dict[str, Any]:
    """Delete calendar event"""
    try:
        await calendar.initialize()
        await calendar.delete_event(event_id)
        return {
            "success": True,
            "event_id": event_id,
            "message": f"Deleted event {event_id}"
        }
    except Exception as e:
        logger.error(f"Event deletion failed: {e}")
        raise EventNotFoundError(event_id=event_id)


@mcp.tool()
@track_request("mark_event_completed")
async def mark_event_completed(event_id: int) -> Dict[str, Any]:
    """Mark event as completed"""
    try:
        await calendar.initialize()
        await calendar.mark_completed(event_id)
        return {
            "success": True,
            "event_id": event_id,
            "message": f"Marked event {event_id} as completed"
        }
    except Exception as e:
        logger.error(f"Failed to mark event completed: {e}")
        raise EventNotFoundError(event_id=event_id)


# ============================================================================
# Conversation History Tools
# ============================================================================

@mcp.tool()
@track_request("get_conversation_history")
@cached(cache_type="general", ttl=60)
async def get_conversation_history(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get conversation history with caching"""
    try:
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
    except Exception as e:
        logger.error(f"Failed to get conversation history: {e}")
        raise JRVSMCPException(f"Failed to retrieve conversation history: {str(e)}")


# ============================================================================
# Monitoring & Health Check Tools
# ============================================================================

@mcp.tool()
async def get_health_status() -> Dict[str, Any]:
    """Get comprehensive health status of all components"""
    try:
        await health_checker.check_all()
        return health_checker.get_health_report()
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@mcp.tool()
async def get_metrics() -> Dict[str, Any]:
    """Get performance metrics and statistics"""
    try:
        return metrics.get_summary()
    except Exception as e:
        logger.error(f"Metrics retrieval failed: {e}")
        return {"error": str(e)}


@mcp.tool()
async def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    try:
        return cache_manager.get_all_stats()
    except Exception as e:
        logger.error(f"Cache stats retrieval failed: {e}")
        return {"error": str(e)}


@mcp.tool()
async def get_rate_limit_stats() -> Dict[str, Any]:
    """Get rate limiting statistics"""
    try:
        return {
            "rate_limiter": rate_limiter.get_stats(),
            "resource_manager": resource_manager.get_stats()
        }
    except Exception as e:
        logger.error(f"Rate limit stats retrieval failed: {e}")
        return {"error": str(e)}


# ============================================================================
# Admin Tools
# ============================================================================

@mcp.tool()
async def clear_cache(cache_type: Optional[str] = None) -> Dict[str, str]:
    """Clear cache (all or specific type)"""
    try:
        if cache_type:
            cache = cache_manager.get_cache(cache_type)
            cache.clear()
            return {"message": f"Cleared {cache_type} cache"}
        else:
            cache_manager.clear_all()
            return {"message": "Cleared all caches"}
    except Exception as e:
        logger.error(f"Cache clear failed: {e}")
        return {"error": str(e)}


# ============================================================================
# Resources
# ============================================================================

@mcp.resource("jrvs://config")
def get_jrvs_config() -> str:
    """Get JRVS configuration"""
    config = config_manager.config
    return f"""JRVS Enhanced MCP Server Configuration:
- Ollama URL: {config.ollama.base_url}
- Default Model: {config.ollama.default_model}
- Current Model: {ollama_client.current_model}
- Cache Enabled: {config.cache.enabled}
- Rate Limiting: {config.rate_limit.enabled}
- Auth Enabled: {config.auth.enabled}
- Log Level: {config.server.log_level.value}
"""


@mcp.resource("jrvs://status")
async def get_jrvs_status() -> str:
    """Get comprehensive system status"""
    try:
        health_report = await get_health_status()
        metrics_summary = metrics.get_summary()

        status_lines = ["JRVS Enhanced MCP Server Status", "=" * 70]

        # Health status
        status_lines.append(f"\nOverall Health: {health_report.get('status', 'unknown').upper()}")

        # Component health
        if 'components' in health_report:
            status_lines.append("\nComponents:")
            for name, component in health_report['components'].items():
                status = component.get('status', 'unknown')
                message = component.get('message', '')
                status_lines.append(f"  - {name}: {status} - {message}")

        # Metrics
        if 'requests' in metrics_summary:
            req = metrics_summary['requests']
            status_lines.append(f"\nRequests:")
            status_lines.append(f"  Total: {req.get('total_requests', 0)}")
            status_lines.append(f"  Success Rate: {req.get('success_rate', 0)}%")

        # Uptime
        uptime = metrics_summary.get('uptime_seconds', 0)
        status_lines.append(f"\nUptime: {uptime:.2f}s ({uptime/60:.2f}m)")

        return "\n".join(status_lines)

    except Exception as e:
        return f"Error getting status: {e}"


# ============================================================================
# Server Initialization and Lifecycle
# ============================================================================

async def initialize_server():
    """Initialize all server components"""
    logger.info("="* 70)
    logger.info("JRVS ENHANCED MCP SERVER - INITIALIZATION")
    logger.info("=" * 70)

    # Load configuration
    try:
        config_manager.load_config()
        logger.info(f"Configuration loaded: {config_manager.get_summary()}")
    except Exception as e:
        logger.warning(f"Config load failed, using defaults: {e}")

    config = config_manager.config

    # Setup authentication (development mode)
    if config.auth.development_mode:
        setup_development_keys()

    # Initialize JRVS core components
    try:
        await db.initialize()
        logger.info("✓ Database initialized")

        await rag_retriever.initialize()
        logger.info("✓ RAG system initialized")

        await calendar.initialize()
        logger.info("✓ Calendar initialized")

        await ollama_client.discover_models()
        logger.info(f"✓ Ollama connected - {len(await ollama_client.list_models())} models available")

    except Exception as e:
        logger.warning(f"Some components failed to initialize: {e}")

    # Register health checks
    register_default_checks()
    logger.info("✓ Health checks registered")

    # Register cleanup tasks
    register_default_cleanup_tasks()
    logger.info("✓ Cleanup tasks registered")

    # Setup signal handlers
    shutdown_handler.setup_signal_handlers()
    logger.info("✓ Signal handlers configured")

    # Start background tasks
    if config.monitoring.enabled:
        asyncio.create_task(metrics_monitor_task(config.monitoring.metrics_interval_seconds))
        asyncio.create_task(health_monitor_task(config.monitoring.health_check_interval_seconds))
        logger.info("✓ Monitoring tasks started")

    if config.cache.enabled:
        asyncio.create_task(cache_cleanup_task(config.cache.cleanup_interval_seconds))
        logger.info("✓ Cache cleanup task started")

    logger.info("=" * 70)
    logger.info("SERVER READY")
    logger.info("=" * 70)


async def main():
    """Main entry point"""
    # Setup logging
    setup_logging(
        level="INFO",
        log_file="logs/jrvs-mcp-enhanced.log",
        json_logs=True
    )

    logger.info("Starting JRVS Enhanced MCP Server...")

    try:
        # Initialize server
        await initialize_server()

        # Run MCP server
        await mcp.run()

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        await shutdown_handler.shutdown()

    except Exception as e:
        logger.critical(f"Fatal server error: {e}", exc_info=True)
        await shutdown_handler.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
