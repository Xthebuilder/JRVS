
JRVS is a local-first AI agent framework designed for developers who want control, extensibility, and predictable behavior when working with local language models and tools.
JRVS prioritizes clear architectural boundaries, low operational overhead, and explicit tradeoffs over opaque abstraction or cloud dependency.
Why JRVS Exists
Most AI agent frameworks optimize for:
Hosted models
Rapid experimentation
Maximum abstraction
JRVS is optimized for a different set of constraints:
Local inference (CPU/GPU, quantized models, limited memory)
Offline or privacy-sensitive workflows
Explicit control over tools, memory, and retrieval
Extensibility without tight coupling
The result is a system that may overlap in capabilities with other tools, but differs fundamentally in design goals and execution model.
Design Principles
JRVS is built around a few intentional principles:
1. Local-First by Default
JRVS assumes models run locally (e.g. via Ollama or similar runtimes).
This forces explicit handling of:
Memory constraints
Latency tradeoffs
Hardware variability
Cloud-hosted APIs are not the primary target.
2. Explicit Architecture Over Magic
Core subsystems are clearly separated:
Agent core
Retrieval-augmented generation (RAG)
Persistent memory
Tool and protocol layer
CLI and API interfaces
This makes behavior predictable, debuggable, and extensible.
3. Protocol-Based Tooling
JRVS uses tool protocols (MCP / UTCP) instead of hard-coded integrations.
This allows:
Tools to be added without modifying the core agent
Loose coupling between execution and capability
Safer extension by third parties
4. Practical Persistence
JRVS uses SQLite and FAISS for memory and retrieval.
This choice favors:
Simplicity
Local reliability
Zero-ops setup
The tradeoff is reduced horizontal scalability, which is an intentional non-goal for a local-first system.
5. Designed for Builders, Not Demos
JRVS exposes:
A CLI for direct use
An API for integration
Configuration surfaces instead of hidden defaults
Once a system has users, behavior must be explicit. JRVS treats that as a requirement, not an afterthought.
What JRVS Is (and Isn’t)
JRVS is:
A framework for building local AI agents
A developer tool, not a hosted service
Opinionated about constraints, flexible about extension
JRVS is not:
A cloud-scale, multi-tenant agent platform
A no-code or consumer AI product
A replacement for every agent framework
If you need distributed orchestration or SaaS-style scaling, a different architecture is more appropriate.
Core Features
Local LLM integration (e.g. Ollama)
Retrieval-Augmented Generation (FAISS + embeddings)
Persistent memory (SQLite)
Protocol-based tool calling (MCP / UTCP)
Modular architecture
CLI and API interfaces
Web scraping and indexing support
Tradeoffs (Explicit by Design)
JRVS makes the following tradeoffs deliberately:
Simplicity over horizontal scalability
Local control over hosted convenience
Explicit configuration over hidden automation
Extensibility over monolithic design
These choices reflect the environments JRVS is designed for.
Who Should Use JRVS
JRVS is a good fit if you:
Run models locally
Care about privacy or offline workflows
Want to understand and extend the system
Prefer clear architecture over opaque abstraction
JRVS is likely not a good fit if you:
Need managed cloud infrastructure
Want zero configuration
Are optimizing for multi-tenant scale
Project Status
JRVS is actively developed and used by developers experimenting with and building local AI workflows.
Breaking changes are avoided where possible, but architectural clarity takes priority over strict backward compatibility at this stage.
Contributing
Contributions are welcome, especially around:
Tool protocol extensions
Performance improvements
Documentation and design feedback
Please open an issue before large changes to align on direction.

## Quick Start

### Prerequisites

