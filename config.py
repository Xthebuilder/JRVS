"""Configuration settings for Jarvis AI Agent"""
import os
from pathlib import Path

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
DEFAULT_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "deepseek-r1:14b")

# LM Studio settings (OpenAI-compatible API)
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_DEFAULT_MODEL = os.environ.get("LMSTUDIO_DEFAULT_MODEL", "")

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
MAX_CONTEXT_LENGTH = 4000
MAX_RETRIEVED_CHUNKS = 5
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

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
