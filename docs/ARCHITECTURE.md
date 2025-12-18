# JRVS Architecture Documentation

## Overview

JRVS (Jarvis) is a local-first AI agent framework with modular architecture designed for extensibility, predictable behavior, and explicit control over AI operations.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Interfaces                         │
├─────────────┬─────────────┬─────────────┬──────────────────┤
│  CLI        │  Web UI     │  API        │  MCP Client      │
│  (cli/)     │  (app/)     │  (api/)     │  (mcp_gateway/)  │
└─────────────┴─────────────┴─────────────┴──────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer                              │
├──────────────────────┬──────────────────────────────────────┤
│  Database            │  Calendar                             │
│  (core/database.py)  │  (core/calendar.py)                  │
│  - SQLite storage    │  - Event management                   │
│  - Conversations     │  - Date operations                    │
│  - Documents         │                                       │
└──────────────────────┴──────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   RAG System (rag/)                          │
├──────────────────┬────────────────┬─────────────────────────┤
│  Embeddings      │  Vector Store  │  Retriever              │
│  - BERT models   │  - FAISS index │  - Context building     │
│  - Caching       │  - Similarity  │  - Document search      │
│                  │    search      │                         │
└──────────────────┴────────────────┴─────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   LLM Clients (llm/)                         │
├──────────────────────────┬──────────────────────────────────┤
│  Ollama Client           │  LM Studio Client                 │
│  - Local models          │  - Alternative runtime            │
│  - Model switching       │  - Compatible API                 │
└──────────────────────────┴──────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   External Tools                             │
├──────────────────────────┬──────────────────────────────────┤
│  Web Scraper             │  MCP Servers                      │
│  - Content extraction    │  - Filesystem                     │
│  - Document ingestion    │  - GitHub, Slack, etc.           │
└──────────────────────────┴──────────────────────────────────┘
```

## Component Details

### 1. Core Layer (`core/`)

#### Database (`database.py`)
- **Purpose:** Persistent storage for conversations, documents, and metadata
- **Technology:** SQLite with aiosqlite for async operations
- **Features:**
  - Conversation history storage
  - Document and chunk storage
  - Model usage statistics
  - User preferences
- **Memory Management:**
  - Connection pooling
  - Automatic cleanup with async context managers

#### Calendar (`calendar.py`)
- **Purpose:** Event and schedule management
- **Features:**
  - Event CRUD operations
  - Date range queries
  - Today/upcoming event views

### 2. RAG System (`rag/`)

#### Embeddings Manager (`embeddings.py`)
- **Purpose:** Generate semantic embeddings for text
- **Model:** Sentence Transformers (all-MiniLM-L6-v2)
- **Features:**
  - Batch processing
  - LRU caching (1000 entries)
  - GPU/CPU support with CUDA
- **Performance:**
  - Single embedding: < 100ms
  - Batch (10): < 500ms
- **Memory Management:**
  - Cache size limits
  - CUDA cache clearing
  - Context manager support

```python
async with EmbeddingManager() as manager:
    embeddings = await manager.encode_text(texts)
# Automatic cleanup
```

#### Vector Store (`vector_store.py`)
- **Purpose:** Fast similarity search using FAISS
- **Technology:** FAISS IndexFlatIP (cosine similarity)
- **Features:**
  - Document chunking
  - Similarity search
  - Persistence to disk
- **Performance:**
  - Search (k=5): < 50ms
- **Memory Management:**
  - Index persistence
  - Document map cleanup
  - Context manager support

#### Retriever (`retriever.py`)
- **Purpose:** Coordinate RAG pipeline
- **Features:**
  - Document ingestion
  - Context retrieval
  - Query enhancement
- **Process:**
  1. Chunk document text
  2. Generate embeddings
  3. Store in vector index
  4. Retrieve relevant chunks for queries

### 3. LLM Clients (`llm/`)

#### Ollama Client (`ollama_client.py`)
- **Purpose:** Interface with Ollama for local LLM inference
- **Features:**
  - Model listing and switching
  - Streaming responses
  - Context injection
- **Configuration:**
  - Base URL: `http://localhost:11434`
  - Configurable model
  - Timeout handling

#### LM Studio Client (`lmstudio_client.py`)
- **Purpose:** Alternative LLM runtime
- **Features:**
  - OpenAI-compatible API
  - Model discovery
  - Automatic fallback

### 4. Web Scraper (`scraper/`)

- **Purpose:** Extract content from web pages
- **Technology:** BeautifulSoup4, aiohttp
- **Features:**
  - HTML parsing
  - Content extraction
  - Metadata extraction
- **Safety:**
  - Timeout handling
  - Error recovery
  - Rate limiting (recommended)

### 5. MCP Gateway (`mcp_gateway/`)

#### MCP Client (`client.py`)
- **Purpose:** Connect to MCP servers for external tools
- **Features:**
  - Server connection management
  - Tool discovery
  - Tool invocation
- **Memory Management:**
  - Proper async context cleanup
  - CancelledError handling
  - Connection pooling

