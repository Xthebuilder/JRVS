#!/usr/bin/env python3
"""
JRVS Web Server - Tailscale Only

Serves JRVS through a web interface accessible only on Tailscale network.
This ensures JRVS is private and only accessible to your devices.
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path
import subprocess

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator, Field
from urllib.parse import urlparse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

# JRVS imports
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from core.database import db
from core.calendar import calendar
from mcp_gateway.client import mcp_client
from mcp_gateway.agent import mcp_agent
from scraper.web_scraper import web_scraper
from data_analysis.analyzer import data_analyzer
from mcp_gateway.coding_agent import jarcore
from core.validators import (
    sanitize_text, validate_url as _validate_url, validate_session_id,
    validate_iso_date, MAX_MESSAGE_LEN, MAX_URL_LEN, MAX_SESSION_ID_LEN,
    MAX_TITLE_LEN, MAX_CODE_LEN,
)


# ============================================================================
# Request Validation Models
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN)
    session_id: Optional[str] = Field(None, max_length=MAX_SESSION_ID_LEN)

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


class ScrapeRequest(BaseModel):
    url: str = Field(..., max_length=MAX_URL_LEN)

    @validator('url')
    def check_url(cls, v):
        return _validate_url(v)


class CodeExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=MAX_CODE_LEN)
    language: str = Field(..., pattern='^(python|bash|javascript)$')
    timeout: int = Field(default=30, ge=1, le=60)


# ============================================================================
# Rate Limiter Setup
# ============================================================================

limiter = Limiter(key_func=get_remote_address)


def get_tailscale_ip() -> str:
    """Get the Tailscale IP address"""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Could not get Tailscale IP: {e}")
        return "127.0.0.1"  # Fallback to localhost only (not all interfaces)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    print("🤖 Initializing JRVS components...")

    await db.initialize()
    await calendar.initialize()
    await rag_retriever.initialize()
    await mcp_client.initialize()

    # Discover Ollama models
    models = await ollama_client.discover_models()
    print(f"✓ Found {len(models)} Ollama models")

    # Check MCP servers
    servers = await mcp_client.list_servers()
    if servers:
        print(f"✓ Connected to {len(servers)} MCP server(s): {', '.join(servers)}")

    print("✓ JRVS ready!")
    
    yield
    
    # Shutdown
    print("🧹 Cleaning up JRVS...")
    await ollama_client.cleanup()
    await web_scraper.cleanup()
    await rag_retriever.cleanup()
    await mcp_client.cleanup()
    print("✓ Goodbye!")


# Create app with lifespan
app = FastAPI(
    title="JRVS AI Agent",
    description="Intelligent AI assistant on your Tailscale network",
    lifespan=lifespan
)

# Add rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Store active WebSocket connections
active_connections: List[WebSocket] = []


async def handle_command(websocket: WebSocket, command: str, session_id: str):
    """Handle slash commands from web interface"""
    parts = command.split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:] if len(parts) > 1 else []

    try:
        if cmd == "help":
            response = """**Available Commands:**

**Calendar:**
• `/calendar` - Show upcoming events (7 days)
• `/month` - Show calendar for current month
• `/today` - Show today's events
• `/event <date> <time> <title>` - Add event

**MCP Tools:**
• `/mcp-servers` - List connected MCP servers
• `/mcp-tools` - List all available tools
• `/report` - Show MCP agent activity report

**AI:**
• `/models` - List available Ollama models
• `/stats` - Show system statistics

**Knowledge:**
• `/scrape <url>` - Scrape website
• `/search <query>` - Search documents

**Other:**
• `/history` - Show conversation history
• `/theme <name>` - Change theme (CLI only)
• `/clear` - Clear screen (use New Chat button)
"""
            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "stats":
            # Get system stats
            servers = await mcp_client.list_servers()
            models = await ollama_client.list_models()
            rag_stats = await rag_retriever.get_stats()

            stats = f"""**JRVS System Statistics**

**AI Model:**
• Current: {ollama_client.current_model}
• Available: {len(models)} Ollama models

**MCP Integration:**
• Connected Servers: {len(servers)}
• Servers: {', '.join(servers) if servers else 'None'}

