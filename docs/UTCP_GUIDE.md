# JRVS UTCP Integration Guide

JRVS now supports the **Universal Tool Calling Protocol (UTCP)** - a modern, flexible, and scalable standard for AI tool calling that enables direct communication between AI agents and tools without requiring wrapper servers.

## What is UTCP?

UTCP (Universal Tool Calling Protocol) is a lightweight protocol that provides a standardized way for AI agents to discover and call tools directly using their native protocols. Unlike other solutions that require building wrapper servers, UTCP acts as a "manual" that tells agents how to call your existing APIs directly.

### Key Benefits

| Benefit | Description |
|---------|-------------|
| 🚀 **Zero Latency Overhead** | Direct tool calls, no proxy servers |
| 🔒 **Native Security** | Uses existing authentication and authorization |
| 🌐 **Protocol Flexibility** | HTTP, WebSocket, CLI, and more |
| ⚡ **Easy Integration** | Just one endpoint, no infrastructure changes |
| 📈 **Scalable** | Leverages your existing scaling and monitoring |

## Quick Start

### 1. Start the JRVS API Server

```bash
# From the JRVS directory
cd api
python server.py
```

Or use the start script:

```bash
./start-api.sh
```

### 2. Discover JRVS Tools

Access the UTCP manual endpoint:

```bash
curl http://localhost:8000/utcp
```

This returns a JSON document describing all available JRVS tools:

```json
{
  "manual_version": "1.0.0",
  "utcp_version": "1.0.1",
  "info": {
    "title": "JRVS AI Agent API",
    "version": "1.0.0",
    "description": "A sophisticated AI assistant..."
  },
  "tools": [
    {
      "name": "chat",
      "description": "Send a message to the JRVS AI assistant...",
      "tool_call_template": {
        "call_template_type": "http",
        "url": "http://localhost:8000/api/chat",
        "http_method": "POST"
      }
    }
    // ... more tools
  ]
}
```

### 3. Call Tools Directly

With UTCP, AI agents can call JRVS tools directly using the information from the manual:

```bash
# Example: Chat with JRVS
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is machine learning?"}'

# Example: Search the knowledge base
curl "http://localhost:8000/api/search?query=python+tutorials&limit=5"

# Example: Create a calendar event
curl -X POST http://localhost:8000/api/calendar/events \
  -H "Content-Type: application/json" \
  -d '{"title": "Team Meeting", "event_date": "2025-11-15T14:30:00"}'
```

## Available UTCP Tools

JRVS exposes the following tools via UTCP:

### Chat & AI

| Tool | Description |
|------|-------------|
| `chat` | Send messages to the AI assistant with RAG-enhanced context |
| `list_models` | List all available Ollama models |
| `switch_model` | Switch to a different AI model |

### Calendar Management

| Tool | Description |
|------|-------------|
| `get_calendar_events` | Get upcoming events for N days |
| `get_today_events` | Get today's events |
| `create_calendar_event` | Create a new event |
| `delete_calendar_event` | Delete an event |
| `complete_calendar_event` | Mark an event as completed |

### Knowledge Base & RAG

| Tool | Description |
|------|-------------|
| `scrape_url` | Scrape a website and add to knowledge base |
| `search_documents` | Semantic search across indexed documents |

### System & History

| Tool | Description |
|------|-------------|
| `get_conversation_history` | Retrieve past conversations |
| `get_stats` | Get system statistics |
| `health_check` | Check API health status |

## UTCP vs MCP Comparison

JRVS supports both UTCP and MCP (Model Context Protocol). Here's how they compare:

| Aspect | UTCP | MCP |
|--------|------|-----|
| **Philosophy** | Manual (describes how to call) | Middleman (wraps tools) |
| **Architecture** | Agent → Tool (Direct) | Agent → MCP Server → Tool |
| **Infrastructure** | None required | Wrapper servers needed |
| **Performance** | Native tool performance | Additional proxy overhead |
| **Use Case** | REST APIs, HTTP tools | Stdio-based tools, complex workflows |

### When to Use UTCP

- Your tools are REST APIs
- You want minimal infrastructure overhead
- You need maximum performance (direct calls)
- You're exposing existing HTTP endpoints

### When to Use MCP

