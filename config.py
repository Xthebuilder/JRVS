"""Configuration settings for Jarvis AI Agent"""
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=False)

# ── Device class profiles ─────────────────────────────────────────────────────
# Set JRVS_DEVICE_CLASS to adjust defaults for your hardware:
#   desktop  — Full-featured, default model assumes 8GB+ RAM
#   server   — Same as desktop but higher concurrency limits
#   sbc      — Single-board computer / ARM / <4GB RAM: tiny model, small context
#   mobile   — Constrained memory, small model, short context
DEVICE_CLASS = os.environ.get("JRVS_DEVICE_CLASS", "desktop").lower()

_DEVICE_PROFILES = {
    "desktop": {
        "default_model": "gemma3:12b",
        "max_context_length": 12000,
        "chunk_size": 512,
        "chunk_overlap": 100,
        "embedding_batch_size": 64,
        "max_retrieved_chunks": 5,
        "vector_cache_size": 2000,
        "max_memory_mb": 2048,
        "voice_max_context": 2000,
    },
    "server": {
        "default_model": "gemma3:12b",
        "max_context_length": 16000,
        "chunk_size": 512,
        "chunk_overlap": 100,
        "embedding_batch_size": 128,
        "max_retrieved_chunks": 8,
        "vector_cache_size": 5000,
        "max_memory_mb": 4096,
        "voice_max_context": 3000,
    },
    "sbc": {
        "default_model": "phi3:mini",
        "max_context_length": 4000,
        "chunk_size": 256,
        "chunk_overlap": 50,
        "embedding_batch_size": 16,
        "max_retrieved_chunks": 3,
        "vector_cache_size": 500,
        "max_memory_mb": 512,
        "voice_max_context": 800,
    },
    "mobile": {
        "default_model": "phi3:mini",
        "max_context_length": 4000,
        "chunk_size": 256,
        "chunk_overlap": 50,
        "embedding_batch_size": 16,
        "max_retrieved_chunks": 3,
        "vector_cache_size": 500,
        "max_memory_mb": 768,
        "voice_max_context": 1000,
    },
}

_profile = _DEVICE_PROFILES.get(DEVICE_CLASS, _DEVICE_PROFILES["desktop"])

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = DATA_DIR / "models"

# JARCORE workspace settings
JARCORE_WORKSPACE = Path(os.environ.get("JARCORE_WORKSPACE", Path.cwd()))

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Database settings (SQLite — used for RAG, documents, feedback, analytics)
DATABASE_PATH = DATA_DIR / "jarvis.db"
VECTOR_INDEX_PATH = DATA_DIR / "faiss_index"

# ── PostgreSQL session store ──────────────────────────────────────────────────
# Hot conversation window for LLM context.  SESSION_DATABASE_URL takes
# precedence; if empty, individual SESSION_PG_* vars are used.
SESSION_DATABASE_URL = os.environ.get("SESSION_DATABASE_URL", "")
SESSION_PG_HOST = os.environ.get("SESSION_PG_HOST", "localhost")
_session_pg_port_raw = os.environ.get("SESSION_PG_PORT", "5432")
try:
    SESSION_PG_PORT = int(_session_pg_port_raw)
except ValueError as _e:
    raise ValueError(
        f"Invalid JRVS config: SESSION_PG_PORT='{_session_pg_port_raw}' is not an integer."
    ) from _e
SESSION_PG_USER = os.environ.get("SESSION_PG_USER", "jrvs")
SESSION_PG_PASSWORD = os.environ.get("SESSION_PG_PASSWORD", "")
SESSION_PG_DATABASE = os.environ.get("SESSION_PG_DATABASE", "jrvs")

# Ollama settings
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", _profile["default_model"])
# How long Ollama keeps the LLM loaded in VRAM after a request.
# Set to "0" when using Dia TTS so Gemma unloads immediately, freeing GPU
# memory for Dia synthesis.  Default "5m" keeps it warm between turns.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "5m")
# Context window size passed as options.num_ctx each request.
# Larger = more conversation history + RAG chunks but more VRAM.
# Default matches the device-class max_context_length profile.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", str(_profile["max_context_length"])))

# LM Studio settings (OpenAI-compatible API)
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_DEFAULT_MODEL = os.environ.get("LMSTUDIO_DEFAULT_MODEL", "")