**RAG System:**
• Documents: {rag_stats.get('total_documents', 0)}
• Chunks: {rag_stats.get('total_chunks', 0)}
• Embeddings: {rag_stats.get('embeddings_count', 0)}

**Calendar:**
• Events in database: (check /calendar)

**Session:**
• Session ID: {session_id[:8]}...
• WebSocket: Connected ✓
"""
            await websocket.send_json({"type": "response", "message": stats})

        elif cmd == "models":
            models = await ollama_client.list_models()
            response = "**Available Ollama Models:**\n\n"
            for model in models:
                current = " ← Current" if model['name'] == ollama_client.current_model else ""
                response += f"• {model['name']}{current}\n"
            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "mcp-servers":
            servers = await mcp_client.list_servers()
            all_tools = await mcp_client.list_all_tools()

            response = "**Connected MCP Servers:**\n\n"
            if servers:
                for server in servers:
                    tool_count = len(all_tools.get(server, []))
                    response += f"• **{server}** - {tool_count} tools\n"
            else:
                response = "No MCP servers connected."

            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "mcp-tools":
            all_tools = await mcp_client.list_all_tools()
            response = "**Available MCP Tools:**\n\n"

            for server, tools in all_tools.items():
                response += f"**{server}:**\n"
                for tool in tools[:5]:  # Show first 5
                    response += f"• `{tool['name']}` - {tool.get('description', 'No description')}\n"
                if len(tools) > 5:
                    response += f"  ... and {len(tools) - 5} more\n"
                response += "\n"

            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "report":
            report = mcp_agent.generate_report(session_id)
            await websocket.send_json({"type": "response", "message": f"```\n{report}\n```"})

        elif cmd == "calendar":
            events = await calendar.get_upcoming_events(days=7)
            response = "**Upcoming Events (Next 7 Days):**\n\n"

            if events:
                for event in events:
                    event_dt = datetime.fromisoformat(event['event_date'])
                    status = "✓" if event['completed'] else "○"
                    response += f"{status} **{event['title']}**\n"
                    response += f"   {event_dt.strftime('%Y-%m-%d %H:%M')}\n"
                    if event['description']:
                        response += f"   {event['description']}\n"
                    response += "\n"
            else:
                response = "No upcoming events."

            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "today":
            events = await calendar.get_today_events()
            response = "**Today's Events:**\n\n"

            if events:
                for event in events:
                    event_dt = datetime.fromisoformat(event['event_date'])
                    status = "✓" if event['completed'] else "○"
                    response += f"{status} **{event['title']}**\n"
                    response += f"   {event_dt.strftime('%H:%M')}\n"
                    if event['description']:
                        response += f"   {event['description']}\n"
                    response += "\n"
            else:
                response = "No events today."

            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "month":
            from datetime import datetime as dt
            now = dt.now()
            events_by_day = await calendar.get_month_events(now.year, now.month)
            cal_display = calendar.render_month_calendar(now.year, now.month, events_by_day)

            response = f"```\n{cal_display}\n```\n\n"

            if events_by_day:
                response += "**Events this month:**\n\n"
                for day in sorted(events_by_day.keys()):
                    for event in events_by_day[day]:
                        event_dt = datetime.fromisoformat(event['event_date'])
                        status = "✓" if event['completed'] else "○"
                        response += f"{status} {event['title']} - {event_dt.strftime('%b %d at %I:%M %p')}\n"

            await websocket.send_json({"type": "response", "message": response})

        elif cmd == "history":
            # Get recent conversations from database
            conversations = await db.get_recent_conversations(session_id, limit=5)
            response = "**Recent Conversations:**\n\n"

            if conversations:
                for i, conv in enumerate(conversations, 1):
                    response += f"**{i}.** User: {conv['user_message'][:100]}...\n"
                    response += f"    JRVS: {conv['ai_response'][:100]}...\n\n"
            else:
                response = "No conversation history yet."

            await websocket.send_json({"type": "response", "message": response})

        else:
            await websocket.send_json({
                "type": "response",
                "message": f"Unknown command: `/{cmd}`\n\nType `/help` for available commands."
            })

    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": f"Command error: {str(e)}"
        })


# WebSocket for real-time chat
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for real-time chat"""
    await websocket.accept()
    active_connections.append(websocket)
    session_id = str(uuid.uuid4())

    try:
        await websocket.send_json({
            "type": "system",
            "message": "Connected to JRVS",
            "session_id": session_id
        })

        while True:
            # Receive message
            data = await websocket.receive_json()
            raw_message = data.get("message", "")

            if not raw_message or not isinstance(raw_message, str):
                continue

            # Sanitize input
            user_message = sanitize_text(raw_message, max_length=MAX_MESSAGE_LEN)
            if not user_message:
                continue

            # Check if it's a slash command
            if user_message.startswith('/'):
                await handle_command(websocket, user_message[1:], session_id)
                continue

            # Send thinking status
            await websocket.send_json({
                "type": "status",
                "message": "Analyzing request..."
            })

            # Check if MCP tools needed
            agent_result = await mcp_agent.process_request(user_message)

            # Send tool usage info
            if agent_result.get("tool_results"):
                tools_used = [
                    f"{tr['server']}/{tr['tool']}"
                    for tr in agent_result["tool_results"]
                    if tr["success"]
                ]
                await websocket.send_json({
                    "type": "tools",
                    "tools": tools_used
                })

            # Get RAG context
            context = await rag_retriever.retrieve_context(user_message, session_id)

            # Add tool results to context
            if agent_result.get("tool_results"):
                tool_context = "\n\nTool Results:\n"
                for tr in agent_result["tool_results"]:
                    if tr["success"] and tr.get("result"):
                        tool_context += f"- {tr['server']}/{tr['tool']}: {tr['result'][:200]}\n"
                context = tool_context + "\n" + context

            # Generate response
            await websocket.send_json({
                "type": "status",
                "message": "Generating response..."
            })

            response = await ollama_client.generate(
                prompt=user_message,
                context=context,
                stream=False
            )

            # Send response
            await websocket.send_json({
                "type": "response",
                "message": response,
                "timestamp": datetime.now().isoformat()
            })

            # Store conversation
            tool_summary = agent_result.get("summary", "No tools used")
            await db.add_conversation(
                session_id=session_id,
                user_message=user_message,
                ai_response=response,
                model_used=ollama_client.current_model,
                context_used=f"Tools: {tool_summary}\n{context[:500]}"
            )

    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print(f"Client disconnected: {session_id}")
    except Exception as e:
        print(f"WebSocket error: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })


# REST API endpoints

@app.get("/")
async def root():
    """Serve the web UI"""
    with open("static/index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.get("/data_analysis.html")
async def data_analysis_page():
    """Serve the data analysis UI"""
    with open("static/data_modern.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.get("/api/status")
@limiter.limit("60/minute")
async def get_status(request: Request):
    """Get JRVS status"""
    servers = await mcp_client.list_servers()
    models = await ollama_client.list_models()

    return {
        "status": "online",
        "mcp_servers": servers,
        "ollama_models": [m["name"] for m in models] if models else [],
        "current_model": ollama_client.current_model
    }


@app.get("/api/calendar/month")
async def get_month_calendar(year: Optional[int] = None, month: Optional[int] = None):
    """Get calendar for a month"""
    from datetime import datetime as dt

    now = dt.now()
    year = year or now.year
    month = month or now.month

    events_by_day = await calendar.get_month_events(year, month)
    calendar_display = calendar.render_month_calendar(year, month, events_by_day)

    return {
        "year": year,
        "month": month,
        "calendar": calendar_display,
        "events": events_by_day
    }


@app.post("/api/calendar/event")
async def add_calendar_event(
    title: str = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    description: str = Form("")
):
    """Add a calendar event"""
    from datetime import datetime as dt

    try:
        event_dt = dt.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        event_id = await calendar.add_event(title, event_dt, description)

        return {
            "success": True,
            "event_id": event_id,
            "message": f"Event '{title}' added for {event_dt.strftime('%Y-%m-%d %H:%M')}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to add event: {e}"
        }


@app.get("/api/mcp/servers")
async def list_mcp_servers():
    """List connected MCP servers"""
    servers = await mcp_client.list_servers()
    all_tools = await mcp_client.list_all_tools()

    return {
        "servers": servers,
        "tools_count": {server: len(tools) for server, tools in all_tools.items()}
    }


@app.get("/api/mcp/tools")
async def list_mcp_tools(server: Optional[str] = None):
    """List MCP tools"""
    if server:
        tools = await mcp_client.list_server_tools(server)
        return {"server": server, "tools": tools}
    else:
        all_tools = await mcp_client.list_all_tools()
        return {"tools": all_tools}


# ============================================================================
# Data Analysis API Endpoints
# ============================================================================

@app.post("/api/data/upload/csv")
@limiter.limit("10/minute")
async def upload_csv(request: Request, file_path: str, name: Optional[str] = None):
    """Upload and analyze CSV file"""
    result = await data_analyzer.load_csv(file_path, name)
    return result


@app.post("/api/data/upload/excel")
@limiter.limit("10/minute")
async def upload_excel(request: Request, file_path: str, sheet_name: Optional[str] = None, name: Optional[str] = None):
    """Upload and analyze Excel file"""
    result = await data_analyzer.load_excel(file_path, sheet_name, name)
    return result


@app.get("/api/data/datasets")
@limiter.limit("60/minute")
async def list_datasets(request: Request):
    """List all loaded datasets"""
    return data_analyzer.list_datasets()


@app.get("/api/data/dataset/{dataset_name}")
@limiter.limit("30/minute")
async def get_dataset_info(request: Request, dataset_name: str):
    """Get information about a specific dataset"""
    if dataset_name not in data_analyzer.loaded_datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = data_analyzer.loaded_datasets[dataset_name]
    return {
        "name": dataset_name,
        "rows": len(df),
        "columns": len(df.columns),
        "preview": df.head(20).to_dict('records'),
        "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()}
    }


@app.post("/api/data/query")
@limiter.limit("20/minute")
async def query_dataset(request: Request, dataset_name: str, query: str):
    """Execute query on dataset"""
    result = await data_analyzer.query_data(dataset_name, query)
    return result


@app.get("/api/data/column/{dataset_name}/{column_name}")
@limiter.limit("30/minute")
async def get_column_stats(request: Request, dataset_name: str, column_name: str):
    """Get statistics for a specific column"""
    result = await data_analyzer.get_column_stats(dataset_name, column_name)
    return result


@app.post("/api/data/ai-insights/{dataset_name}")
@limiter.limit("5/minute")
async def get_ai_insights(request: Request, dataset_name: str):
    """Get AI-powered insights about the dataset using JARCORE"""
    result = await data_analyzer.get_ai_insights(dataset_name, jarcore)
    return result


# Jupyter Notebook endpoints

@app.post("/api/notebook/create")
async def create_notebook(name: str, title: str = "New Notebook"):
    """Create a new Jupyter notebook"""
    result = await data_analyzer.create_jupyter_notebook(name, title)
    return result


@app.post("/api/notebook/load")
async def load_notebook(file_path: str):
    """Load a Jupyter notebook"""
    result = await data_analyzer.load_jupyter_notebook(file_path)
    return result


@app.get("/api/notebook/list")
async def list_notebooks():
    """List all loaded notebooks"""
    return data_analyzer.list_notebooks()


# ============================================================================
# REST API endpoints for Next.js frontend
# ============================================================================

class RestChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN)
    session_id: Optional[str] = Field(None, max_length=MAX_SESSION_ID_LEN)
    stream: bool = False

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


class CalendarEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LEN)
    description: Optional[str] = Field(None, max_length=2000)
    event_date: str
    reminder_minutes: Optional[int] = Field(None, ge=0, le=10080)
    completed: Optional[bool] = False

    @validator('title')
    def sanitize_title(cls, v):
        return sanitize_text(v, max_length=MAX_TITLE_LEN)

    @validator('event_date')
    def check_event_date(cls, v):
        validate_iso_date(v)
        return v


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "model": ollama_client.current_model}