- You need stdio-based communication
- You're building complex multi-step workflows
- You need MCP-specific features (resources, prompts)
- You're integrating with Claude Code or similar tools

## Using UTCP with AI Agents

### Python Example

```python
import httpx
import json

# 1. Discover tools
async with httpx.AsyncClient() as client:
    response = await client.get("http://localhost:8000/utcp")
    manual = response.json()

# 2. Find a tool
chat_tool = next(t for t in manual["tools"] if t["name"] == "chat")

# 3. Call the tool directly
template = chat_tool["tool_call_template"]
response = await client.post(
    template["url"],
    json={"message": "Hello JRVS!"}
)
print(response.json())
```

### With UTCP Python SDK

```bash
pip install utcp utcp-http
```

```python
from utcp import UTCPClient

# Configure client to discover JRVS tools
client = UTCPClient({
    "manual_call_templates": [{
        "name": "jrvs",
        "call_template_type": "http",
        "url": "http://localhost:8000/utcp",
        "http_method": "GET"
    }]
})

# Discover and call tools
await client.discover()
result = await client.call_tool("chat", {"message": "Hello JRVS!"})
```

## Configuration

### Custom Base URL

If running JRVS on a different host or port, the UTCP manual automatically uses the correct base URL:

```bash
# Running on custom port
uvicorn api.server:app --host 0.0.0.0 --port 9000

# UTCP manual will use http://0.0.0.0:9000 as base URL
curl http://localhost:9000/utcp
```

### With Tailscale

If you're using Tailscale for remote access:

```bash
# Access via Tailscale hostname
curl http://your-machine.tail12345.ts.net:8000/utcp
```

## Security

UTCP uses your existing API security. For production deployments:

1. **Enable HTTPS**: Use a reverse proxy (nginx, Caddy) with SSL
2. **Add Authentication**: Implement API keys or OAuth
3. **Rate Limiting**: Configure rate limits in your server
4. **CORS**: Adjust CORS settings in `api/server.py`

Example with API key authentication:

```python
# In api/server.py, add authentication middleware
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.environ.get("JRVS_API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key
```

## Troubleshooting

### UTCP endpoint not accessible

1. Ensure the API server is running:
   ```bash
   curl http://localhost:8000/health
   ```

2. Check if the port is available:
   ```bash
   lsof -i :8000
   ```

### Tools not working

1. Verify Ollama is running for chat/model tools:
   ```bash
   ollama serve
   ```

2. Check JRVS database is initialized:
   ```bash
   python main.py  # Run once to initialize
   ```

### Connection refused

1. Check firewall settings
2. Ensure you're using the correct host/port
3. For remote access, consider using Tailscale or SSH tunneling

## Resources

- **UTCP Specification**: https://github.com/universal-tool-calling-protocol/utcp-specification
- **UTCP Python SDK**: https://pypi.org/project/utcp/
- **JRVS Documentation**: [README.md](../README.md)
- **MCP Integration**: [MCP_SETUP.md](MCP_SETUP.md) (for MCP-specific features)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  AI Agent (Claude, GPT, Custom)                         │
└───────────────┬─────────────────────────────────────────┘
                │ 1. GET /utcp (discover)
                ↓
┌─────────────────────────────────────────────────────────┐
│  JRVS API Server (FastAPI)                              │
│  ├─ GET /utcp        → Returns UTCP Manual              │
│  ├─ POST /api/chat   → Chat with AI                     │
│  ├─ GET /api/models  → List models                      │
│  ├─ GET /api/search  → Search knowledge base            │
│  └─ ...              → Other endpoints                  │
└───────────────┬─────────────────────────────────────────┘
                │ 2. Direct HTTP calls
                ↓
┌─────────────────────────────────────────────────────────┐
│  JRVS Core Components                                   │
│  ├─ RAG Retriever (FAISS + BERT)                        │
│  ├─ Ollama Client (LLM)                                 │
│  ├─ Calendar (SQLite)                                   │
│  ├─ Database (Conversations)                            │
│  └─ Web Scraper (BeautifulSoup)                         │
└─────────────────────────────────────────────────────────┘
```

---

**JRVS + UTCP = Direct, Fast, Simple AI Tool Integration!** 🚀
