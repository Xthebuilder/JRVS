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


# ============================================================================
# Request Validation Models
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = Field(None, max_length=100)
    
    @validator('message')
    def sanitize_message(cls, v):
        if not v or not v.strip():
            raise ValueError('Message cannot be empty')
        return v.strip()


class ScrapeRequest(BaseModel):
    url: str = Field(..., max_length=2000)
    
    @validator('url')
    def validate_url(cls, v):
        parsed = urlparse(v)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError('URL must use http or https')
        if not parsed.netloc:
            raise ValueError('Invalid URL')
        # Block internal IPs
        blocked = ['localhost', '127.0.0.1', '0.0.0.0', '169.254', '10.', '172.16', '192.168']
        if any(b in parsed.netloc for b in blocked):
            raise ValueError('Internal URLs not allowed')
        return v


class CodeExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50000)
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
        return "0.0.0.0"  # Fallback to all interfaces


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    print("🤖 Initializing JRVS components...")

    await db.initialize()
    await calendar.initialize()
    await rag_retriever.initialize()
    await mcp_client.initialize()

    # Initialize Mind Map module
    try:
        from memory_map.database import mindmap_db
        await mindmap_db.initialize()
        print("✓ Mind Map module initialized")
    except Exception as e:
        print(f"⚠ Mind Map module initialization skipped: {e}")

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

**Mind Map:**
• `/mindmap view` - Open mind map visualization
• `/mindmap build` - Build from conversation history
• `/mindmap stats` - Show mind map statistics
• `/mindmap insights` - Get AI-generated insights

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

        elif cmd == "mindmap" or cmd.startswith("mindmap"):
            # Handle mindmap commands
            parts = cmd.split()
            action = parts[1] if len(parts) > 1 else "view"
            
            if action == "view":
                response = """**🧠 Mind Map Visualization**

Open the mind map in your browser: [Mind Map](/static/mindmap.html)

Or use these commands:
• `/mindmap build` - Build topic graph from history
• `/mindmap stats` - Show mind map statistics
• `/mindmap insights` - Get AI insights
"""
                await websocket.send_json({"type": "response", "message": response})
            
            elif action == "build":
                await websocket.send_json({
                    "type": "status",
                    "message": "Building mind map from conversation history..."
                })
                
                try:
                    from memory_map.topic_extractor import topic_extractor
                    from memory_map.graph_builder import graph_builder
                    from memory_map.database import mindmap_db
                    
                    result = await topic_extractor.batch_extract_from_history(limit=100)
                    
                    await graph_builder.initialize()
                    topics = await mindmap_db.get_all_topics()
                    if topics:
                        await graph_builder._calculate_topic_relationships(topics)
                    
                    response = f"**✓ Mind Map Built!**\n\n{result['message']}\n\nView it at: [Mind Map](/static/mindmap.html)"
                    await websocket.send_json({"type": "response", "message": response})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"Error building mind map: {e}"})
            
            elif action == "stats":
                try:
                    from memory_map.database import mindmap_db
                    await mindmap_db.initialize()
                    stats = await mindmap_db.get_graph_statistics()
                    
                    response = f"""**📊 Mind Map Statistics**

• **Total Topics:** {stats['total_topics']}
• **Total Connections:** {stats['total_connections']}
• **Top Category:** {stats['top_category']}
• **Avg Mentions/Topic:** {stats['avg_mentions']}
• **Conversations Processed:** {stats['conversations_processed']}
"""
                    await websocket.send_json({"type": "response", "message": response})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"Error: {e}"})
            
            elif action == "insights":
                await websocket.send_json({
                    "type": "status",
                    "message": "Generating AI insights..."
                })
                
                try:
                    from memory_map.analyzer import mindmap_analyzer
                    insights = await mindmap_analyzer.generate_insights()
                    
                    response = "**🧠 Mind Map Insights**\n\n"
                    for insight in insights:
                        response += f"{insight.get('icon', '📌')} **{insight['type']}:** {insight['description']}\n\n"
                    
                    await websocket.send_json({"type": "response", "message": response})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"Error: {e}"})
            
            else:
                response = """**🧠 Mind Map Commands**

• `/mindmap view` - Open visualization
• `/mindmap build` - Build from history  
• `/mindmap stats` - Show statistics
• `/mindmap insights` - AI insights
"""
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
            user_message = data.get("message", "")

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


