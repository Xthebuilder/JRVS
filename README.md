# Jarvis AI Agent 🤖

A sophisticated AI assistant that combines Ollama LLMs with RAG (Retrieval-Augmented Generation) capabilities, featuring web scraping, vector search, and intelligent context injection.

## ✨ Features

- **🧠 RAG Pipeline**: FAISS vector search with BERT embeddings for intelligent context retrieval
- **🔄 Dynamic Model Switching**: Hot-swap between different Ollama models
- **🌐 Web Scraping**: Automatically scrape and index web content with BeautifulSoup
- **🔌 MCP Integration**: Both MCP **Server** (be a tool for others) AND **Client** (use external tools)
- **📅 Smart Calendar**: ASCII calendar view with natural language event creation
- **🎨 Beautiful CLI**: Customizable themes (Matrix, Cyberpunk, Minimal) with Rich terminal UI
- **💾 Persistent Memory**: Conversation history and document storage in SQLite
- **⚡ Performance Optimized**: Lazy loading, caching, and async operations
- **🛡️ Robust**: Timeout handling, circuit breakers, and graceful error recovery
- **📊 Smart Analytics**: Usage statistics and system health monitoring

## 🚀 Quick Start

### Prerequisites

1. **Python 3.8+** 
2. **Ollama** - [Install Ollama](https://ollama.ai)

### Installation

1. **Clone or download the project**:
```bash
cd jarvis_ai_agent
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Start Ollama** (in another terminal):
```bash
ollama serve
```

4. **Pull some models** (choose what you prefer):
```bash
ollama pull llama3.1
ollama pull codellama
ollama pull mistral
```

5. **Run Jarvis**:
```bash
python main.py
```

## 🎯 Usage

### Basic Chat
Just type your questions and Jarvis will respond with enhanced context from its knowledge base:

```
jarvis❯ What is machine learning?
```

### Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/models` | List available Ollama models |
| `/switch <model>` | Switch to different AI model |
| `/scrape <url>` | Scrape website and add to knowledge base |
| `/search <query>` | Search stored documents |
| `/calendar` | Show upcoming events (7 days) |
| `/month [month] [year]` | Show ASCII calendar for month |
| `/today` | Show today's events |
| `/mcp-servers` | List connected MCP servers |
| `/mcp-tools [server]` | List MCP tools |
| `/stats` | Show system statistics |
| `/history` | Show conversation history |
| `/theme <name>` | Change CLI theme |
| `/clear` | Clear screen |
| `/exit` | Exit Jarvis |

### Examples

**Scrape a website:**
```
jarvis❯ /scrape https://python.org/dev/pep/pep-8/
```

**Switch AI model:**
```
jarvis❯ /switch codellama
```

**Search your knowledge base:**
```
jarvis❯ /search python best practices
```

**Change theme:**
```
jarvis❯ /theme cyberpunk
```

## 🧬 How It Works

### RAG (Retrieval-Augmented Generation) Pipeline

1. **Document Ingestion**: Web pages are scraped and chunked into manageable pieces
2. **Embedding Generation**: BERT creates vector embeddings for semantic search
3. **Vector Storage**: FAISS provides fast similarity search across document chunks
4. **Context Injection**: Relevant chunks are automatically added to your prompts
5. **Enhanced Responses**: Ollama generates responses with enriched context

### Smart Learning

Jarvis gets smarter over time:
- **Conversation Memory**: Learns from your chat history
- **Document Growth**: More scraped content = better context
- **Usage Patterns**: Optimizes based on your preferences

## 🔌 MCP Client (Connect to External Tools)

JRVS can now act as an **MCP Client**, connecting to MCP servers to access external tools like filesystems, databases, APIs, and more!

### Quick Setup

1. **Configure servers** in `mcp/client_config.json`:
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
    }
  }
}
```

2. **Start JRVS** - it will auto-connect to configured servers

3. **Use MCP commands**:
```bash
/mcp-servers              # List connected servers
/mcp-tools                # List all available tools
/mcp-tools filesystem     # Tools from specific server
```

### Available MCP Servers

- **filesystem** - File operations (read, write, search)
- **github** - GitHub API (issues, PRs, repos)
- **postgres** - PostgreSQL database access
- **brave-search** - Web search
- **memory** - Persistent notes/memory
- **slack** - Slack messaging
- And many more! See `MCP_CLIENT_GUIDE.md`

📖 **Full guide**: See [MCP_CLIENT_GUIDE.md](MCP_CLIENT_GUIDE.md)

## 🛠️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL of the Ollama API server |
| `OLLAMA_DEFAULT_MODEL` | `deepseek-r1:14b` | Default model to use |

Example for connecting to a remote Ollama instance:
```bash
export OLLAMA_BASE_URL="http://192.168.1.100:11434"
export OLLAMA_DEFAULT_MODEL="llama3:8b"
python main.py
```

### Command Line Options

```bash
python main.py --help
```

Options:
- `--theme {matrix,cyberpunk,minimal}` - Set CLI theme
- `--model MODEL_NAME` - Set default Ollama model
- `--ollama-url URL` - Custom Ollama API URL
- `--no-banner` - Skip ASCII banner
- `--debug` - Enable debug mode

### Themes

- **Matrix**: Green-on-black hacker aesthetic
- **Cyberpunk**: Magenta and cyan futuristic style
- **Minimal**: Clean black and white interface

## 📁 Project Structure

```
jarvis_ai_agent/
├── main.py              # Application entry point
├── config.py            # Configuration settings
├── requirements.txt     # Python dependencies
├── core/
│   ├── database.py      # SQLite database operations
│   └── lazy_loader.py   # Performance optimizations
├── rag/
│   ├── embeddings.py    # BERT embedding generation
│   ├── vector_store.py  # FAISS vector operations
│   └── retriever.py     # RAG pipeline coordinator
├── llm/
│   └── ollama_client.py # Ollama API integration
├── cli/
│   ├── interface.py     # Main CLI interface
│   ├── themes.py        # Theme management
│   └── commands.py      # Command handling
├── scraper/
│   └── web_scraper.py   # Web scraping functionality
└── data/                # Generated data directory
    ├── jarvis.db        # SQLite database
    └── faiss_index.*    # Vector index files
