# JRVS MCP Servers Guide

## Available MCP Servers on Your System

Based on what I found, you have these MCP servers available:

### 1. **Filesystem Server** ✅
- **Package**: `@modelcontextprotocol/server-filesystem`
- **What it does**: File operations (read, write, list, search files)
- **Already cached**: Yes (found in ~/.npm/_npx/)

### 2. **Memory Server** ✅
- **Package**: `@modelcontextprotocol/server-memory`
- **What it does**: Persistent key-value storage for notes/data
- **Already cached**: Yes (found in ~/.npm/_npx/)

### 3. **JRVS Server** ✅ (Your own!)
- **Location**: `/home/xmanz/JRVS/mcp/server.py`
- **What it does**: RAG, Calendar, JARCORE, Web Scraping (20+ tools)
- **Already built**: Yes!

## Quick Setup

### Step 1: Test MCP Server Discovery

```bash
cd /home/xmanz/JRVS
python3 connect_mcp_servers.py
```

This will:
- ✅ Connect to filesystem, memory, and JRVS servers
- ✅ List all available tools
- ✅ Test connections

### Step 2: Connect JRVS to MCP Servers

The configuration is already created in `mcp_config.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/xmanz"]
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    },
    "jrvs": {
      "command": "python3",
      "args": ["/home/xmanz/JRVS/mcp/server.py"]
    }
  }
}
```

### Step 3: Use MCP Tools in JRVS

Once connected, you can use tools from any server:

```python
# In JRVS chat or code:

# Use filesystem tools
> List files in my home directory
[Uses filesystem/list_directory]

# Use memory tools
> Remember that my favorite color is blue
[Uses memory/store]

# Use JRVS tools
> Analyze my sales.csv file
[Uses JRVS/analyze_code or data analysis tools]
```

## More MCP Servers You Can Install

### Popular Official MCP Servers:

```bash
# GitHub integration
npx -y @modelcontextprotocol/server-github

# Google Drive
npx -y @modelcontextprotocol/server-gdrive

# SQLite database
npx -y @modelcontextprotocol/server-sqlite

# Brave Search
npx -y @modelcontextprotocol/server-brave-search

# Fetch (HTTP requests)
npx -y @modelcontextprotocol/server-fetch

# Git operations
npx -y @modelcontextprotocol/server-git
```

### Add to mcp_config.json:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "your_token_here"
      }
    },
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your_api_key"
      }
    }
  }
}
```

## What Each Server Gives You

### Filesystem Server
- `read_file` - Read any file
- `write_file` - Write/create files
- `list_directory` - List directory contents
- `search_files` - Search for files
- `get_file_info` - File metadata
- `move_file` - Move/rename files
- `create_directory` - Create folders

### Memory Server
- `store` - Save key-value pairs
- `retrieve` - Get stored values
- `list_keys` - List all keys
- `delete` - Remove entries
- Perfect for: Notes, preferences, temporary data

### JRVS Server (Yours!)
- **RAG Tools**: search_knowledge_base, add_document, scrape_and_index_url
- **Calendar**: get_calendar_events, create_event, mark_completed
- **JARCORE**: generate_code, analyze_code, fix_errors, refactor_code
- **Ollama**: list_models, switch_model, generate_with_ollama
- **Data Analysis**: upload_csv, query_data, ai_insights (NEW!)
- And 20+ more tools!

## Use Cases

### 1. **Smart File Management**
```
You: "Find all Python files in my projects folder modified in the last week"

JRVS uses:
- filesystem/search_files
- Filters by date
- Returns results
```

### 2. **Persistent Memory**
```
You: "Remember that I prefer deepseek-coder for coding tasks"

JRVS uses:
- memory/store with key "preferred_coding_model"
- Next time: Auto-switches to deepseek-coder
```

### 3. **Multi-Server Workflow**
```
You: "Analyze my data.csv and save insights to notes"

JRVS:
1. filesystem/read_file → load CSV
2. jrvs/ai_insights → analyze with JARCORE
3. memory/store → save insights
```

## Testing MCP Connections

```bash
# Test filesystem
python3 -c "
import asyncio
from mcp.client import mcp_client

async def test():
    await mcp_client.add_server('fs', 'npx', ['-y', '@modelcontextprotocol/server-filesystem', '/home/xmanz'])
    tools = await mcp_client.list_server_tools('fs')
    print(f'✅ {len(tools)} tools available')

asyncio.run(test())
"

# Test memory
python3 -c "
import asyncio
from mcp.client import mcp_client

async def test():
    await mcp_client.add_server('mem', 'npx', ['-y', '@modelcontextprotocol/server-memory'])
    result = await mcp_client.call_tool('mem', 'store', {'key': 'test', 'value': 'works!'})
    print(f'✅ Memory test: {result}')

asyncio.run(test())
"
```

## Architecture

```
┌─────────────────────────────────────────────┐
│              JRVS (MCP Client)              │
│  - Chat interface                           │
│  - Intelligent agent                        │
│  - Tool orchestration                       │
└─────────────────┬───────────────────────────┘
                  │
        ┌─────────┴──────────┬──────────┐
        │                    │          │
┌───────▼────────┐  ┌────────▼─────┐  ┌▼──────────┐
│   Filesystem   │  │    Memory    │  │   JRVS    │
│   MCP Server   │  │  MCP Server  │  │MCP Server │
│                │  │              │  │           │
│ • read_file    │  │ • store      │  │• JARCORE  │
│ • write_file   │  │ • retrieve   │  │• RAG      │
│ • list_dir     │  │ • list_keys  │  │• Calendar │
└────────────────┘  └──────────────┘  └───────────┘
```

## Current Status

✅ **Filesystem server**: Cached and ready
✅ **Memory server**: Cached and ready
✅ **JRVS server**: Built and functional
✅ **Configuration**: Created (mcp_config.json)
✅ **Discovery script**: Ready (connect_mcp_servers.py)

## Next Steps

1. **Run discovery**:
   ```bash
   python3 connect_mcp_servers.py
   ```

2. **Start JRVS with MCP**:
   ```bash
   python3 web_server.py
   # JRVS will auto-connect to configured servers
   ```

3. **Test in chat**:
   ```
   > List files in my Documents folder
   > Remember my API key is xyz123
   > Generate Python code for data analysis
   ```

4. **Add more servers** (optional):
   - Edit `mcp_config.json`
   - Add GitHub, Brave Search, etc.
   - Restart JRVS

## Troubleshooting

**"MCP package not installed"**:
```bash
pip install mcp
```

**"npx command not found"**:
```bash
# Install Node.js/npm first
```

**Server won't connect**:
```bash
# Test manually
npx -y @modelcontextprotocol/server-filesystem /home/xmanz
# Should start without errors
```

---

**JRVS is now an MCP client with access to multiple tool servers!** 🚀