@app.get("/mindmap")
async def mindmap_page():
    """Serve the mind map visualization UI"""
    with open("static/mindmap.html", "r") as f:
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
# Mind Map API Endpoints
# ============================================================================

@app.get("/api/mindmap/graph")
@limiter.limit("30/minute")
async def get_mindmap_graph(
    request: Request,
    time_range: Optional[str] = "all",
    category: Optional[str] = None,
    min_connections: int = 0
):
    """Get mind map graph data filtered by parameters"""
    from memory_map.graph_builder import graph_builder
    
    graph = await graph_builder.build_topic_graph(
        time_range=time_range,
        category=category if category else None,
        min_connections=min_connections
    )
    
    return graph


@app.get("/api/mindmap/topic/{topic_id}")
@limiter.limit("30/minute")
async def get_topic_details(request: Request, topic_id: int):
    """Get detailed information about a specific topic"""
    from memory_map.database import mindmap_db
    
    await mindmap_db.initialize()
    
    topic = await mindmap_db.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    # Get related conversations
    conversations = await mindmap_db.get_conversations_for_topic(topic_id)
    
    # Get related topics
    related_topics = await mindmap_db.get_related_topics(topic_id, limit=10)
    
    return {
        "topic": {
            "id": topic['id'],
            "topic_name": topic['topic_name'],
            "category": topic['category'],
            "mention_count": topic['mention_count'],
            "first_mentioned": topic['first_mentioned'],
            "last_mentioned": topic['last_mentioned']
        },
        "conversations": conversations,
        "related_topics": related_topics,
        "statistics": {
            "total_mentions": topic['mention_count'],
            "conversation_count": len(conversations),
            "related_topics_count": len(related_topics)
        }
    }


@app.post("/api/mindmap/build")
@limiter.limit("5/minute")
async def build_mindmap(request: Request):
    """Build or rebuild the topic graph from conversation history"""
    from memory_map.topic_extractor import topic_extractor
    from memory_map.graph_builder import graph_builder
    from memory_map.database import mindmap_db
    
    # Extract topics from conversations
    result = await topic_extractor.batch_extract_from_history(limit=100)
    
    # Build relationships
    await graph_builder.initialize()
    topics = await mindmap_db.get_all_topics()
    if topics:
        await graph_builder._calculate_topic_relationships(topics)
    
    return result


@app.post("/api/mindmap/snapshot")
@limiter.limit("10/minute")
async def save_snapshot(request: Request, snapshot_name: str, description: str = ""):
    """Save current mind map state as a snapshot"""
    import json
    from memory_map.graph_builder import graph_builder
    from memory_map.database import mindmap_db
    
    graph = await graph_builder.build_topic_graph()
    
    snapshot_id = await mindmap_db.save_mindmap_snapshot(
        name=snapshot_name,
        graph_data=json.dumps(graph),
        description=description
    )
    
    return {"snapshot_id": snapshot_id, "message": "Snapshot saved"}


@app.get("/api/mindmap/snapshots")
@limiter.limit("30/minute")
async def list_snapshots(request: Request):
    """List all saved snapshots"""
    from memory_map.database import mindmap_db
    
    await mindmap_db.initialize()
    snapshots = await mindmap_db.get_all_snapshots()
    return snapshots


@app.get("/api/mindmap/insights")
@limiter.limit("10/minute")
async def get_insights(request: Request):
    """Get AI-generated insights about conversation patterns"""
    from memory_map.analyzer import mindmap_analyzer
    
    insights = await mindmap_analyzer.generate_insights()
    return insights


@app.get("/api/mindmap/stats")
@limiter.limit("30/minute")
async def get_mindmap_stats(request: Request):
    """Get mind map statistics"""
    from memory_map.database import mindmap_db
    
    await mindmap_db.initialize()
    stats = await mindmap_db.get_graph_statistics()
    return stats


@app.get("/api/mindmap/search")
@limiter.limit("30/minute")
async def search_topics(request: Request, q: str):
    """Search topics by name"""
    from memory_map.database import mindmap_db
    
    await mindmap_db.initialize()
    results = await mindmap_db.search_topics(q)
    return results


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
