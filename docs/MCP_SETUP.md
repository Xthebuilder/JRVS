# JRVS MCP Server Setup Guide

This guide will help you set up and use JRVS as an MCP (Model Context Protocol) server with Claude Code and other MCP-compatible clients.

## What is MCP?

Model Context Protocol (MCP) is an open protocol that enables AI applications like Claude Code to connect to external data sources and tools. By running JRVS as an MCP server, Claude Code can:

- Query JRVS's RAG-powered knowledge base
- Scrape and index web content
- Manage calendar events
- Switch between Ollama models
- Access conversation history
- And more!

## Prerequisites

- Python 3.10 or higher
- JRVS already installed and configured
- Ollama running locally (for LLM features)

## Installation

### 1. Install MCP Dependencies

```bash
cd /home/xmanz/JRVS
pip install -r requirements.txt
```

This will install the `mcp>=1.2.0` package along with other JRVS dependencies.

### 2. Verify Installation

Test that the MCP server starts correctly:

```bash
python mcp/server.py
```

You should see output like:
```
Starting JRVS MCP Server...
Ollama URL: http://localhost:11434
Default Model: deepseek-r1:14b
✓ JRVS components initialized
✓ MCP server ready
```

Press Ctrl+C to stop the server.

## Configuration for Claude Code

### Option 1: Using the Provided Config File

1. Copy the MCP configuration:

```bash
# For Claude Desktop/Code
mkdir -p ~/.config/claude
cp /home/xmanz/JRVS/mcp/claude_config.json ~/.config/claude/mcp_servers.json
```

2. Edit `~/.config/claude/mcp_servers.json` to adjust paths if needed:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "python",
      "args": [
        "/home/xmanz/JRVS/mcp/server.py"
      ],
      "env": {
        "PYTHONPATH": "/home/xmanz/JRVS"
      }
    }
  }
}
```

### Option 2: Manual Configuration

Add this to your Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "python",
      "args": [
        "/home/xmanz/JRVS/mcp/server.py"
      ],
      "env": {
        "PYTHONPATH": "/home/xmanz/JRVS"
      }
    }
  }
}
```

### Option 3: Using uv (Alternative)

If you have `uv` installed:

```bash
cd /home/xmanz/JRVS
uv add "mcp[cli]"
```

Then update your config to use `uv`:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "uv",
      "args": [
        "run",
        "mcp/server.py"
      ]
    }
  }
}
```

## Available MCP Tools

Once configured, Claude Code will have access to these JRVS tools:

### Knowledge Base & RAG
- **search_knowledge_base** - Search JRVS's vector database semantically
- **get_context_for_query** - Get enriched RAG context for a query
- **add_document_to_knowledge_base** - Add documents for indexing
- **scrape_and_index_url** - Scrape websites and add to knowledge base
- **get_rag_stats** - Get statistics about the RAG system

### Ollama LLM
- **list_ollama_models** - List all available Ollama models
- **get_current_model** - Get the active model
- **switch_ollama_model** - Switch to a different model
- **generate_with_ollama** - Generate responses with RAG context

### Calendar
- **get_calendar_events** - Get upcoming events
- **get_today_events** - Get today's events
- **create_calendar_event** - Create new events
- **delete_calendar_event** - Delete events
- **mark_event_completed** - Mark events as done

### Conversation History
- **get_conversation_history** - Retrieve past conversations

### Resources (Read-Only Data)
- **jrvs://config** - View JRVS configuration
- **jrvs://status** - Check system status

## Usage Examples

Once Claude Code is connected to JRVS MCP server, you can use natural language:

### Example 1: Search Knowledge Base
```
User: "Search JRVS knowledge base for Python best practices"
Claude Code uses: search_knowledge_base(query="Python best practices", limit=5)
```

### Example 2: Add Content
```
User: "Scrape https://docs.python.org/3/tutorial/ and add it to JRVS"
Claude Code uses: scrape_and_index_url(url="https://docs.python.org/3/tutorial/")
```

### Example 3: Calendar Management
```
User: "What's on my calendar today?"
Claude Code uses: get_today_events()

