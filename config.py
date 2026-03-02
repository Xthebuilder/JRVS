"""Configuration settings for Jarvis AI Agent"""
import os
from pathlib import Path
from urllib.parse import urlparse

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = DATA_DIR / "models"

# JARCORE workspace settings
JARCORE_WORKSPACE = Path(os.environ.get("JARCORE_WORKSPACE", Path.cwd()))

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Database settings
DATABASE_PATH = DATA_DIR / "jarvis.db"
VECTOR_INDEX_PATH = DATA_DIR / "faiss_index"

# Ollama settings
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "gemma3:12b")

# LM Studio settings (OpenAI-compatible API)
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_DEFAULT_MODEL = os.environ.get("LMSTUDIO_DEFAULT_MODEL", "")

# Brave Search API settings
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
_brave_max_raw = os.environ.get("BRAVE_MAX_REQUESTS_PER_SESSION", "20")
_brave_results_raw = os.environ.get("BRAVE_SEARCH_RESULTS_PER_QUERY", "5")
try:
    BRAVE_MAX_REQUESTS_PER_SESSION = int(_brave_max_raw)
    BRAVE_SEARCH_RESULTS_PER_QUERY = int(_brave_results_raw)
except ValueError as _e:
    raise ValueError(
        f"Invalid JRVS config: {_e}. "
        "BRAVE_MAX_REQUESTS_PER_SESSION and BRAVE_SEARCH_RESULTS_PER_QUERY must be integers."
    ) from _e
BRAVE_AUTO_SCRAPE = os.environ.get("BRAVE_AUTO_SCRAPE", "true").lower() == "true"

# Google Workspace settings
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_TOKEN_PATH = DATA_DIR / os.environ.get("GOOGLE_TOKEN_FILE", "google_token.json")
_google_sync_raw = os.environ.get("GOOGLE_SYNC_INTERVAL_MINUTES", "15")
_google_gmail_raw = os.environ.get("GOOGLE_GMAIL_MAX_EMAILS", "50")
_google_drive_raw = os.environ.get("GOOGLE_DRIVE_MAX_FILES", "20")
try:
    GOOGLE_SYNC_INTERVAL_MINUTES = int(_google_sync_raw)
    GOOGLE_GMAIL_MAX_EMAILS = int(_google_gmail_raw)
    GOOGLE_DRIVE_MAX_FILES = int(_google_drive_raw)
except ValueError as _e:
    raise ValueError(
        f"Invalid JRVS config: {_e}. "
        "GOOGLE_SYNC_INTERVAL_MINUTES, GOOGLE_GMAIL_MAX_EMAILS, and "
        "GOOGLE_DRIVE_MAX_FILES must be integers."
    ) from _e

# Timeout settings (in seconds)
TIMEOUTS = {
    "embedding_generation": 60,
    "vector_search": 10,
    "context_building": 60,
    "ollama_response": 300,  # 5 minutes
    "llm_response": 300,  # Generic LLM response timeout (5 minutes)
    "web_scraping": 45
}

# RAG settings
MAX_CONTEXT_LENGTH = 12000        # was 4000 — modern models handle 8k-128k tokens
MAX_RETRIEVED_CHUNKS = 5
CHUNK_SIZE = 512                  # characters
CHUNK_OVERLAP = 100               # characters (was 50 "words" — unit mismatch fixed)
CONVERSATION_HISTORY_TURNS = 8   # how many recent turns to pass to the LLM as messages

# Embedding model — change this env var to swap the whole embedding stack
# BAAI/bge-base-en-v1.5 (768-dim) is state-of-the-art for retrieval tasks.
# Falls back gracefully: set EMBEDDING_MODEL=all-MiniLM-L6-v2 to use the old fast model.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

# Retrieval pipeline tuning
# SIMILARITY_THRESHOLD: minimum cosine similarity to include a FAISS result (0–1).
# 0.35 filters low-signal noise; raise toward 0.5 for higher precision.
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.35"))
# HNSW_UPGRADE_THRESHOLD: auto-migrate flat FAISS index to HNSW at this vector count.
HNSW_UPGRADE_THRESHOLD = int(os.environ.get("HNSW_UPGRADE_THRESHOLD", "200000"))
# MMR_LAMBDA: tradeoff for Maximal Marginal Relevance (0=pure diversity, 1=pure relevance).
MMR_LAMBDA = float(os.environ.get("MMR_LAMBDA", "0.7"))
# RERANK_CANDIDATES: how many candidates to collect before cross-encoder re-ranking.
RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES", "20"))