#### MCP Server (`server.py`)
- **Purpose:** Expose JRVS tools via MCP protocol
- **Features:**
  - 17+ tools (RAG, calendar, models, etc.)
  - Claude integration
  - Resource management

### 6. API Server (`api/server.py`)

- **Purpose:** REST API for JRVS
- **Framework:** FastAPI
- **Endpoints:**
  - `/api/chat` - Chat with AI
  - `/api/search` - Search documents
  - `/api/models` - List models
  - `/api/stats` - System statistics
  - `/api/rag/*` - RAG operations
- **Features:**
  - CORS support
  - Input validation
  - Error handling

### 7. CLI Interface (`cli/`)

#### Interface (`interface.py`)
- **Purpose:** Command-line interface
- **Framework:** Rich (terminal UI)
- **Features:**
  - Interactive chat
  - Command processing
  - History management
  - Theme support

#### Themes (`themes.py`)
- **Purpose:** Visual customization
- **Themes:**
  - Matrix (green on black)
  - Cyberpunk (magenta/cyan)
  - Minimal (black/white)

## Data Flow

### Chat Request Flow

```
User Input
    ↓
CLI/API
    ↓
RAG Retriever ─→ Vector Store ─→ Search similar chunks
    ↓              ↓
    └──────────────┘
         ↓
    Context Building
         ↓
LLM Client (Ollama/LM Studio)
         ↓
    Generate Response
         ↓
    Store in Database
         ↓
    Return to User
```

### Document Ingestion Flow

```
URL/Content
    ↓
Web Scraper (if URL)
    ↓
Text Chunking
    ↓
Embedding Generation
    ↓
Vector Store (FAISS)
    ↓
Database Storage
```

## Configuration

All configuration is centralized in `config.py`:

```python
# LLM Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "deepseek-r1:14b"

# RAG Configuration
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
MAX_RETRIEVED_CHUNKS = 5
MAX_CONTEXT_LENGTH = 4000

# Embedding Configuration
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_BATCH_SIZE = 32

# Database Configuration
DATABASE_PATH = "data/jarvis.db"
VECTOR_INDEX_PATH = "data/faiss_index"

# Timeout Configuration
TIMEOUTS = {
    "llm_generation": 60.0,
    "embedding_generation": 10.0,
    "vector_search": 2.0,
    "context_building": 5.0,
}
```

## Performance Characteristics

### Latency Targets

| Operation | Target | Typical |
|-----------|--------|---------|
| Vector search | < 50ms | ~20ms |
| Embedding (single) | < 100ms | ~50ms |
| Embedding (batch 10) | < 500ms | ~200ms |
| Database query | < 10ms | ~5ms |
| Context retrieval | < 1s | ~500ms |
| LLM generation | < 60s | ~5-20s |

### Throughput

- **API requests:** ~50-100 req/s (limited by LLM)
- **Document ingestion:** ~10 docs/s
- **Vector search:** ~1000 queries/s

### Resource Usage

- **Memory:**
  - Base: ~500MB
  - With embeddings: ~1-2GB
  - With large models: 4-16GB
- **CPU:**
  - Embedding generation: CPU-bound
  - Vector search: Fast, < 5% CPU
  - LLM inference: 80-100% (Ollama)

## Deployment Patterns

### Local Development

```bash
# Start Ollama
ollama serve

# Run JRVS
python main.py
```

### Production (API Server)

```bash
# With reverse proxy (nginx/Caddy)
uvicorn api.server:app --host 0.0.0.0 --port 8080
```

### Docker Deployment

```dockerfile
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

## Extension Points

### 1. Custom LLM Client

```python
from llm.base_client import BaseLLMClient

class CustomClient(BaseLLMClient):
    async def generate(self, prompt: str, **kwargs) -> str:
        # Implementation
        pass
```

### 2. Custom Embedding Model

```python
from rag.embeddings import EmbeddingManager

custom_manager = EmbeddingManager(model_name="custom-model")
```

### 3. Custom MCP Tools

```python
# In mcp_gateway/server.py
@server.call_tool()
async def custom_tool(arguments: dict) -> str:
    # Implementation
    return result
```

## Testing Strategy

See [TESTING.md](TESTING.md) for details.

- **Unit tests:** Component isolation
- **Integration tests:** End-to-end flows
- **Load tests:** Performance validation
- **Security tests:** Vulnerability scanning

## Security Considerations

See [SECURITY.md](SECURITY.md) for details.

- Input validation
- SQL injection protection
- XSS prevention
- Rate limiting
- Secret management

## Future Enhancements

1. **Distributed Vector Store:** Scale beyond single machine
2. **Streaming RAG:** Real-time context updates
3. **Multi-modal Support:** Images, audio
4. **Fine-tuning Pipeline:** Custom model training
5. **Advanced Memory:** Long-term memory graphs

## Resources

- [RAG Paper](https://arxiv.org/abs/2005.11401)
- [FAISS Documentation](https://github.com/facebookresearch/faiss)
- [Sentence Transformers](https://www.sbert.net/)
- [MCP Protocol](https://modelcontextprotocol.io/)