User: "Create a meeting for tomorrow at 2pm"
Claude Code uses: create_calendar_event(title="Meeting", event_date="2025-11-12T14:00:00")
```

### Example 4: Model Switching
```
User: "Switch JRVS to use llama3.1"
Claude Code uses: switch_ollama_model(model_name="llama3.1")
```

### Example 5: RAG-Enhanced Generation
```
User: "Ask JRVS about machine learning using its knowledge base"
Claude Code uses: generate_with_ollama(prompt="Explain machine learning", context=<RAG context>)
```

## Testing the Integration

### 1. Test MCP Server Directly

You can test the MCP server using the MCP inspector:

```bash
npx @modelcontextprotocol/inspector python mcp/server.py
```

This will open a web interface to interact with your MCP server and test all tools.

### 2. Test with Claude Code

1. Restart Claude Code after adding the MCP configuration
2. Start a conversation and ask: "What MCP servers are connected?"
3. Try using JRVS tools: "Search JRVS knowledge base for AI"

## Troubleshooting

### "Cannot connect to Ollama"
- Make sure Ollama is running: `ollama serve`
- Check if it's accessible: `curl http://localhost:11434/api/tags`

### "MCP module not found"
- Install MCP: `pip install 'mcp[cli]'`
- Verify Python version: `python --version` (needs 3.10+)

### "Failed to initialize JRVS components"
- Run JRVS normally first: `python main.py`
- Check that the database exists: `ls data/jarvis.db`
- Verify Ollama models are available: `ollama list`

### "MCP server not showing in Claude Code"
- Check Claude Code MCP configuration file location
- Verify the path to `mcp/server.py` is correct
- Check logs in Claude Code settings
- Restart Claude Code

### "Permission denied"
- Make the server executable: `chmod +x mcp/server.py`
- Check Python is in your PATH: `which python`

## Advanced Configuration

### Environment Variables

You can customize JRVS MCP behavior via environment variables:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "python",
      "args": ["/home/xmanz/JRVS/mcp/server.py"],
      "env": {
        "PYTHONPATH": "/home/xmanz/JRVS",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "DEFAULT_MODEL": "llama3.1"
      }
    }
  }
}
```

### Running with Custom Config

Edit `/home/xmanz/JRVS/config.py` to customize:
- Default Ollama model
- Timeout settings
- RAG parameters (chunk size, context length, etc.)
- Database paths

## Architecture

```
Claude Code (MCP Client)
    ↓
    MCP Protocol (stdio/JSON-RPC)
    ↓
JRVS MCP Server (mcp/server.py)
    ↓
    ├─→ RAG System (rag/)
    │   ├─→ Vector Store (FAISS)
    │   ├─→ Embeddings (BERT)
    │   └─→ Retriever
    │
    ├─→ Ollama Client (llm/)
    │   └─→ Local LLMs
    │
    ├─→ Calendar (core/calendar.py)
    │
    ├─→ Web Scraper (scraper/)
    │
    └─→ Database (SQLite)
```

## Security Notes

- MCP server runs locally and only accepts connections from the same machine
- No external network exposure by default
- All data stays on your local system
- Scraped content is stored in your local SQLite database

## Next Steps

1. Try searching your existing JRVS knowledge base from Claude Code
2. Add new documents or scrape websites through MCP
3. Use JRVS's RAG capabilities to enhance Claude Code responses
4. Manage your calendar and tasks through natural language
5. Experiment with different Ollama models via MCP tools

## Support & Documentation

- **JRVS Documentation**: See README.md and QUICKSTART.md
- **MCP Documentation**: https://modelcontextprotocol.io
- **Claude Code MCP**: Check Claude Code documentation for MCP integration

---

**Happy building with JRVS + MCP!** 🚀