# JRVS system identity — injected as the LLM system prompt every turn
SYSTEM_PROMPT = (
    "You are JRVS, an intelligent personal AI assistant with persistent memory. "
    "You have access to a knowledge base built from web research and past conversations. "
    "When relevant context from memory or documents is provided, use it naturally and precisely. "
    "You grow smarter with every interaction. Be concise, direct, and accurate."
)

# Performance settings
MAX_MEMORY_MB = 2024
EMBEDDING_BATCH_SIZE = 64
VECTOR_CACHE_SIZE = 2000

# CLI Theme settings
THEMES = {
    "matrix": {
        "primary": "bright_green",
        "secondary": "green",
        "accent": "bright_cyan",
        "error": "bright_red",
        "warning": "bright_yellow",
        "prompt": "bright_green",
        "response": "white"
    },
    "cyberpunk": {
        "primary": "bright_magenta",
        "secondary": "magenta",
        "accent": "bright_cyan",
        "error": "bright_red",
        "warning": "bright_yellow",
        "prompt": "bright_magenta",
        "response": "bright_white"
    },
    "minimal": {
        "primary": "white",
        "secondary": "bright_black",
        "accent": "blue",
        "error": "red",
        "warning": "yellow",
        "prompt": "blue",
        "response": "white"
    }
}

DEFAULT_THEME = "matrix"


def _validate_config() -> None:
    """Validate config values at startup — raise ValueError with a clear message on bad input."""
    errors: list[str] = []

    # URL format checks
    for name, url in [("OLLAMA_BASE_URL", OLLAMA_BASE_URL),
                      ("LMSTUDIO_BASE_URL", LMSTUDIO_BASE_URL)]:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            errors.append(f"{name}='{url}' is not a valid URL (expected http://host:port)")

    # Range checks
    if BRAVE_MAX_REQUESTS_PER_SESSION < 1:
        errors.append("BRAVE_MAX_REQUESTS_PER_SESSION must be >= 1")
    if not (1 <= BRAVE_SEARCH_RESULTS_PER_QUERY <= 20):
        errors.append("BRAVE_SEARCH_RESULTS_PER_QUERY must be between 1 and 20")
    if MAX_CONTEXT_LENGTH < 1000:
        errors.append("MAX_CONTEXT_LENGTH must be >= 1000")
    if CHUNK_SIZE < 64:
        errors.append("CHUNK_SIZE must be >= 64")
    if CHUNK_OVERLAP >= CHUNK_SIZE:
        errors.append("CHUNK_OVERLAP must be less than CHUNK_SIZE")
    if CONVERSATION_HISTORY_TURNS < 1:
        errors.append("CONVERSATION_HISTORY_TURNS must be >= 1")
    if EMBEDDING_BATCH_SIZE < 1:
        errors.append("EMBEDDING_BATCH_SIZE must be >= 1")
    if not (0.0 <= SIMILARITY_THRESHOLD <= 1.0):
        errors.append("SIMILARITY_THRESHOLD must be between 0.0 and 1.0")
    if not (0.0 <= MMR_LAMBDA <= 1.0):
        errors.append("MMR_LAMBDA must be between 0.0 and 1.0")
    if HNSW_UPGRADE_THRESHOLD < 10000:
        errors.append("HNSW_UPGRADE_THRESHOLD must be >= 10000")
    if RERANK_CANDIDATES < 1:
        errors.append("RERANK_CANDIDATES must be >= 1")

    # Google Workspace
    if bool(GOOGLE_CLIENT_ID) != bool(GOOGLE_CLIENT_SECRET):
        errors.append(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must both be set or both be empty"
        )
    if GOOGLE_SYNC_INTERVAL_MINUTES < 1:
        errors.append("GOOGLE_SYNC_INTERVAL_MINUTES must be >= 1")
    if GOOGLE_GMAIL_MAX_EMAILS < 1:
        errors.append("GOOGLE_GMAIL_MAX_EMAILS must be >= 1")
    if GOOGLE_DRIVE_MAX_FILES < 1:
        errors.append("GOOGLE_DRIVE_MAX_FILES must be >= 1")

    if errors:
        raise ValueError("JRVS configuration errors:\n  - " + "\n  - ".join(errors))


_validate_config()

# ASCII Art
JARVIS_ASCII = """
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
        Advanced RAG-Powered AI Assistant
"""
