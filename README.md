# Jarvis AI Agent 🤖

A sophisticated AI assistant that combines Ollama LLMs with RAG (Retrieval-Augmented Generation) capabilities, featuring web scraping, vector search, and intelligent context injection.

## ✨ Features

- **🧠 RAG Pipeline**: FAISS vector search with BERT embeddings for intelligent context retrieval
- **🔄 Dynamic Model Switching**: Hot-swap between different Ollama models
- **🌐 Web Scraping**: Automatically scrape and index web content with BeautifulSoup
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

## 🛠️ Configuration

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