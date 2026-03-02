"""FastAPI server for Jarvis AI Agent"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio
import logging
import os
import uuid
from datetime import datetime

# Import Jarvis components
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging_setup import setup_logging
setup_logging()

log = logging.getLogger(__name__)

from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from core.database import db
from core.calendar import calendar
from core.calendar_parser import parse_calendar_request
from scraper.web_scraper import web_scraper
from config import CONVERSATION_HISTORY_TURNS
from google_integration.client import google_workspace

# CORS origins — restrict to configured origins in production
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    if o.strip()
]

# Per-session in-memory conversation history (within server lifetime)
# Maps session_id → list of {"user": str, "assistant": str} dicts
_session_histories: Dict[str, List[Dict]] = {}

# Background task registry — lets us await / cancel them on shutdown
_background_tasks: set = set()


def _create_task(coro) -> asyncio.Task:
    """Create a tracked background task that removes itself from the registry on completion."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    await db.initialize()
    await calendar.initialize()
    await rag_retriever.initialize()
    await ollama_client.discover_models()
    # Backfill any conversation turns not yet embedded in FAISS (e.g. from a previous crash)
    _create_task(rag_retriever.embed_pending_conversations())
    yield
    # Graceful shutdown: wait up to 10s for background tasks then cancel
    if _background_tasks:
        log.info("Waiting for %d background task(s) to finish…", len(_background_tasks))
        done, pending = await asyncio.wait(_background_tasks, timeout=10)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="Jarvis AI API", version="1.0.0", lifespan=lifespan)

# CORS for frontend — set ALLOWED_ORIGINS env var to restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = False

class ChatResponse(BaseModel):
    response: str
    session_id: str
    model_used: str
    context_used: Optional[str] = None

class EventRequest(BaseModel):
    title: str
    event_date: str  # ISO format: 2025-11-10T14:30:00
    description: Optional[str] = ""
    reminder_minutes: Optional[int] = 0

class ScrapeRequest(BaseModel):
    url: str

# Google Workspace models
class GoogleAuthRequest(BaseModel):
    code: str

class GmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str

class GoogleDocsCreateRequest(BaseModel):
    title: str
    content: str

class GoogleSheetsUpdateRequest(BaseModel):
    range: str
    values: List[List[Any]]

# Health check — probes every critical subsystem and returns 503 if any are down
@app.get("/health")
async def health():
    checks: Dict[str, Any] = {}
    all_healthy = True

    # Ollama reachability
    try:
        ollama_ok = await ollama_client._check_ollama_connection()
        checks["ollama"] = "ok" if ollama_ok else "unreachable"
        if not ollama_ok:
            all_healthy = False
    except Exception as e:
        checks["ollama"] = f"error: {e}"
        all_healthy = False

    # Database — quick read check
    try:
        await db.get_recent_conversations("_health_probe_", limit=1)
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        all_healthy = False

    # Vector store — check index is loaded
    try:
        from rag.vector_store import vector_store
        checks["vector_store"] = "ok" if vector_store.index is not None else "not_loaded"
        if vector_store.index is None:
            all_healthy = False
    except Exception as e:
        checks["vector_store"] = f"error: {e}"
        all_healthy = False

    # Google Workspace — informational only (not a health-gate)
    try:
        gws = google_workspace.get_status()
        checks["google_workspace"] = {
            "configured": gws["configured"],
            "authenticated": gws["authenticated"],
            "sync_running": gws["sync_running"],
        }
    except Exception as e:
        checks["google_workspace"] = f"error: {e}"

    payload = {
        "status": "healthy" if all_healthy else "degraded",
        "model": ollama_client.current_model,
        "checks": checks,
    }
    if not all_healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload

# Chat endpoint
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        # Try to parse calendar request first (shared parser)
        event_id = None
        cal = parse_calendar_request(request.message)
        if cal:
            event_id = await calendar.add_event(cal["title"], cal["event_date"])

        # Build conversation history for this session
        history = _session_histories.get(session_id, [])
        recent_history = history[-CONVERSATION_HISTORY_TURNS:]

        # Get context from RAG
        context = await rag_retriever.retrieve_context(request.message, session_id)

        # Generate response with history
        response = await ollama_client.generate(
            prompt=request.message,
            context=context,
            stream=False,
            conversation_history=recent_history
        )

        # If we created an event, prepend confirmation to response
        if event_id:
            response = f"✓ I've created that event for you (Event #{event_id}).\n\n" + response

        if not response:
            raise HTTPException(status_code=500, detail="Failed to generate response")

        # Store conversation and embed in FAISS
        conversation_id = await db.add_conversation(
            session_id=session_id,
            user_message=request.message,
            ai_response=response,
            model_used=ollama_client.current_model,
            context_used=context[:500] if context else None
        )
        _create_task(rag_retriever.embed_conversation(
            user_message=request.message,
            ai_response=response,
            conversation_id=conversation_id,
            session_id=session_id
        ))

        # Update in-memory session history
        _session_histories.setdefault(session_id, []).append({
            "user": request.message,
            "assistant": response
        })

        return ChatResponse(
            response=response,
            session_id=session_id,
            model_used=ollama_client.current_model,
            context_used=context[:200] if context else None
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Streaming chat via WebSocket
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    ws_history: List[Dict] = []  # per-connection conversation history

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data.get("message")

            if not message:
                continue

            # Try to parse calendar request (shared parser)
            event_id = None
            cal = parse_calendar_request(message)
            if cal:
                event_id = await calendar.add_event(cal["title"], cal["event_date"])

            # Get context and generate response with history
            context = await rag_retriever.retrieve_context(message, session_id)
            recent_history = ws_history[-CONVERSATION_HISTORY_TURNS:]
            response = await ollama_client.generate(
                prompt=message,
                context=context,
                stream=False,
                conversation_history=recent_history
            )

            if response:
                if event_id:
                    response = f"✓ I've created that event for you (Event #{event_id}).\n\n" + response

                # Send in chunks for streaming effect
                for i in range(0, len(response), 20):
                    chunk = response[i:i+20]
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk
                    })
                    await asyncio.sleep(0.05)

                await websocket.send_json({"type": "done"})

                # Store conversation and embed in FAISS
                conversation_id = await db.add_conversation(
                    session_id=session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=ollama_client.current_model,
                    context_used=context[:500] if context else None
                )
                _create_task(rag_retriever.embed_conversation(
                    user_message=message,
                    ai_response=response,
                    conversation_id=conversation_id,
                    session_id=session_id
                ))

                # Update per-connection history
                ws_history.append({"user": message, "assistant": response})

    except WebSocketDisconnect:
        log.debug("WebSocket client disconnected: %s", session_id)

# Models
@app.get("/api/models")
async def list_models():
    models = await ollama_client.list_models()
    return {"models": models, "current": ollama_client.current_model}

@app.post("/api/models/switch/{model_name}")
async def switch_model(model_name: str):
    success = await ollama_client.switch_model(model_name)
    if success:
        return {"success": True, "model": ollama_client.current_model}
    raise HTTPException(status_code=400, detail="Failed to switch model")

# Calendar endpoints
@app.get("/api/calendar/events")
async def get_events(days: int = 7):
    events = await calendar.get_upcoming_events(days=days)
    return {"events": events}

@app.get("/api/calendar/today")
async def get_today_events():
    events = await calendar.get_today_events()
    return {"events": events}

@app.post("/api/calendar/events")
async def create_event(request: EventRequest):
    event_date = datetime.fromisoformat(request.event_date)
    event_id = await calendar.add_event(
        title=request.title,
        event_date=event_date,
        description=request.description,
        reminder_minutes=request.reminder_minutes
    )
    return {"event_id": event_id, "success": True}

@app.delete("/api/calendar/events/{event_id}")
async def delete_event(event_id: int):
    await calendar.delete_event(event_id)
    return {"success": True}

@app.post("/api/calendar/events/{event_id}/complete")
async def complete_event(event_id: int):
    await calendar.mark_completed(event_id)
    return {"success": True}

# Scraping
@app.post("/api/scrape")
async def scrape_url(request: ScrapeRequest):
    doc_id = await web_scraper.scrape_and_store(request.url)
    if doc_id:
        return {"success": True, "document_id": doc_id}
    raise HTTPException(status_code=400, detail="Failed to scrape URL")

# Search documents
@app.get("/api/search")
async def search_documents(query: str, limit: int = 5):
    results = await rag_retriever.search_documents(query)
    return {"results": results[:limit]}