1. **Python 3.8+** - [Download Python](https://python.org/downloads/)
2. **Ollama** OR **LM Studio** - Choose one LLM provider:
   - [Install Ollama](https://ollama.ai)
   - [Install LM Studio](https://lmstudio.ai)
3. **Node.js** (optional, for MCP servers and web UI) - [Download Node.js](https://nodejs.org/)

### Automated Setup (Recommended)

Use the platform-specific setup scripts to automatically install dependencies:

#### Windows
```cmd
setup_windows.bat
```

#### macOS
```bash
chmod +x setup_mac.sh
./setup_mac.sh
```

### Manual Installation

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

---

## Platform-Specific Setup

### Windows Setup

#### Prerequisites

1. **Python 3.8+**
   - Download from [python.org](https://python.org/downloads/)
   - **Important**: Check "Add Python to PATH" during installation
   - Verify installation: `python --version`

2. **Ollama**
   - Download from [ollama.ai/download](https://ollama.ai/download)
   - Run the installer and follow the prompts
   - Verify installation: `ollama --version`

3. **Node.js** (optional, for MCP and web UI)
   - Download from [nodejs.org](https://nodejs.org/)
   - Choose the LTS version
   - Verify installation: `node --version`

4. **Git** (optional, for cloning)
   - Download from [git-scm.com](https://git-scm.com/download/win)

#### Quick Setup

Run the automated setup script:
```cmd
setup_windows.bat
```

Or manually:
```cmd
pip install -r requirements.txt
ollama serve
ollama pull llama3.1
python main.py
```

#### Windows-Specific Tips

- **PowerShell vs Command Prompt**: Both work, but PowerShell offers better features
- **Virtual Environment** (recommended):
  ```cmd
  python -m venv venv
  venv\Scripts\activate
  pip install -r requirements.txt
  ```
- **Firewall**: Allow Ollama through Windows Firewall if prompted
- **Long Path Names**: Enable long paths in Windows if you encounter path length issues:
  ```cmd
  reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
  ```

---

### macOS Setup

#### Prerequisites

1. **Homebrew** (recommended)
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Python 3.8+**
   - macOS comes with Python, but you may need a newer version:
   ```bash
   brew install python@3.11
   ```
   - Verify: `python3 --version`

3. **Ollama**
   ```bash
   brew install ollama
   ```
   - Or download from [ollama.ai/download](https://ollama.ai/download)

4. **Node.js** (optional, for MCP and web UI)
   ```bash
   brew install node
   ```

#### Quick Setup

Run the automated setup script:
```bash
chmod +x setup_mac.sh
./setup_mac.sh
```

Or manually:
```bash
pip3 install -r requirements.txt
ollama serve
ollama pull llama3.1
python3 main.py
```

#### macOS-Specific Tips

- **Apple Silicon (M1/M2/M3)**: All dependencies are compatible with ARM architecture
- **Virtual Environment** (recommended):
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```
- **Permissions**: If you see "permission denied" errors:
  ```bash
  chmod +x start_jrvs.sh start-api.sh setup_mac.sh
  ```
- **Gatekeeper**: If macOS blocks Ollama, go to System Preferences > Security & Privacy and allow it
- **Memory**: For larger models (70B+), ensure you have sufficient RAM (32GB+ recommended)

---

## Dependency Reference

### Python Dependencies

| Package | Purpose |
|---------|---------|
| `rich` | Beautiful terminal UI |
| `requests` | HTTP client |
| `beautifulsoup4` | Web scraping |
| `faiss-cpu` | Vector search |
| `sentence-transformers` | Text embeddings |
| `torch` | PyTorch for ML |
| `fastapi` | API server |
| `uvicorn` | ASGI server |

### System Dependencies

| Tool | Required | Purpose |
|------|----------|---------|
| Python 3.8+ | Yes | Runtime |
| Ollama | Yes | Local AI models |
| Node.js | Optional | MCP servers, web UI |
| npm | Optional | Package management |

---

## Usage

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

## How It Works

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

## MCP Client (Connect to External Tools)

JRVS can now act as an **MCP Client**, connecting to MCP servers to access external tools like filesystems, databases, APIs, and more!

### Quick Setup

1. **Configure servers** in `mcp_gateway/client_config.json`:
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

 **Full guide**: See [MCP_CLIENT_GUIDE.md](MCP_CLIENT_GUIDE.md)

## UTCP Support (Universal Tool Calling Protocol)

JRVS now supports **UTCP** - a modern, lightweight protocol that allows AI agents to discover and call tools directly without wrapper servers.

### What is UTCP?

UTCP provides a standardized way for AI agents to call your tools directly using their native protocols (HTTP, WebSocket, CLI). Unlike MCP which requires wrapper servers, UTCP acts as a "manual" that describes how to call existing APIs.

### Quick Start

1. **Start the API server**:
```bash
python api/server.py
```

2. **Discover tools via UTCP**:
```bash
curl http://localhost:8000/utcp
```

3. **Call tools directly** using the information from the manual:
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello JRVS!"}'
```

### UTCP vs MCP

| Aspect | UTCP | MCP |
|--------|------|-----|
| **Architecture** | Direct API calls | Wrapper servers |
| **Performance** | Zero overhead | Proxy latency |
| **Infrastructure** | None required | Servers needed |
| **Best for** | REST APIs | Stdio tools, complex workflows |

 **Full guide**: See [docs/UTCP_GUIDE.md](docs/UTCP_GUIDE.md)

**Learn more**: [UTCP Specification](https://github.com/universal-tool-calling-protocol)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL of the Ollama API server |
| `OLLAMA_DEFAULT_MODEL` | `deepseek-r1:14b` | Default Ollama model to use |
| `LMSTUDIO_BASE_URL` | `http://127.0.0.1:1234/v1` | URL of the LM Studio API server |
| `LMSTUDIO_DEFAULT_MODEL` | `` | Default LM Studio model (auto-detected if empty) |

Example for connecting to a remote Ollama instance:
```bash
export OLLAMA_BASE_URL="http://192.168.1.100:11434"
export OLLAMA_DEFAULT_MODEL="llama3:8b"
python main.py
```

Example for using LM Studio:
```bash
python main.py --use-lmstudio
```

### Command Line Options

```bash
python main.py --help
```

Options:
- `--theme {matrix,cyberpunk,minimal}` - Set CLI theme
- `--model MODEL_NAME` - Set default model
- `--ollama-url URL` - Custom Ollama API URL
- `--lmstudio-url URL` - Custom LM Studio API URL
- `--use-lmstudio` - Use LM Studio instead of Ollama
- `--no-banner` - Skip ASCII banner
- `--debug` - Enable debug mode

### Themes

- **Matrix**: Green-on-black hacker aesthetic
- **Cyberpunk**: Magenta and cyan futuristic style
- **Minimal**: Clean black and white interface

## Project Structure

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
│   ├── ollama_client.py   # Ollama API integration
│   └── lmstudio_client.py # LM Studio API integration
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

## Advanced Usage

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
python mcp_gateway/server.py

# Test components
python mcp_gateway/test_server.py
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

### Using LM Studio

LM Studio is an alternative to Ollama for running local LLMs:

```python
from llm.lmstudio_client import lmstudio_client

# Use LM Studio
context = await rag_retriever.retrieve_context(query)
response = await lmstudio_client.generate(query, context=context)
```

## Troubleshooting

### Common Issues

**"Cannot connect to Ollama"**
- Make sure Ollama is running: `ollama serve`
- Check if port 11434 is free
- Verify Ollama installation
- Alternatively, use LM Studio: `python main.py --use-lmstudio`

**"Cannot connect to LM Studio"**
- Make sure LM Studio is running and the local server is enabled
- Default URL is `http://127.0.0.1:1234/v1`
- Load a model in LM Studio before starting JRVS

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

---

### Windows-Specific Issues

**"python is not recognized"**
- Python is not in PATH
- Reinstall Python and check "Add Python to PATH"
- Or use the full path: `C:\Python311\python.exe`

**"pip is not recognized"**
- Try: `python -m pip install -r requirements.txt`

**Permission denied errors**
- Run Command Prompt as Administrator
- Or use a virtual environment

**torch installation fails**
- Install Visual C++ Build Tools from [Microsoft](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
- Try: `pip install torch --index-url https://download.pytorch.org/whl/cpu`

**FAISS installation issues**
- Try: `pip install faiss-cpu --no-cache-dir`
- Ensure you have a 64-bit Python installation

---

### macOS-Specific Issues

**"command not found: python"**
- Use `python3` instead of `python`
- Or create an alias: `alias python=python3`

**"zsh: permission denied"**
- Make script executable: `chmod +x script_name.sh`

**SSL certificate errors**
- Install certificates: 
  ```bash
  /Applications/Python\ 3.11/Install\ Certificates.command
  ```

**Apple Silicon (M1/M2/M3) issues**
- Ensure you're using ARM-native Python (not Rosetta)
- Check architecture: `python3 -c "import platform; print(platform.machine())"`
- Should output `arm64`

**Homebrew not found after install (Apple Silicon)**
- Add to your shell profile (~/.zshrc):
  ```bash
  eval "$(/opt/homebrew/bin/brew shellenv)"
  ```
- Then: `source ~/.zshrc`

**Memory errors with large models**
- Close other applications to free RAM
- Use smaller models: `ollama pull llama3.1:8b`
- Check available memory: `top` or Activity Monitor

---

### MCP Server Issues

**"npx: command not found"**
- Install Node.js from [nodejs.org](https://nodejs.org/)
- Verify: `node --version` and `npm --version`

**MCP servers not connecting**
- Check `mcp_gateway/client_config.json` configuration
- Ensure paths are correct for your OS
- Windows paths use backslashes or forward slashes: `"C:/Users/name/folder"`

---

### Virtual Environment Tips

Using a virtual environment is recommended to avoid dependency conflicts:

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

To deactivate: `deactivate`

## Contributing

This is a functional RAG system built for learning and experimentation. Feel free to:
- Add new features
- Improve performance
- Fix bugs
- Add new themes
- Enhance the CLI

## License

This project is for educational and personal use. Respect website terms of service when scraping.

## Acknowledgments

- **Ollama** for local LLM serving
- **FAISS** for efficient vector search
- **Sentence Transformers** for embeddings
- **Rich** for beautiful terminal UI
- **BeautifulSoup** for web scraping

