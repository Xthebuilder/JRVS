# JRVS Intelligent Agent Guide 🤖

## What Is This?

JRVS now has an **Intelligent Agent** that automatically:
1. ✨ **Detects** when your request needs external tools
2. 🔧 **Chooses** the right MCP tools to use
3. ⚡ **Executes** tools with proper parameters
4. 📝 **Logs** everything with timestamps and reasoning
5. 📊 **Generates** reports of all actions

## How It Works

### Before (Manual)
```bash
# You had to manually call tools
/mcp-call filesystem read_file '{"path": "/tmp/test.txt"}'
```

### Now (Automatic!)
```bash
# Just talk naturally - JRVS figures out what to do
jarvis❯ read the file /tmp/test.txt

🔧 Tools Used:
  ✓ filesystem/read_file
Assistant❯ Here's the content of /tmp/test.txt:
[file contents shown here]
```

## Example Use Cases

### 1. File Operations
```bash
# JRVS automatically uses filesystem tools
jarvis❯ what files are in my Downloads folder?
jarvis❯ create a new file called notes.txt with "Hello World"
jarvis❯ search for python files in my JRVS directory
```

### 2. Memory & Learning
```bash
# JRVS remembers things across sessions
jarvis❯ remember that I prefer Python 3.11 for all projects
jarvis❯ remember my database password is in ~/.secrets/db.txt
jarvis❯ what do you remember about my preferences?
```

### 3. Web Search (if Brave API configured)
```bash
# JRVS searches the web when needed
jarvis❯ search for the latest Python 3.12 features
jarvis❯ find tutorials on async programming
jarvis❯ what are the best practices for FastAPI?
```

### 4. Combined Intelligence
```bash
# JRVS can use multiple tools in sequence
jarvis❯ read my config file and remember my API keys location

🔧 Tools Used:
  ✓ filesystem/read_file
  ✓ memory/create_memory
```

## Viewing Activity Reports

### Quick Report
```bash
/report
```

Shows:
- Total actions taken
- Tools used (with success/failure status)
- Reasoning for each action
- Timestamps and duration
- Summary statistics

### Save Report
```bash
/save-report
```

Saves two files to `data/mcp_logs/`:
1. **JSON log** - Machine-readable, detailed
2. **TXT report** - Human-readable summary

Example report:
```
======================================================================
JRVS MCP AGENT ACTIVITY REPORT
Session: a3b4c5d6...
Generated: 2025-11-11 15:30:45
======================================================================

SUMMARY
----------------------------------------------------------------------
Total Actions: 5
Tool Calls: 3
Successful: 3
Failed: 0
Average Duration: 145.67ms

DETAILED ACTIONS
----------------------------------------------------------------------

1. [15:29:12] ANALYSIS
   Reasoning: User wants to read a file, filesystem tool needed

2. [15:29:12] TOOL CALL - ✓ SUCCESS
   Server: filesystem
   Tool: read_file
   Purpose: Read the contents of /tmp/test.txt
   Parameters: {"path": "/tmp/test.txt"}
   Duration: 123.45ms
   Result: File contents: "Hello, World!\n..."

3. [15:30:01] TOOL CALL - ✓ SUCCESS
   Server: memory
   Tool: create_memory
   Purpose: Store user preference about Python version
   Parameters: {"content": "User prefers Python 3.11"}
   Duration: 89.12ms
   Result: Memory created with ID: mem_123

======================================================================
END OF REPORT
======================================================================
```

## Configuration

### Enable/Disable Automatic Tool Usage

By default, the intelligent agent is **always active**. It analyzes every message to determine if tools are needed.

If you want to **disable** automatic tool usage:
1. Open `mcp_gateway/agent.py`
2. Set `AGENT_ENABLED = False` at the top
3. Restart JRVS

With agent disabled, you can still use tools manually:
```bash
/mcp-call filesystem read_file '{"path": "/tmp/test.txt"}'
```

## Understanding the Decision Process

### How JRVS Decides to Use Tools