# Conversation history
@app.get("/api/history/{session_id}")
async def get_history(session_id: str, limit: int = 10):
    history = await db.get_recent_conversations(session_id, limit=limit)
    return {"history": history}

# Stats
@app.get("/api/stats")
async def get_stats():
    stats = await rag_retriever.get_stats()
    return stats


# ============================================================================
# Google Workspace Endpoints
# ============================================================================

@app.get("/api/google/status")
async def google_status():
    """Return Google Workspace auth state and sync statistics."""
    return google_workspace.get_status()


@app.post("/api/google/auth")
async def google_auth(request: GoogleAuthRequest):
    """Exchange an OAuth2 authorization code for tokens."""
    if not google_workspace.auth.is_configured():
        raise HTTPException(status_code=503, detail="Google credentials not configured on server.")
    try:
        google_workspace.auth.exchange_code(request.code)
        _create_task(google_workspace.start_background_sync())
        return {"success": True, "message": "Authenticated with Google successfully."}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/google/sync")
async def google_sync():
    """Trigger an immediate Google Workspace sync. Returns ingestion summary."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    summary = await google_workspace.sync_now()
    return summary


@app.get("/api/google/gmail/search")
async def gmail_search(q: str = "", limit: int = 10):
    """Search Gmail messages. Results are ingested into FAISS automatically."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    from rag.retriever import rag_retriever

    messages = await asyncio.to_thread(
        google_workspace.gmail.list_messages, query=q, max_results=limit
    )
    ingested = 0
    results = []
    for msg in messages:
        url = f"gmail:{msg['id']}"
        exists = await db.check_document_exists(url)
        if not exists:
            content = google_workspace.gmail.format_for_ingestion(msg)
            if content.strip():
                await rag_retriever.add_document(
                    content=content,
                    title=msg["subject"],
                    url=url,
                    metadata={"source": "gmail", "from": msg["from_"], "date": msg["date"]},
                )
                ingested += 1
        results.append({
            "id": msg["id"],
            "subject": msg["subject"],
            "from": msg["from_"],
            "date": msg["date"],
            "snippet": msg["snippet"],
        })
    return {"messages": results, "ingested": ingested}