@app.post("/api/chat")
@limiter.limit("30/minute")
async def rest_chat(request: Request, body: RestChatRequest):
    """REST chat endpoint for Next.js frontend"""
    session_id = body.session_id or str(uuid.uuid4())

    agent_result = await mcp_agent.process_request(body.message)
    context = await rag_retriever.retrieve_context(body.message, session_id)

    if agent_result.get("tool_results"):
        tool_context = "\n\nTool Results:\n"
        for tr in agent_result["tool_results"]:
            if tr["success"] and tr.get("result"):
                tool_context += f"- {tr['server']}/{tr['tool']}: {tr['result'][:200]}\n"
        context = tool_context + "\n" + context

    response = await ollama_client.generate(
        prompt=body.message,
        context=context,
        stream=False
    )

    await db.add_conversation(
        session_id=session_id,
        user_message=body.message,
        ai_response=response,
        model_used=ollama_client.current_model,
        context_used=context[:500]
    )

    return {
        "response": response,
        "session_id": session_id,
        "model_used": ollama_client.current_model,
    }


@app.get("/api/models")
async def list_models():
    """List available Ollama models"""
    models = await ollama_client.list_models()
    return {
        "models": [
            {"name": m["name"], "current": m["name"] == ollama_client.current_model}
            for m in (models or [])
        ],
        "current": ollama_client.current_model
    }


