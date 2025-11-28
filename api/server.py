"""FastAPI server for Jarvis AI Agent"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    await db.initialize()
    await calendar.initialize()
    await rag_retriever.initialize()
    await ollama_client.discover_models()
    yield
    # Shutdown (cleanup if needed)


app = FastAPI(title="Jarvis AI API", version="1.0.0", lifespan=lifespan)

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

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy", "model": ollama_client.current_model}

# Helper: Parse calendar requests from natural language
async def try_parse_calendar_request(message: str) -> Optional[int]:
    """Try to parse natural language calendar requests and create event"""
    import re
    from datetime import datetime, timedelta

    msg_lower = message.lower()

    # Pattern: "meeting/event/reminder tomorrow/today at X"
    if any(word in msg_lower for word in ['meeting', 'event', 'reminder', 'appointment']):
        time_match = re.search(r'at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?', msg_lower)

        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            meridiem = time_match.group(3)

            # Convert to 24-hour format
            if meridiem == 'pm' and hour != 12:
                hour += 12
            elif meridiem == 'am' and hour == 12:
                hour = 0

            # Determine date
            if 'tomorrow' in msg_lower:
                event_date = datetime.now() + timedelta(days=1)
            elif 'today' in msg_lower:
                event_date = datetime.now()
            elif 'next week' in msg_lower:
                event_date = datetime.now() + timedelta(days=7)
            else:
                # Check for day names (monday, tuesday, etc.)
                days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                for i, day in enumerate(days):
                    if day in msg_lower:
                        # Find next occurrence of this day
                        today = datetime.now()
                        days_ahead = i - today.weekday()
                        if days_ahead <= 0:  # Target day already happened this week
                            days_ahead += 7
                        event_date = today + timedelta(days=days_ahead)
                        break
                else:
                    event_date = datetime.now()

            # Set time
            event_date = event_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # Extract title with smart parsing
            title = message.split('at')[0].strip()

            # Remove time-related words and common phrases
            remove_words = [
                'i have a', 'i have an', 'i have',
                'schedule a', 'schedule an', 'schedule',
                'create a', 'create an', 'create',
                'add a', 'add an', 'add',
                'tomorrow', 'today', 'next week',
                'this monday', 'this tuesday', 'this wednesday',
                'this thursday', 'this friday', 'this saturday', 'this sunday',
                'next monday', 'next tuesday', 'next wednesday',
                'next thursday', 'next friday', 'next saturday', 'next sunday',
                'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            ]

            title_lower = title.lower()
            for word in remove_words:
                title_lower = title_lower.replace(word, '').strip()

            # Capitalize first letter of each word
            title = ' '.join(word.capitalize() for word in title_lower.split())

            # Generate smart titles based on keywords
            if not title or len(title) < 3:
                if 'meeting' in msg_lower:
                    # Extract who the meeting is with
                    with_match = re.search(r'with\s+(.+?)(?:\s+at|\s+tomorrow|\s+today|$)', msg_lower)
                    if with_match:
                        title = f"Meeting w/ {with_match.group(1).title()}"
                    else:
                        title = "Team Meeting"
                elif 'appointment' in msg_lower:
                    title = "Appointment"
                elif 'reminder' in msg_lower:
                    title = "Reminder"
                elif 'event' in msg_lower:
                    title = "Event"
                else:
                    title = "Task"

            # Limit title length for clean display
            if len(title) > 30:
                title = title[:27] + "..."

            # Create event
            event_id = await calendar.add_event(title, event_date)
            return event_id

    return None

# Chat endpoint
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        # Try to parse calendar request first
        event_id = await try_parse_calendar_request(request.message)

        # Get context from RAG
        context = await rag_retriever.retrieve_context(request.message, session_id)

        # Generate response
        response = await ollama_client.generate(
            prompt=request.message,
            context=context,
            stream=False
        )

        # If we created an event, prepend confirmation to response
        if event_id:
            event_msg = f"✓ I've created that event for you (Event #{event_id}).\n\n"
            response = event_msg + response

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