@app.post("/api/google/gmail/send")
async def gmail_send(request: GmailSendRequest):
    """Send an email via Gmail (audit-logged)."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    try:
        result = await google_workspace.send_email(request.to, request.subject, request.body)
        return {"success": True, "message_id": result.get("id")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/google/docs/{doc_id}")
async def google_docs_get(doc_id: str):
    """Return Google Doc content and ingest into FAISS."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    from rag.retriever import rag_retriever

    try:
        doc = await asyncio.to_thread(google_workspace.docs.get_document, doc_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    url = f"gdrive:{doc_id}"
    exists = await db.check_document_exists(url)
    if not exists:
        _create_task(rag_retriever.add_document(
            content=doc["content"],
            title=doc["title"],
            url=url,
            metadata={"source": "gdocs", "revision": doc["revision_id"]},
        ))
    return {"id": doc["id"], "title": doc["title"], "content": doc["content"], "ingested": not exists}


@app.post("/api/google/docs")
async def google_docs_create(request: GoogleDocsCreateRequest):
    """Create a new Google Doc (audit-logged)."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    try:
        result = await google_workspace.create_doc(request.title, request.content)
        return {"success": True, "id": result["id"], "url": result["url"]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/google/sheets/{sheet_id}")
async def google_sheets_get(sheet_id: str, range: str = "A1:Z1000"):
    """Read a Google Sheet range and ingest into FAISS."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    from rag.retriever import rag_retriever

    try:
        data = await asyncio.to_thread(google_workspace.sheets.get_values, sheet_id, range)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    url = f"gsheets:{sheet_id}:{range}"
    exists = await db.check_document_exists(url)
    if not exists:
        content = google_workspace.sheets.format_for_ingestion(data)
        _create_task(rag_retriever.add_document(
            content=content,
            title=f"Sheet {sheet_id} ({range})",
            url=url,
            metadata={"source": "gsheets", "range": range},
        ))
    return {"spreadsheet_id": data["spreadsheet_id"], "range": data["range"],
            "values": data["values"], "ingested": not exists}


@app.post("/api/google/sheets/{sheet_id}")
async def google_sheets_update(sheet_id: str, request: GoogleSheetsUpdateRequest):
    """Update a Google Sheet range (audit-logged)."""
    if not google_workspace.auth.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")
    try:
        result = await google_workspace.update_sheet(sheet_id, request.range, request.values)
        return {"success": True, "updated_cells": result.get("updatedCells", 0)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# UTCP (Universal Tool Calling Protocol) Endpoint
# ============================================================================
# UTCP provides a standardized way for AI agents to discover and call tools
# directly without requiring wrapper servers. This endpoint returns a UTCP
# manual that describes all JRVS API endpoints as callable tools.
#
# Learn more: https://github.com/universal-tool-calling-protocol
# ============================================================================

def get_utcp_manual(request: Request) -> Dict[str, Any]:
    """Generate UTCP manual for JRVS API tools"""
    base_url = str(request.base_url).rstrip("/")

    return {
        "manual_version": "1.0.0",
        "utcp_version": "1.0.1",
        "info": {
            "title": "JRVS AI Agent API",
            "version": "1.0.0",
            "description": "A sophisticated AI assistant combining Ollama LLMs with RAG capabilities, featuring web scraping, vector search, calendar management, and intelligent context injection.",
            "contact": {
                "url": "https://github.com/universal-tool-calling-protocol"
            }
        },
        "tools": [
            # Chat Tools
            {
                "name": "chat",
                "description": "Send a message to the JRVS AI assistant and get a response with RAG-enhanced context. Supports natural language calendar event creation.",
                "tags": ["chat", "ai", "conversation"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message or question to send to the AI assistant"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Optional session ID for conversation continuity"
                        },
                        "stream": {
                            "type": "boolean",
                            "description": "Whether to stream the response (currently not supported via this endpoint)",
                            "default": False
                        }
                    },
                    "required": ["message"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "response": {"type": "string", "description": "The AI-generated response"},
                        "session_id": {"type": "string", "description": "Session ID for this conversation"},
                        "model_used": {"type": "string", "description": "The Ollama model used for generation"},
                        "context_used": {"type": "string", "description": "Preview of RAG context used"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/chat",
                    "http_method": "POST",
                    "headers": {"Content-Type": "application/json"}
                }
            },
            # Model Management Tools
            {
                "name": "list_models",
                "description": "List all available Ollama AI models and identify the currently active model.",
                "tags": ["models", "ollama", "configuration"],
                "inputs": {"type": "object", "properties": {}},
                "outputs": {
                    "type": "object",
                    "properties": {
                        "models": {"type": "array", "description": "List of available models with metadata"},
                        "current": {"type": "string", "description": "Currently active model name"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/models",
                    "http_method": "GET"
                }
            },
            {
                "name": "switch_model",
                "description": "Switch JRVS to use a different Ollama AI model for text generation.",
                "tags": ["models", "ollama", "configuration"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "model_name": {
                            "type": "string",
                            "description": "Name of the Ollama model to switch to (e.g., 'llama3.1', 'codellama', 'mistral')"
                        }
                    },
                    "required": ["model_name"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "model": {"type": "string", "description": "The newly active model name"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/models/switch/{{model_name}}",
                    "http_method": "POST"
                }
            },
            # Calendar Tools
            {
                "name": "get_calendar_events",
                "description": "Retrieve upcoming calendar events for a specified number of days.",
                "tags": ["calendar", "events", "schedule"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Number of days ahead to retrieve events (default: 7)",
                            "default": 7
                        }
                    }
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "description": "List of upcoming events"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/calendar/events",
                    "http_method": "GET",
                    "query_params": {"days": "${{days}}"}
                }
            },
            {
                "name": "get_today_events",
                "description": "Get all calendar events scheduled for today.",
                "tags": ["calendar", "events", "today"],
                "inputs": {"type": "object", "properties": {}},
                "outputs": {
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "description": "List of today's events"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/calendar/today",
                    "http_method": "GET"
                }
            },
            {
                "name": "create_calendar_event",
                "description": "Create a new calendar event with optional reminder.",
                "tags": ["calendar", "events", "create"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Event title"
                        },
                        "event_date": {
                            "type": "string",
                            "description": "Event date/time in ISO format (e.g., '2025-11-15T14:30:00')"
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional event description",
                            "default": ""
                        },
                        "reminder_minutes": {
                            "type": "integer",
                            "description": "Minutes before event to send reminder (0 = no reminder)",
                            "default": 0
                        }
                    },
                    "required": ["title", "event_date"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "integer", "description": "ID of the created event"},
                        "success": {"type": "boolean"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/calendar/events",
                    "http_method": "POST",
                    "headers": {"Content-Type": "application/json"}
                }
            },
            {
                "name": "delete_calendar_event",
                "description": "Delete a calendar event by its ID.",
                "tags": ["calendar", "events", "delete"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "integer",
                            "description": "ID of the event to delete"
                        }
                    },
                    "required": ["event_id"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/calendar/events/{{event_id}}",
                    "http_method": "DELETE"
                }
            },
            {
                "name": "complete_calendar_event",
                "description": "Mark a calendar event as completed.",
                "tags": ["calendar", "events", "complete"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "integer",
                            "description": "ID of the event to mark as completed"
                        }
                    },
                    "required": ["event_id"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/calendar/events/{{event_id}}/complete",
                    "http_method": "POST"
                }
            },
            # Knowledge Base & RAG Tools
            {
                "name": "scrape_url",
                "description": "Scrape a website URL and add its content to the JRVS knowledge base for RAG retrieval.",
                "tags": ["scraping", "knowledge-base", "rag"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to scrape and index"
                        }
                    },
                    "required": ["url"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "document_id": {"type": "integer", "description": "ID of the indexed document"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/scrape",
                    "http_method": "POST",
                    "headers": {"Content-Type": "application/json"}
                }
            },
            {
                "name": "search_documents",
                "description": "Search the JRVS knowledge base using semantic vector search.",
                "tags": ["search", "knowledge-base", "rag"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query text"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "results": {"type": "array", "description": "List of matching documents with similarity scores"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/search",
                    "http_method": "GET",
                    "query_params": {
                        "query": "${{query}}",
                        "limit": "${{limit}}"
                    }
                }
            },
            # Conversation History Tool
            {
                "name": "get_conversation_history",
                "description": "Retrieve conversation history for a specific session.",
                "tags": ["history", "conversation", "session"],
                "inputs": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID to retrieve history for"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of conversations to return",
                            "default": 10
                        }
                    },
                    "required": ["session_id"]
                },
                "outputs": {
                    "type": "object",
                    "properties": {
                        "history": {"type": "array", "description": "List of past conversations"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/history/{{session_id}}",
                    "http_method": "GET",
                    "query_params": {"limit": "${{limit}}"}
                }
            },
            # System Tools
            {
                "name": "get_stats",
                "description": "Get JRVS system statistics including RAG pipeline metrics, vector store size, and embedding cache info.",
                "tags": ["system", "stats", "monitoring"],
                "inputs": {"type": "object", "properties": {}},
                "outputs": {
                    "type": "object",
                    "properties": {
                        "vector_store": {"type": "object", "description": "Vector store statistics"},
                        "embedding_cache": {"type": "object", "description": "Embedding cache statistics"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/api/stats",
                    "http_method": "GET"
                }
            },
            {
                "name": "health_check",
                "description": "Check if the JRVS API is healthy and get the current active model.",
                "tags": ["system", "health", "status"],
                "inputs": {"type": "object", "properties": {}},
                "outputs": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Health status ('healthy' or 'unhealthy')"},
                        "model": {"type": "string", "description": "Currently active Ollama model"}
                    }
                },
                "tool_call_template": {
                    "call_template_type": "http",
                    "url": f"{base_url}/health",
                    "http_method": "GET"
                }
            }
        ]
    }


@app.get("/utcp")
async def utcp_manual(request: Request):
    """
    UTCP Discovery Endpoint - Universal Tool Calling Protocol
    
    Returns a UTCP manual describing all JRVS API tools that can be called
    directly by AI agents without requiring wrapper servers.
    
    UTCP is a modern, flexible, and scalable standard for tool calling that:
    - Allows direct tool calls (no middleman proxy)
    - Supports multiple protocols (HTTP, CLI, WebSocket, etc.)
    - Uses native authentication and security
    - Provides zero latency overhead
    
    Learn more: https://github.com/universal-tool-calling-protocol
    """
    return JSONResponse(content=get_utcp_manual(request))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
