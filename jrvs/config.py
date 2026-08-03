"""
JRVS Core — Configuration.

Lean version: no torch/GPU imports at module level.
Device detection is lazy (only when embeddings are actually used).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from this directory or home
_HERE = Path(__file__).resolve().parent.parent
for _env in (_HERE / ".env", Path.home() / "JRVS" / ".env", Path.home() / ".env"):
    if _env.exists():
        load_dotenv(_env)
        break


class Config:
    """Central configuration for the JRVS core application."""

    # ── Paths ────────────────────────────────────────────────────────────
    DATA_DIR: Path        = Path.home() / "JRVS"
    DB_PATH: Path         = DATA_DIR / "youtube.db"
    FAISS_INDEX_DIR: Path = DATA_DIR / "faiss_indexes"
    THUMBNAIL_CACHE: Path = DATA_DIR / "thumbnails"
    MODEL_CACHE: Path     = DATA_DIR / "models"
    LOG_DIR: Path         = DATA_DIR / "logs"

    # ── Brave Search ─────────────────────────────────────────────────────
    BRAVE_API_KEY: str       = os.getenv("BRAVE_API_KEY", "")
    BRAVE_SEARCH_URL: str    = "https://api.search.brave.com/res/v1/web/search"
    BRAVE_RESULT_COUNT: int  = int(os.getenv("BRAVE_RESULT_COUNT", "5"))
    WEB_SEARCH_TOP_K: int    = int(os.getenv("WEB_SEARCH_TOP_K", "6"))

    # ── YouTube Search (web-search augmentation) ─────────────────────────
    YOUTUBE_API_KEY: str              = os.getenv("YOUTUBE_API_KEY", "")
    YOUTUBE_SEARCH_RESULT_COUNT: int  = int(os.getenv("YOUTUBE_SEARCH_RESULT_COUNT", "5"))
    YT_SEARCH_TOP_K: int              = int(os.getenv("YT_SEARCH_TOP_K", "6"))

    # ── Google Workspace ─────────────────────────────────────────────────
    GOOGLE_CREDENTIALS_FILE: Path = Path(
        os.getenv("GOOGLE_CREDENTIALS_FILE",
                  str(Path.home() / "JRVS" / "google_credentials.json"))
    )
    GOOGLE_TOKEN_FILE: Path = Path(
        os.getenv("GOOGLE_TOKEN_FILE",
                  str(Path.home() / "JRVS" / "google_token.json"))
    )
    GOOGLE_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar",
    ]
    GOOGLE_LIST_LIMIT: int = int(os.getenv("GOOGLE_LIST_LIMIT", "10"))

    # ── Nextcloud (CalDAV) ───────────────────────────────────────────────
    NEXTCLOUD_URL: str          = os.getenv("NEXTCLOUD_URL", "")
    NEXTCLOUD_USERNAME: str     = os.getenv("NEXTCLOUD_USER", os.getenv("NEXTCLOUD_USERNAME", ""))
    NEXTCLOUD_APP_PASSWORD: str = os.getenv("NEXTCLOUD_APP_PASSWORD", "")
    NEXTCLOUD_CALENDAR: str     = os.getenv("NEXTCLOUD_CALENDAR", "")
    NEXTCLOUD_LIST_LIMIT: int   = int(os.getenv("NEXTCLOUD_LIST_LIMIT", "20"))

    # ── Autonomous Agent ─────────────────────────────────────────────────
    AGENT_GOALS_FILE: Path = Path(
        os.getenv("AGENT_GOALS_FILE", str(Path.home() / "JRVS" / "goals.yaml"))
    )
    AGENT_LOG_FILE: Path = Path(
        os.getenv("AGENT_LOG_FILE", str(Path.home() / "JRVS" / "agent.log"))
    )
    AGENT_DEFAULT_TIER: str  = os.getenv("AGENT_DEFAULT_TIER", "notify")
    AGENT_NOTIFY_EMAIL: str  = os.getenv("AGENT_NOTIFY_EMAIL", "")
    AGENT_MAX_STEPS: int     = int(os.getenv("AGENT_MAX_STEPS", "10"))
    AGENT_HISTORY_LIMIT: int = int(os.getenv("AGENT_HISTORY_LIMIT", "50"))

    # ── Embedding model (sentence-transformers, lazy-loaded) ─────────────
    EMBEDDING_MODEL: str       = os.getenv("JRVS_EMBEDDING_MODEL",
                                           "sentence-transformers/all-MiniLM-L6-v2")
    EMBEDDING_DIM: int         = 384
    EMBEDDING_BATCH_SIZE: int  = 64

    # ── LLM (Ollama) ─────────────────────────────────────────────────────
    OLLAMA_HOST: str          = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_BASE_URL: str      = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    OLLAMA_MODEL: str         = os.getenv("OLLAMA_MODEL", "gemma3:12b")
    OLLAMA_TEMPERATURE: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))
    OLLAMA_NUM_CTX: int       = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    OLLAMA_RETRY_COUNT: int   = int(os.getenv("OLLAMA_RETRY_COUNT", "3"))
    OLLAMA_RETRY_DELAY: float = float(os.getenv("OLLAMA_RETRY_DELAY", "1.0"))
    OLLAMA_HEALTH_TIMEOUT: int = int(os.getenv("OLLAMA_HEALTH_TIMEOUT", "5"))
    OLLAMA_CHAT_TIMEOUT: int  = int(os.getenv("OLLAMA_CHAT_TIMEOUT", "120"))

    # ── Device (detected once at import, no hard torch dep) ─────────────
    try:
        import torch as _torch
        DEVICE: str = "cuda" if _torch.cuda.is_available() else "cpu"
        del _torch
    except ImportError:
        DEVICE: str = "cpu"

    HALF_PRECISION: bool = True

    @classmethod
    def ensure_dirs(cls) -> None:
        for d in (cls.DATA_DIR, cls.FAISS_INDEX_DIR, cls.THUMBNAIL_CACHE,
                  cls.MODEL_CACHE, cls.LOG_DIR):
            d.mkdir(parents=True, exist_ok=True)
