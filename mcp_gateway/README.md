# JRVS MCP Server

This directory contains the Model Context Protocol (MCP) server implementation for JRVS.

## Quick Start

### 1. Install Dependencies
```bash
pip install -r ../requirements.txt
```

### 2. Test the Server
```bash
python test_server.py
```

### 3. Run the MCP Server
```bash
python server.py
```

The server will start and wait for MCP client connections via stdio.

## Files

- `server.py` - Main MCP server with all JRVS tools
- `test_server.py` - Component test script
- `claude_config.json` - Example Claude Code configuration
- `README.md` - This file

## Available Tools

### Knowledge Base (17 tools total)
- `search_knowledge_base` - Semantic search
- `get_context_for_query` - Get RAG context
- `add_document_to_knowledge_base` - Index documents
- `scrape_and_index_url` - Web scraping
- `get_rag_stats` - System statistics
- `list_ollama_models` - List LLM models
- `get_current_model` - Current model info
- `switch_ollama_model` - Switch models
- `generate_with_ollama` - Generate with RAG
- `get_calendar_events` - Upcoming events
- `get_today_events` - Today's events
- `create_calendar_event` - Create events
- `delete_calendar_event` - Delete events
- `mark_event_completed` - Complete events
- `get_conversation_history` - Chat history

### Resources
- `jrvs://config` - Configuration info
- `jrvs://status` - System status

## Integration with Claude Code

### Method 1: Environment Variable (Recommended for Testing)

```bash
export CLAUDE_MCP_SERVER='{"jrvs": {"command": "python", "args": ["/home/xmanz/JRVS/mcp/server.py"], "env": {"PYTHONPATH": "/home/xmanz/JRVS"}}}'
```

### Method 2: Configuration File

Create or edit `~/.config/claude/mcp_servers.json`:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "python",
      "args": ["/home/xmanz/JRVS/mcp/server.py"],
      "env": {
        "PYTHONPATH": "/home/xmanz/JRVS"
      }
    }
  }
}
```

Then restart Claude Code.

## Testing

Test individual components:
```bash
python test_server.py
```

Test with MCP inspector (requires Node.js):
```bash
npx @modelcontextprotocol/inspector python server.py
```

## Troubleshooting

**Import Error**: Make sure `mcp` package is installed:
```bash
pip install 'mcp[cli]'
```

**Ollama Not Available**: Start Ollama service:
```bash
ollama serve
```

**Database Not Found**: Run JRVS normally first:
```bash
cd .. && python main.py
```

## Architecture

```
MCP Client (Claude Code)
    ↓ stdio/JSON-RPC
MCP Server (server.py)
    ↓
FastMCP (@tool decorators)
    ↓
JRVS Components
    ├─ rag_retriever (RAG/Vector Search)
    ├─ ollama_client (LLM Interface)
    ├─ calendar (Event Management)
    ├─ db (SQLite Storage)
    └─ web_scraper (Content Ingestion)
```

## Development

To add new tools, use the `@mcp.tool()` decorator in `server.py`:

```python
@mcp.tool()
async def my_new_tool(param: str) -> dict:
    """Tool description for Claude"""
    # Your implementation
    return {"result": "value"}
```

For resources (read-only data), use `@mcp.resource()`:

```python
@mcp.resource("jrvs://my-resource")
def my_resource() -> str:
    """Resource description"""
    return "Resource data"
```

## See Also

- [MCP_SETUP.md](../MCP_SETUP.md) - Complete setup guide
- [README.md](../README.md) - JRVS documentation
- [Model Context Protocol](https://modelcontextprotocol.io) - Official MCP docs