# ── JRVS API server ──────────────────────────────────────────────────────────
JRVS_SERVER_HOST = os.environ.get("JRVS_SERVER_HOST", "localhost")
_jrvs_port_raw = os.environ.get("JRVS_SERVER_PORT", "8000")
try:
    JRVS_SERVER_PORT = int(_jrvs_port_raw)
except ValueError as _e:
    raise ValueError(
        f"Invalid JRVS config: JRVS_SERVER_PORT='{_jrvs_port_raw}' is not a valid integer."
    ) from _e

# ── Web Search APIs (Multi-provider with rotation) ───────────────────────────
# Brave Search: https://search.brave.com/
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

# Exa.ai: https://exa.ai/
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
_exa_results_raw = os.environ.get("EXA_SEARCH_RESULTS_PER_QUERY", "5")
try:
    EXA_SEARCH_RESULTS_PER_QUERY = int(_exa_results_raw)
except ValueError as _e:
    raise ValueError(f"Invalid JRVS config: EXA_SEARCH_RESULTS_PER_QUERY must be integer: {_e}") from _e

# Tavily: https://app.tavily.com/home
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
_tavily_results_raw = os.environ.get("TAVILY_SEARCH_RESULTS_PER_QUERY", "5")
try:
    TAVILY_SEARCH_RESULTS_PER_QUERY = int(_tavily_results_raw)
except ValueError as _e:
    raise ValueError(f"Invalid JRVS config: TAVILY_SEARCH_RESULTS_PER_QUERY must be integer: {_e}") from _e

# Serper: https://serper.dev/dashboard
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
_serper_results_raw = os.environ.get("SERPER_SEARCH_RESULTS_PER_QUERY", "5")
try:
    SERPER_SEARCH_RESULTS_PER_QUERY = int(_serper_results_raw)
except ValueError as _e:
    raise ValueError(f"Invalid JRVS config: SERPER_SEARCH_RESULTS_PER_QUERY must be integer: {_e}") from _e

# SerpAPI: https://serpapi.com/dashboard
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
_serpapi_results_raw = os.environ.get("SERPAPI_SEARCH_RESULTS_PER_QUERY", "5")
try:
    SERPAPI_SEARCH_RESULTS_PER_QUERY = int(_serpapi_results_raw)
except ValueError as _e:
    raise ValueError(f"Invalid JRVS config: SERPAPI_SEARCH_RESULTS_PER_QUERY must be integer: {_e}") from _e

# Multi-API Search Router Settings
SEARCH_API_ROTATION_STRATEGY = os.environ.get("SEARCH_API_ROTATION_STRATEGY", "round-robin")
SEARCH_API_FAILOVER_ENABLED = os.environ.get("SEARCH_API_FAILOVER_ENABLED", "true").lower() == "true"
SEARCH_AUTO_SCRAPE = os.environ.get("SEARCH_AUTO_SCRAPE", "true").lower() == "true"

# The Guardian Open Platform
GUARDIAN_API_KEY = os.environ.get("GUARDIAN_API_KEY", "")
GUARDIAN_API_BASE_URL = os.environ.get("GUARDIAN_API_BASE_URL", "https://content.guardianapis.com")

# Server URL for public links (reports, etc.)
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8000")

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

# RAG settings — defaults come from device profile, overridable via env vars
MAX_CONTEXT_LENGTH = int(os.environ.get("MAX_CONTEXT_LENGTH", str(_profile["max_context_length"])))
# Reduced context for voice sessions — shorter = faster, more focused spoken answers
VOICE_MAX_CONTEXT_LENGTH = int(os.environ.get("VOICE_MAX_CONTEXT_LENGTH", str(_profile["voice_max_context"])))
MAX_RETRIEVED_CHUNKS = int(os.environ.get("MAX_RETRIEVED_CHUNKS", str(_profile["max_retrieved_chunks"])))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", str(_profile["chunk_size"])))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", str(_profile["chunk_overlap"])))
CONVERSATION_HISTORY_TURNS = 8   # how many recent turns to pass to the LLM as messages

# Embedding model — kept for backward-compat; Mem0 backend uses MEM0_EMBEDDING_MODEL.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

# ── Mem0 settings ─────────────────────────────────────────────────────────────
# Data directory for Mem0's on-disk Qdrant index and SQLite history DB.
MEM0_DATA_DIR = os.environ.get(
    "MEM0_DATA_DIR", str(Path.home() / ".jrvs" / "mem0")
)
# Ollama embedding model used by Mem0.  nomic-embed-text is 768-dim and
# available via: ollama pull nomic-embed-text
MEM0_EMBEDDING_MODEL = os.environ.get("MEM0_EMBEDDING_MODEL", "nomic-embed-text")
# Qdrant collection name inside MEM0_DATA_DIR/qdrant/.
MEM0_COLLECTION_NAME = os.environ.get("MEM0_COLLECTION_NAME", "jrvs_memories")