```

## 🔧 Advanced Usage

### Custom Model Configuration

Edit `config.py` to customize:
- Default models
- Timeout settings  
- RAG parameters
- Performance limits

### MCP (Model Context Protocol) Integration

JRVS now includes a full-featured MCP server for Claude Code integration:

```bash
# Run MCP server
python mcp/server.py

# Test components
python mcp/test_server.py
```

**17 tools available**: RAG search, web scraping, calendar, model switching, and more!

See [MCP_SETUP.md](MCP_SETUP.md) for complete integration guide.

### API Integration

The modular design allows easy integration:

```python
from rag.retriever import rag_retriever
from llm.ollama_client import ollama_client

# Add document
doc_id = await rag_retriever.add_document(content, title, url)

# Enhanced chat
context = await rag_retriever.retrieve_context(query)
response = await ollama_client.generate(query, context=context)
```

## 🐛 Troubleshooting

### Common Issues

**"Cannot connect to Ollama"**
- Make sure Ollama is running: `ollama serve`
- Check if port 11434 is free
- Verify Ollama installation

**"No models available"**
- Pull at least one model: `ollama pull llama3.1`
- Check model list: `ollama list`

**Import errors**
- Install dependencies: `pip install -r requirements.txt`
- Check Python version: `python --version` (needs 3.8+)

**Performance issues**
- Reduce `MAX_CONTEXT_LENGTH` in config.py
- Use smaller models (e.g., `llama3.1:8b` instead of `llama3.1:70b`)
- Clear vector cache: delete `data/faiss_index.*` files

## 🤝 Contributing

This is a functional RAG system built for learning and experimentation. Feel free to:
- Add new features
- Improve performance
- Fix bugs
- Add new themes
- Enhance the CLI

## ⚖️ License

This project is for educational and personal use. Respect website terms of service when scraping.

## 🙏 Acknowledgments

- **Ollama** for local LLM serving
- **FAISS** for efficient vector search
- **Sentence Transformers** for embeddings
- **Rich** for beautiful terminal UI
- **BeautifulSoup** for web scraping

---

**Happy chatting with Jarvis! 🚀**