1. **Analyzes your message** using AI (Ollama)
2. **Compares** against available MCP tools
3. **Determines** if tools match your request
4. **Generates** parameters automatically
5. **Executes** the tools
6. **Integrates** results into the response

### What Triggers Tool Usage?

**File-related requests:**
- "read the file..."
- "create a file..."
- "list files in..."
- "search for files..."

**Memory requests:**
- "remember that..."
- "what do you remember about..."
- "store this information..."

**Search requests (if Brave configured):**
- "search for..."
- "find information about..."
- "lookup..."

**Just conversations:**
- "what is Python?"
- "explain async programming"
- "tell me a joke"
→ No tools used, normal RAG + LLM response

## Logs & Privacy

### What Gets Logged?

- Tool calls made
- Parameters used
- Results (truncated to 500 chars)
- Timestamps
- Success/failure status
- AI reasoning for tool selection

### Where Are Logs Stored?

```
data/mcp_logs/
├── session_a3b4c5d6_20251111_153045.json  # Detailed JSON
└── report_session_a3b4c5d6_20251111_153045.txt  # Human-readable
```

### Log Retention

- Logs are saved on JRVS exit
- Never automatically deleted
- You can manually clean up old logs
- No data is sent to external servers

## Advanced: Customizing Tool Selection

Edit `mcp_gateway/agent.py` to customize how JRVS selects tools:

```python
# Example: Always use memory for certain keywords
if "important" in user_message.lower():
    # Force memory tool usage
    pass
```

## Troubleshooting

### "No tools were used when they should be"

1. Check MCP servers are connected: `/mcp-servers`
2. Verify tools are available: `/mcp-tools`
3. Check agent logs: `/report`
4. Try being more explicit: "use filesystem to read /tmp/test.txt"

### "Wrong tool was chosen"

The AI occasionally makes mistakes. You can:
1. Be more specific in your request
2. Use manual tool calls: `/mcp-call`
3. Check the reasoning in `/report`

### "Tool call failed"

Check the report to see the error:
```bash
/report
```

Common issues:
- File path doesn't exist (filesystem)
- Permissions denied (filesystem)
- API key missing/invalid (brave-search)
- Server not running (any)

## Performance

### Speed Impact

- Analysis adds ~200-500ms per message
- Actual tool calls vary by tool
- Overall: Slight delay, but worth it!

### Reducing Latency

1. Use faster Ollama models (e.g., `llama3.1:8b` instead of `70b`)
2. Pre-warm connections (already done automatically)
3. Disable agent if not needed (see Configuration section)

## Examples in Action

### Complete Workflow Example

```bash
jarvis❯ read my TODO file and create calendar events for each item

🔧 Tools Used:
  ✓ filesystem/read_file
  ✓ memory/create_memory
  ✓ (calendar events created via built-in feature)

Assistant❯ I've read your TODO.txt file with 5 items. I'll create calendar
events for each:
1. ✓ "Team meeting" - Created event for tomorrow at 2pm
2. ✓ "Code review" - Created event for Wed at 10am
...
```

### Research & Document

```bash
jarvis❯ search for Python best practices and save key points to notes.txt

🔧 Tools Used:
  ✓ brave-search/brave_web_search
  ✓ filesystem/write_file

Assistant❯ I've searched for Python best practices and compiled the top
recommendations. Saved to /home/xmanz/Documents/notes.txt with:
- Use type hints
- Follow PEP 8
- Write unit tests
...
```

## Tips & Best Practices

1. **Be Natural** - Just chat like you normally would
2. **Be Specific** - File paths, exact terms, etc.
3. **Check Reports** - Use `/report` to see what JRVS did
4. **Build Habits** - Use memory tool to teach JRVS your preferences
5. **Explore Tools** - Run `/mcp-tools` to see what's possible

## What's Next?

Future improvements planned:
- 🔄 Multi-step tool chains
- 🧠 Better context awareness
- 📊 Analytics dashboard
- 🎯 User-trainable preferences
- 🔌 More MCP servers out of the box

---

**You're all set!** 🚀 JRVS will now intelligently use tools whenever needed. Just chat naturally and let the agent handle the heavy lifting.