# ── RAG backend selection ────────────────────────────────────────────────────
# "mem0" — Mem0-backed (Ollama LLM + nomic-embed-text + on-disk Qdrant)
# "faiss" — FAISS + sentence-transformers + cross-encoder reranker
RAG_BACKEND = os.environ.get("RAG_BACKEND", "mem0").lower()

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
def _platform_safe_strftime(fmt: str, dt: datetime) -> str:
    """Cross-platform strftime: %-d works on Linux/macOS, %#d on Windows."""
    import sys
    if sys.platform == "win32":
        fmt = fmt.replace("%-", "%#")
    try:
        return dt.strftime(fmt)
    except ValueError:
        # Final fallback: strip the dash/hash and accept zero-padded output
        import re
        fmt_safe = re.sub(r"%-|%#", "%", fmt)
        return dt.strftime(fmt_safe)


# Static identity — built once, no date/time
IDENTITY_BASE = (
    "You are JARVIS, a sharp and capable personal AI assistant with persistent memory. "
    "Your name is JARVIS — always refer to yourself as JARVIS, never as JRVS or J.R.V.S. "
    "You have a knowledge base built from web research and past conversations — use it naturally when it's relevant. "
    "Talk like a real person, not a corporate assistant. Keep responses tight and conversational. "
    "Match the user's energy: casual when they're casual, focused when they need something done. "
    "Never start a response with 'Certainly!', 'Of course!', 'Great question!', or similar filler phrases. "
    "Skip the preamble — just answer. Never announce the date or time unless explicitly asked."
)


def _build_system_prompt() -> str:
    """Returns IDENTITY_BASE with a fresh date/time stamp. Called per message."""
    now = datetime.now()
    date_str = _platform_safe_strftime("%A, %B %-d, %Y", now)
    time_str = _platform_safe_strftime("%-I:%M %p", now)
    return f"{IDENTITY_BASE}\n[Context: {date_str}, {time_str}]"


# Frozen snapshot kept for backward-compat (tests, lmstudio fallback)
SYSTEM_PROMPT = _build_system_prompt()


def _build_voice_system_prompt() -> str:
    """Short, spoken-language system prompt for voice interactions — no markdown."""
    now = datetime.now()
    date_str = _platform_safe_strftime("%A, %B %-d, %Y", now)
    time_str = _platform_safe_strftime("%-I:%M %p", now)
    return (
        f"You are JARVIS, a voice assistant. Your name is JARVIS. "
        f"Today is {date_str} and the time is {time_str}. "
        f"Respond in 1 to 3 short spoken sentences. "
        f"No markdown, no bullet points, no lists, no special characters. "
        f"Be direct and conversational."
    )

# Performance settings — adjusted by device class profile
MAX_MEMORY_MB = int(os.environ.get("MAX_MEMORY_MB", str(_profile["max_memory_mb"])))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", str(_profile["embedding_batch_size"])))
VECTOR_CACHE_SIZE = int(os.environ.get("VECTOR_CACHE_SIZE", str(_profile["vector_cache_size"])))

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
    if not (1 <= JRVS_SERVER_PORT <= 65535):
        errors.append("JRVS_SERVER_PORT must be between 1 and 65535")
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

    # RAG backend
    if RAG_BACKEND not in ("mem0", "faiss"):
        errors.append(f"RAG_BACKEND must be 'mem0' or 'faiss' (got '{RAG_BACKEND}')")

    # PostgreSQL session store
    if SESSION_DATABASE_URL:
        parsed = urlparse(SESSION_DATABASE_URL)
        if parsed.scheme not in ("postgres", "postgresql"):
            errors.append(
                f"SESSION_DATABASE_URL scheme must be 'postgresql' (got '{parsed.scheme}')"
            )
    else:
        if not (1 <= SESSION_PG_PORT <= 65535):
            errors.append("SESSION_PG_PORT must be between 1 and 65535")

    if errors:
        raise ValueError("JRVS configuration errors:\n  - " + "\n  - ".join(errors))


_validate_config()

# ── Anthropic / Claude (used by LLMRouter for !strong goals) ─────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

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
