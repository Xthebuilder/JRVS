"""FastAPI server for Jarvis AI Agent"""
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import uuid
from datetime import datetime

# Import Jarvis components
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from core.database import db
from core.calendar import calendar
from scraper.web_scraper import web_scraper

app = FastAPI(title="Jarvis AI API", version="1.0.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your frontend URL in production
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

# Startup
@app.on_event("startup")
async def startup():
    await db.initialize()
    await calendar.initialize()
    await rag_retriever.initialize()
    await ollama_client.discover_models()

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy", "model": ollama_client.current_model}

# Chat endpoint
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        # Get context from RAG
        context = await rag_retriever.retrieve_context(request.message, session_id)

        # Generate response
        response = await ollama_client.generate(
            prompt=request.message,
            context=context,
            stream=False
        )

        if not response:
            raise HTTPException(status_code=500, detail="Failed to generate response")

        # Store conversation
        await db.add_conversation(
            session_id=session_id,
            user_message=request.message,
            ai_response=response,
            model_used=ollama_client.current_model,
            context_used=context[:500] if context else None
        )

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

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data.get("message")

            if not message:
                continue

            # Get context
            context = await rag_retriever.retrieve_context(message, session_id)

            # Send response (streaming simulation)
            response = await ollama_client.generate(
                prompt=message,
                context=context,
                stream=False
            )

            if response:
                # Send in chunks for streaming effect
                for i in range(0, len(response), 20):
                    chunk = response[i:i+20]
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk
                    })
                    await asyncio.sleep(0.05)

                await websocket.send_json({"type": "done"})

                # Store conversation
                await db.add_conversation(
                    session_id=session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=ollama_client.current_model,
                    context_used=context[:500] if context else None
                )

    except WebSocketDisconnect:
        print(f"Client disconnected: {session_id}")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