@app.post("/api/models/switch/{model_name:path}")
async def switch_model(model_name: str):
    """Switch the active Ollama model"""
    success = await ollama_client.switch_model(model_name)
    return {"success": success}


@app.get("/api/calendar/events")
async def get_calendar_events(days: int = 7):
    """Get upcoming calendar events"""
    events = await calendar.get_upcoming_events(days=days)
    return {"events": events}


@app.get("/api/calendar/today")
async def get_today_events():
    """Get today's calendar events"""
    events = await calendar.get_today_events()
    return {"events": events}


@app.post("/api/calendar/events")
async def create_calendar_event(event: CalendarEventCreate):
    """Create a new calendar event"""
    from datetime import datetime as dt
    event_dt = dt.fromisoformat(event.event_date)
    event_id = await calendar.add_event(
        event.title,
        event_dt,
        event.description or ""
    )
    return {"event_id": event_id, "success": True}


@app.post("/api/calendar/events/{event_id}/complete")
async def complete_calendar_event(event_id: int):
    """Mark a calendar event as complete"""
    success = await calendar.complete_event(event_id)
    return {"success": success}


@app.delete("/api/calendar/events/{event_id}")
async def delete_calendar_event(event_id: int):
    """Delete a calendar event"""
    success = await calendar.delete_event(event_id)
    return {"success": success}


