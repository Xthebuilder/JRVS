# JRVS MCP Integration - Quick Start

Your JRVS AI assistant now has full MCP (Model Context Protocol) support! 🚀

## What You Get

Claude Code can now directly:
- 🔍 Search your JRVS knowledge base semantically
- 🌐 Scrape websites and add them to JRVS
- 📅 Manage your calendar events
- 🤖 Switch between Ollama models
- 💬 Access conversation history
- 📊 Get system statistics

## Installation (Already Done!)

✅ MCP server created at `mcp/server.py`
✅ 17 tools + 2 resources implemented
✅ Dependencies added to requirements.txt
✅ Test suite passed (4/4 components working)

## Usage

### Option 1: Test Locally First

```bash
# Test components
python mcp/test_server.py

# Run server (will wait for stdio connection)
python mcp/server.py
```

### Option 2: Connect to Claude Code

**Edit your Claude Code MCP config** (`~/.config/claude/mcp_servers.json` or similar):

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

**Then restart Claude Code.**

## Example Usage in Claude Code

Once connected, you can ask:

```
"Search JRVS for information about Python best practices"
→ Uses: search_knowledge_base(query="Python best practices")

"Add https://docs.python.org to JRVS knowledge base"
→ Uses: scrape_and_index_url(url="https://docs.python.org")

"What's on my calendar this week?"
→ Uses: get_calendar_events(days=7)

"Switch JRVS to llama3.1 model"
→ Uses: switch_ollama_model(model_name="llama3.1")

"Ask JRVS about machine learning with context"
→ Uses: generate_with_ollama(prompt="...", context=<RAG>)
```

## Available Tools (17 total)

### 🧠 RAG & Knowledge Base
- `search_knowledge_base` - Semantic vector search
- `get_context_for_query` - Get enriched RAG context
- `add_document_to_knowledge_base` - Index documents
- `scrape_and_index_url` - Web scraping
- `get_rag_stats` - System statistics

### 🤖 Ollama LLM
- `list_ollama_models` - Available models
- `get_current_model` - Current model info
- `switch_ollama_model` - Change models
- `generate_with_ollama` - Generate with RAG

### 📅 Calendar
- `get_calendar_events` - Upcoming events
- `get_today_events` - Today's schedule
- `create_calendar_event` - New events
- `delete_calendar_event` - Remove events
- `mark_event_completed` - Complete events

### 💬 Conversation
- `get_conversation_history` - Past conversations

### 📊 Resources (Read-Only)
- `jrvs://config` - Configuration
- `jrvs://status` - System status

## Test Results

```
✓ Database initialized
✓ RAG initialized (vectors: 0)
✓ Calendar initialized (0 events)
✓ Ollama connected (12 models)
```

All systems ready!

## Next Steps

1. **Add Content**: Scrape some websites to build your knowledge base
   ```bash
   # Via CLI
   python main.py
   /scrape https://example.com
   ```

2. **Try MCP**: Connect Claude Code and start using JRVS tools

3. **Explore**: Check `MCP_SETUP.md` for detailed documentation

## Files Created

```
mcp/
├── __init__.py           # Package init
├── server.py             # MCP server (17 tools)
├── test_server.py        # Component tests
├── claude_config.json    # Example config
└── README.md             # MCP directory docs

MCP_SETUP.md              # Complete setup guide (this file)
MCP_QUICKSTART.md         # Quick reference
```

## Troubleshooting

**"MCP package not found"**
```bash
pip install 'mcp[cli]'
```

**"Cannot connect to Ollama"**
```bash
ollama serve
```

**"Database not found"**
```bash
python main.py  # Run JRVS once to initialize
```

## Documentation

- **Full Guide**: See `MCP_SETUP.md`
- **MCP Dir**: See `mcp/README.md`
- **JRVS Docs**: See `README.md`
- **Official MCP**: https://modelcontextprotocol.io

---

**Your JRVS is now MCP-enabled!** 🎉

Use it with Claude Code to supercharge your AI workflows with persistent knowledge, RAG-enhanced responses, and calendar management.
