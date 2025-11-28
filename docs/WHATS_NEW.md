# What's New in JRVS 🎉

## Recent Updates

### 🔌 MCP Client Integration (NEW!)

JRVS can now **use external tools** by connecting to MCP servers! This is a game-changer.

**What this means:**
- JRVS was already an MCP **server** (others can use JRVS as a tool)
- Now JRVS is also an MCP **client** (JRVS can use external tools)
- Think of it like giving JRVS superpowers from other services!

**Examples of what JRVS can now do:**
- 📁 Read/write files on your system (via filesystem server)
- 🐙 Create GitHub issues and PRs (via github server)
- 🔍 Search the web (via brave-search server)
- 💾 Access databases (via postgres/sqlite servers)
- 📝 Keep persistent notes across sessions (via memory server)
- 💬 Send Slack messages (via slack server)

**Quick Start:**
1. Edit `mcp/client_config.json` to add servers
2. Start JRVS - it auto-connects
3. Use `/mcp-servers` and `/mcp-tools` to explore
4. Call tools with `/mcp-call <server> <tool> <json_args>`

📖 Full guide: [MCP_CLIENT_GUIDE.md](MCP_CLIENT_GUIDE.md)

---

### 📅 Smart Calendar with ASCII View

**Interactive monthly calendar:**
```
╔══════════════════════════════════════════════════════════════╗
║ November 2025                                                ║
╠══════════════════════════════════════════════════════════════╣
║ Sun    Mon    Tue    Wed    Thu    Fri    Sat          ║
╠══════════════════════════════════════════════════════════════╣
║   2       3       4       5       6       7       8     ║
║   9      10     [11]     12*     13      14      15     ║
║  16      17      18      19      20      21      22     ║
║  23      24      25      26      27      28      29     ║
║  30                                               ║
╚══════════════════════════════════════════════════════════════╝

Legend: [DD] = Today  | DD* = Has Events | [DD]* = Today + Events
```

**Natural language event creation:**
- "add event study time tomorrow at 10 am"
- "meeting with team today at 3pm"
- "schedule dentist 2025-11-20 at 2:30 pm"

**Commands:**
- `/month` - Show current month calendar
- `/month 12 2025` - Show specific month
- `/calendar` - Upcoming events (7 days)
- `/today` - Today's events

---

### 🎨 Enhanced CLI Experience

**New commands:**
- `/mcp-servers` - List connected MCP servers
- `/mcp-tools` - Browse available tools
- `/month` - ASCII calendar view
- `/today` - Today's events

**Improved help:**
- Organized by category
- Examples for complex commands
- Tips for natural language features

---

## Previous Features

### 🧠 RAG Pipeline
- FAISS vector search with BERT embeddings
- Automatic context injection for better responses
- Web scraping and document indexing

### 🔄 Dynamic Model Switching
- Hot-swap between Ollama models
- Multiple model support
- No restart needed

### 🎨 Beautiful Themes
- Matrix (green hacker style)
- Cyberpunk (magenta/cyan)
- Minimal (clean B&W)

### 💾 Persistent Storage
- SQLite database for conversations
- Document and embedding storage
- Session history

### ⚡ Performance
- Lazy loading
- Async operations
- Connection pooling
- Caching

---

## Coming Soon

- 🤖 AI-powered MCP tool selection (JRVS automatically picks the right tool)
- 🗣️ Voice input/output
- 🌐 Web UI alongside CLI
- 📊 Analytics dashboard
- 🔐 Better auth/security for MCP connections
- 📱 Mobile companion app

---

## Migration Notes

**For existing users:**
- No breaking changes!
- MCP client is optional - JRVS works fine without it
- Calendar feature uses existing database
- All old commands still work

**New dependencies:**
- MCP client libraries (already in requirements.txt)
- Node.js (only if using MCP servers that need it)

---

## Support

- 📖 Docs: See README.md and MCP_CLIENT_GUIDE.md
- 🐛 Issues: Create an issue on GitHub
- 💡 Ideas: Open a discussion

Enjoy the new features! 🚀