@app.post("/api/scrape")
@limiter.limit("5/minute")
async def scrape_url_rest(request: Request, body: ScrapeRequest):
    """Scrape a URL into the knowledge base"""
    doc_id = await web_scraper.scrape_and_store(body.url, rag_retriever)
    return {"document_id": doc_id, "success": True}


@app.get("/api/search")
async def search_documents(query: str, limit: int = 5):
    """Search the knowledge base"""
    results = await rag_retriever.search(query, limit=limit)
    return {"results": results}


@app.get("/api/stats")
async def get_stats():
    """Get system stats"""
    servers = await mcp_client.list_servers()
    models = await ollama_client.list_models()
    rag_stats = await rag_retriever.get_stats()
    return {
        "current_model": ollama_client.current_model,
        "models_count": len(models) if models else 0,
        "mcp_servers": servers,
        "rag": rag_stats,
    }


@app.get("/api/history/{session_id}")
async def get_history(session_id: str, limit: int = 10):
    """Get conversation history for a session"""
    conversations = await db.get_recent_conversations(session_id, limit=limit)
    return {"history": conversations}


if __name__ == "__main__":
    # Get Tailscale IP
    tailscale_ip = get_tailscale_ip()
    port = 8080

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║              JRVS Web Server - Tailscale Only             ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  🔒 Access JRVS securely on your Tailscale network       ║
║                                                           ║
║  URL: http://{tailscale_ip}:{port}/                    ║
║                                                           ║
║  Available from all your Tailscale devices:              ║
║  - Desktop, laptop, phone, tablet, etc.                  ║
║  - NOT accessible from public internet                   ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)

    # Run server bound to Tailscale IP only
    uvicorn.run(
        app,
        host=tailscale_ip,  # Only bind to Tailscale IP
        port=port,
        log_level="info"
    )
