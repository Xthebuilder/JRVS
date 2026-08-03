"""FastAPI server for Jarvis AI Agent"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
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
import re
from config import (
    VOICE_MAX_CONTEXT_LENGTH,
    _build_voice_system_prompt,
)
from google_integration.client import google_workspace
from core.auth import require_auth, require_auth_ws
from core.ws_rate_limiter import WebSocketRateLimiter
from core.session_store import session_store
from core.validators import (
    sanitize_text, validate_url, validate_email, validate_session_id,
    validate_iso_date, MAX_MESSAGE_LEN, MAX_URL_LEN, MAX_SESSION_ID_LEN,
    MAX_TITLE_LEN, MAX_EMAIL_LEN,
)

_ws_limiter = WebSocketRateLimiter(
    max_messages=int(os.environ.get("JRVS_WS_RATE_LIMIT", "30")),
    window_seconds=60.0,
)

# CORS origins — restrict to configured origins in production
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    if o.strip()
]

# Background task registry — lets us await / cancel them on shutdown
_background_tasks: set = set()


def _create_task(coro) -> asyncio.Task:
    """Create a tracked background task that removes itself from the registry on completion."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _periodic_reembed(interval: int = 1800) -> None:
    """Re-embed any conversations stuck at embedded=0 every *interval* seconds.

    Handles the case where embed_conversation() fails at runtime (Qdrant blip,
    Ollama timeout, etc.) — those turns are skipped by the startup backfill after
    the first run, so without this they'd stay unembedded until the next restart.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            count = await rag_retriever.embed_pending_conversations()
            if count:
                log.info("Periodic re-embed: caught up %d conversation(s)", count)
        except Exception as exc:
            log.warning("Periodic re-embed failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    await db.initialize()
    await session_store.initialize()
    await calendar.initialize()
    await rag_retriever.initialize()
    await ollama_client.discover_models()
    # Backfill any conversation turns not yet embedded in the RAG backend
    _create_task(rag_retriever.embed_pending_conversations())
    # Backfill any documents added directly to SQLite (scraper/CLI) that missed RAG ingestion
    _create_task(rag_retriever.backfill_documents())
    # Periodic re-embed: catches conversations that failed during runtime (every 30 min)
    _create_task(_periodic_reembed())
    yield
    # Graceful shutdown: wait up to 10s for background tasks then cancel
    if _background_tasks:
        log.info("Waiting for %d background task(s) to finish…", len(_background_tasks))
        done, pending = await asyncio.wait(_background_tasks, timeout=10)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    await session_store.close()


app = FastAPI(title="Jarvis AI API", version="1.0.0", lifespan=lifespan)

# CORS for frontend — set ALLOWED_ORIGINS env var to restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# Request/Response models
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN)
    session_id: Optional[str] = Field(None, max_length=MAX_SESSION_ID_LEN)
    stream: bool = False
    voice: bool = False  # Use voice-optimized prompt + reduced RAG context

    @validator('message')
    def sanitize_message(cls, v):
        v = sanitize_text(v)
        if not v:
            raise ValueError('Message cannot be empty')
        return v

    @validator('session_id', pre=True, always=True)
    def check_session_id(cls, v):
        if v is not None:
            return validate_session_id(v)
        return v

class ChatResponse(BaseModel):
    response: str
    session_id: str
    model_used: str
    context_used: Optional[str] = None

class EventRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LEN)
    event_date: str = Field(...)  # ISO format: 2025-11-10T14:30:00
    description: Optional[str] = Field("", max_length=2000)
    reminder_minutes: Optional[int] = Field(0, ge=0, le=10080)  # max 1 week

    @validator('title')
    def sanitize_title(cls, v):
        return sanitize_text(v, max_length=MAX_TITLE_LEN)

    @validator('event_date')
    def check_event_date(cls, v):
        validate_iso_date(v)  # raises ValueError on bad format
        return v

class ScrapeRequest(BaseModel):
    url: str = Field(..., max_length=MAX_URL_LEN)

    @validator('url')
    def check_url(cls, v):
        return validate_url(v)

# Google Workspace models
class GoogleAuthRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=2048)

    @validator('code')
    def sanitize_code(cls, v):
        return sanitize_text(v, max_length=2048)

class GmailSendRequest(BaseModel):
    to: str = Field(..., max_length=MAX_EMAIL_LEN)
    subject: str = Field(..., min_length=1, max_length=998)  # RFC 2822 limit
    body: str = Field(..., min_length=1, max_length=50_000)

    @validator('to')
    def check_email(cls, v):
        return validate_email(v)

    @validator('subject')
    def sanitize_subject(cls, v):
        return sanitize_text(v, max_length=998)

class GoogleDocsCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LEN)
    content: str = Field(..., min_length=1, max_length=100_000)

    @validator('title')
    def sanitize_title(cls, v):
        return sanitize_text(v, max_length=MAX_TITLE_LEN)

class GoogleSheetsUpdateRequest(BaseModel):
    range: str = Field(..., min_length=1, max_length=200)
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

    # Memory backend — do a live probe, not just an init flag check
    try:
        if not rag_retriever._initialized:
            checks["memory_backend"] = "not_initialised"
            all_healthy = False
        else:
            await asyncio.wait_for(
                rag_retriever.retrieve_context("health_probe", session_id="__health__", max_length=1),
                timeout=4.0,
            )
            checks["memory_backend"] = "ok"
    except asyncio.TimeoutError:
        checks["memory_backend"] = "timeout (Qdrant/Ollama unresponsive)"
        all_healthy = False
    except Exception as e:
        checks["memory_backend"] = f"degraded: {e}"
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
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat(request: ChatRequest):
    from core.observability import tracer, async_trace_span

    session_id = request.session_id or str(uuid.uuid4())
    trace_id = tracer.start_trace(f"chat:{session_id[:8]}")

    try:
        # Try to parse calendar request first (shared parser)
        event_id = None
        cal = parse_calendar_request(request.message)
        if cal:
            async with async_trace_span(trace_id, "tool", "calendar_add", metadata={"title": cal["title"]}):
                event_id = await calendar.add_event(cal["title"], cal["event_date"])

        # Build conversation history for this session from the unified store
        recent_history = await session_store.get_recent_as_pairs(session_id)

        # Get context from RAG (reduced limit for voice to keep responses brief)
        ctx_limit = VOICE_MAX_CONTEXT_LENGTH if request.voice else None
        async with async_trace_span(trace_id, "rag", "retrieve_context", metadata={"query_len": len(request.message), "voice": request.voice}) as rag_span:
            context = await rag_retriever.retrieve_context(
                request.message, session_id, max_length=ctx_limit
            )
            rag_span.metadata["context_len"] = len(context) if context else 0

        # Use a spoken-language system prompt for voice requests
        sys_prompt = _build_voice_system_prompt() if request.voice else None

        # Generate response with history
        async with async_trace_span(trace_id, "llm", "generate", metadata={"model": ollama_client.current_model}) as llm_span:
            response = await ollama_client.generate(
                prompt=request.message,
                context=context,
                stream=False,
                conversation_history=recent_history,
                system_prompt=sys_prompt,
            )
            llm_span.metadata["response_len"] = len(response) if response else 0

        # If we created an event, prepend confirmation to response
        if event_id:
            response = f"\u2713 I've created that event for you (Event #{event_id}).\n\n" + response

        if not response:
            raise HTTPException(status_code=500, detail="Failed to generate response")

        # Store in SQLite analytics DB and queue for RAG embedding
        try:
            conversation_id = await db.add_conversation(
                session_id=session_id,
                user_message=request.message,
                ai_response=response,
                model_used=ollama_client.current_model,
                context_used=context[:500] if context else None,
            )
            _create_task(rag_retriever.embed_conversation(
                user_message=request.message,
                ai_response=response,
                conversation_id=conversation_id,
                session_id=session_id,
            ))
        except Exception as _db_err:
            log.error("Failed to persist conversation to analytics DB: %s", _db_err)

        # Persist to session store (hot context window) — failure here doesn't break the response
        try:
            await session_store.add_turn(
                session_id, request.message, response,
                metadata={"model": ollama_client.current_model},
            )
        except Exception as _ss_err:
            log.error("Failed to persist turn to session store: %s", _ss_err)

        return ChatResponse(
            response=response,
            session_id=session_id,
            model_used=ollama_client.current_model,
            context_used=context[:200] if context else None
        )

    except Exception as e:
        log.error("Chat endpoint error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Check server logs for details.")

# Full-pipeline chat — MCP tools + RAG + LLM (used by terminal thin client)
# Localhost-only, no auth token required
@app.post("/api/chat/full")
async def chat_full(request: ChatRequest, req: Request):
    if req.client and req.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Localhost only")

    session_id = request.session_id or str(uuid.uuid4())

    try:
        from cli.interface import cli
        if not cli._system_prompt:
            raise HTTPException(status_code=503, detail="CLI not initialized yet — daemon still starting")

        # label_source=False: this endpoint serves the terminal client (and any other
        # non-Slack caller), where the "From what I know from memory, ..." Slack-only
        # prefix reads as stilted filler rather than useful context.
        response = await cli.handle_chat_message_for_slack(request.message, session_id, label_source=False)
        return ChatResponse(
            response=response,
            session_id=session_id,
            model_used=cli.llm_client.current_model,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("chat_full error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Streaming chat via WebSocket
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data.get("message")

            if not message or not isinstance(message, str):
                continue

            # Sanitize + enforce length limit
            message = sanitize_text(message, max_length=MAX_MESSAGE_LEN)
            if not message:
                continue

            # WebSocket rate limiting
            if _ws_limiter.is_limited(session_id):
                await websocket.send_json({
                    "type": "error",
                    "content": "Rate limited. Please slow down."
                })
                continue
            _ws_limiter.record(session_id)

            # Try to parse calendar request (shared parser)
            event_id = None
            cal = parse_calendar_request(message)
            if cal:
                event_id = await calendar.add_event(cal["title"], cal["event_date"])

            # Get context and generate response with history from unified store
            context = await rag_retriever.retrieve_context(message, session_id)
            recent_history = await session_store.get_recent_as_pairs(session_id)
            response = await ollama_client.generate(
                prompt=message,
                context=context,
                stream=False,
                conversation_history=recent_history
            )

            if response:
                if event_id:
                    response = f"\u2713 I've created that event for you (Event #{event_id}).\n\n" + response

                # Send in chunks for streaming effect
                for i in range(0, len(response), 20):
                    chunk = response[i:i+20]
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk
                    })
                    await asyncio.sleep(0.05)

                await websocket.send_json({"type": "done"})

                try:
                    conversation_id = await db.add_conversation(
                        session_id=session_id,
                        user_message=message,
                        ai_response=response,
                        model_used=ollama_client.current_model,
                        context_used=context[:500] if context else None,
                    )
                    _create_task(rag_retriever.embed_conversation(
                        user_message=message,
                        ai_response=response,
                        conversation_id=conversation_id,
                        session_id=session_id,
                    ))
                except Exception as _db_err:
                    log.error("WS: failed to persist conversation: %s", _db_err)
                try:
                    await session_store.add_turn(
                        session_id, message, response,
                        metadata={"model": ollama_client.current_model},
                    )
                except Exception as _ss_err:
                    log.error("WS: failed to persist session turn: %s", _ss_err)

    except WebSocketDisconnect:
        _ws_limiter.disconnect(session_id)
        log.debug("WebSocket client disconnected: %s", session_id)


# Voice streaming WebSocket — true sentence-level streaming for low-latency TTS
@app.websocket("/ws/voice")
async def websocket_voice(websocket: WebSocket):
    """
    Voice-optimised WebSocket endpoint.

    Client sends: {"message": "...", "session_id": "voice"}
    Server sends:
      {"type": "thinking"}            — JRVS is querying the LLM
      {"type": "sentence", "content": "..."} — one spoken sentence (repeat)
      {"type": "done"}                — response complete
    """
    await websocket.accept()
    session_id: Optional[str] = None

    # Regex to find a sentence boundary: .!? followed by whitespace
    _sent_end = re.compile(r'(?<=[.!?])\s+')

    try:
        while True:
            data = await websocket.receive_json()
            raw_msg = data.get("message", "")
            if not isinstance(raw_msg, str):
                continue
            message = sanitize_text(raw_msg, max_length=MAX_MESSAGE_LEN)
            if not message:
                continue

            # First message sets session_id; subsequent messages inherit it
            sid = data.get("session_id") or str(uuid.uuid4())
            if session_id is None:
                session_id = sid

            # WebSocket rate limiting
            if _ws_limiter.is_limited(sid):
                await websocket.send_json({
                    "type": "error",
                    "content": "Rate limited. Please slow down."
                })
                continue
            _ws_limiter.record(sid)

            await websocket.send_json({"type": "thinking"})

            # RAG context — reduced for voice
            context = await rag_retriever.retrieve_context(
                message, session_id, max_length=VOICE_MAX_CONTEXT_LENGTH
            )
            recent_history = await session_store.get_recent_as_pairs(session_id)

            # Stream tokens from Ollama; detect sentence boundaries; forward each sentence
            sentence_buf = ""
            full_response = ""

            async for token in ollama_client.generate_tokens(
                prompt=message,
                system_prompt=_build_voice_system_prompt(),
                context=context,
                conversation_history=recent_history,
            ):
                full_response += token
                sentence_buf += token

                # Split off any complete sentences from the buffer
                while True:
                    m = _sent_end.search(sentence_buf)
                    if not m:
                        break
                    sentence = sentence_buf[: m.start() + 1].strip()
                    sentence_buf = sentence_buf[m.end():]
                    if len(sentence) > 3:
                        await websocket.send_json({"type": "sentence", "content": sentence})

            # Flush any remaining text (no trailing punctuation)
            remaining = sentence_buf.strip()
            if len(remaining) > 2:
                await websocket.send_json({"type": "sentence", "content": remaining})

            await websocket.send_json({"type": "done"})

            if full_response:
                try:
                    conversation_id = await db.add_conversation(
                        session_id=session_id,
                        user_message=message,
                        ai_response=full_response,
                        model_used=ollama_client.current_model,
                        context_used=context[:500] if context else None,
                    )
                    _create_task(rag_retriever.embed_conversation(
                        user_message=message,
                        ai_response=full_response,
                        conversation_id=conversation_id,
                        session_id=session_id,
                    ))
                except Exception as _db_err:
                    log.error("Voice WS: failed to persist conversation: %s", _db_err)
                try:
                    await session_store.add_turn(
                        session_id, message, full_response,
                        metadata={"model": ollama_client.current_model},
                    )
                except Exception as _ss_err:
                    log.error("Voice WS: failed to persist session turn: %s", _ss_err)

    except WebSocketDisconnect:
        if session_id:
            _ws_limiter.disconnect(session_id)
        log.debug("Voice WebSocket disconnected: %s", session_id)


# Models
@app.get("/api/models", dependencies=[Depends(require_auth)])
async def list_models():
    models = await ollama_client.list_models()
    return {"models": models, "current": ollama_client.current_model}

@app.post("/api/models/switch/{model_name}", dependencies=[Depends(require_auth)])
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
@app.post("/api/scrape", dependencies=[Depends(require_auth)])
async def scrape_url(request: ScrapeRequest):
    doc_id = await web_scraper.scrape_and_store(request.url)
    if doc_id:
        return {"success": True, "document_id": doc_id}
    raise HTTPException(status_code=400, detail="Failed to scrape URL")

# Search documents
@app.get("/api/search", dependencies=[Depends(require_auth)])
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


# Feedback — log bad responses for the training feedback loop
@app.post("/api/feedback", dependencies=[Depends(require_auth)])
async def log_feedback(request: Request):
    body = await request.json()
    question = body.get("question", "")
    response = body.get("response", "")
    note     = body.get("note", "")
    if not question or not response:
        return {"status": "error", "message": "question and response required"}
    feedback_id = await db.log_feedback(question, response, note)
    return {"status": "logged", "id": feedback_id}


# ============================================================================
# Google Workspace Endpoints
# ============================================================================

@app.get("/api/google/auth-url")
async def google_auth_url():
    """Return the OAuth2 URL the user needs to visit."""
    if not google_workspace.auth.is_configured():
        raise HTTPException(status_code=503, detail="Google credentials not configured.")
    try:
        url = google_workspace.auth.get_auth_url()
        return {"url": url}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
        log.error("Google auth exchange failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to exchange Google auth code.")


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
        log.error("Gmail send failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send email.")


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
        log.error("Google Doc create failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create document.")


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
        log.error("Google Sheets update failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update spreadsheet.")


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


# ============================================================================
# Observability Endpoints — Trace & Resource Monitoring
# ============================================================================

from core.observability import tracer, resource_monitor
from fastapi.responses import StreamingResponse


@app.get("/api/trace", dependencies=[Depends(require_auth)])
async def get_trace_events(trace_id: Optional[str] = None, limit: int = 50):
    """
    Get trace events.  Pass ?trace_id=xxx for a specific trace, or
    omit for the most recent events across all traces.
    """
    if trace_id:
        return {"trace_id": trace_id, "events": tracer.get_trace(trace_id)}
    return {"events": tracer.get_recent(limit=limit)}


@app.get("/api/trace/stream")
async def stream_trace_events(request: Request):
    """
    Server-Sent Events (SSE) endpoint for real-time trace events.

    Connect from browser:
        const es = new EventSource("/api/trace/stream");
        es.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    import json

    queue = tracer.subscribe()

    async def event_generator():
        try:
            while True:
                # Check for client disconnect every 5 s at most so the listener
                # is removed promptly on hard disconnects (TCP reset, tab close).
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {json.dumps(event.to_dict())}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            tracer.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/resources", dependencies=[Depends(require_auth)])
async def get_resources():
    """
    System resource dashboard — CPU, RAM, VRAM, disk, device class.
    Intended for the JRVS UI to show the user what the local device is doing.
    """
    snapshot = resource_monitor.snapshot()
    # Also include model status
    snapshot["llm"] = {
        "current_model": ollama_client.current_model,
        "backend": "ollama",
        "base_url": ollama_client.base_url,
    }
    return snapshot


if __name__ == "__main__":
    import uvicorn
    from config import JRVS_SERVER_HOST, JRVS_SERVER_PORT
    uvicorn.run(app, host=JRVS_SERVER_HOST, port=JRVS_SERVER_PORT)
