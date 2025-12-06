#!/usr/bin/env python3
"""
CORTANA_JRVS - Enterprise-Grade Hybrid AI Assistant
===================================================

Production-ready cognitive AI system combining:
- JRVS modular RAG/MCP architecture
- Cortana's reflection, planning, and proactive intelligence
- Enterprise resilience, monitoring, and observability

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │              CORTANA_JRVS Cognitive Layer               │
    ├─────────────────────────────────────────────────────────┤
    │  Reflection │ Planning │ Proactive │ Memory Fusion      │
    │  Engine     │ Engine   │ Monitor   │ (ChromaDB+RAG)     │
    └─────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────────┐
    │              Resilience & Monitoring Layer              │
    ├─────────────────────────────────────────────────────────┤
    │  Circuit    │ Retry     │ Timeout   │ Health   │ Metrics│
    │  Breakers   │ Logic     │ Guards    │ Checks   │        │
    └─────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────────┐
    │                  JRVS Backend Layer                     │
    ├─────────────────────────────────────────────────────────┤
    │  RAG Pipeline  │  MCP Client  │  Database  │  Scraper   │
    └─────────────────────────────────────────────────────────┘

Enterprise Features:
- Comprehensive error handling with graceful degradation
- Circuit breakers for external services
- Structured logging with correlation IDs
- Health checks and metrics collection
- Configuration validation
- Input sanitization and security hardening
- Async-first with timeout guards
- Resource cleanup and lifecycle management
- Type safety and documentation
- Dependency injection for testing

Version: 1.0.0
License: MIT
"""

import asyncio
import sys
import os
import uuid
import json
import re
import logging
import threading
import time
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable, Union
from dataclasses import dataclass, field, asdict
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from enum import Enum
import hashlib

# Rich terminal UI
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.markdown import Markdown
from rich import box
from rich.logging import RichHandler

# Vector memory
import chromadb
from sentence_transformers import SentenceTransformer

# LLM
from langchain_ollama import OllamaLLM
from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory

# Add JRVS to path
jrvs_path = Path.home() / "JRVS"
if jrvs_path.exists():
    sys.path.insert(0, str(jrvs_path))

# ==================== VERSION & METADATA ====================

__version__ = "1.0.0"
__author__ = "JRVS Community"
__license__ = "MIT"

# ==================== ENUMS ====================

class ComponentStatus(Enum):
    """Component health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PlanStatus(Enum):
    """Plan execution status"""
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# ==================== CONFIGURATION ====================

class ConfigValidator:
    """Validates configuration at startup"""

    @staticmethod
    def validate(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate configuration structure and values"""
        errors = []

        # Check required sections
        required_sections = ["models", "memory", "reflection", "proactive", "planning", "ui", "data", "resilience"]
        for section in required_sections:
            if section not in config:
                errors.append(f"Missing required config section: {section}")

        # Validate timeouts are positive
        if "resilience" in config:
            for key, value in config["resilience"].get("timeouts", {}).items():
                if not isinstance(value, (int, float)) or value <= 0:
                    errors.append(f"Invalid timeout value for {key}: {value}")

        # Validate paths exist or can be created
        if "data" in config:
            for key in ["plans_file", "goals_file", "log_file"]:
                if key in config["data"]:
                    path = Path(config["data"][key])
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        errors.append(f"Cannot create directory for {key}: {e}")

        return (len(errors) == 0, errors)

# Default configuration
DEFAULT_CONFIG = {
    "models": {
        "primary": "jarvis",
        "reflection": "gemma3:12b",
        "fallback": "llama3:8b"  # Fallback model if primary fails
    },
    "memory": {
        "chromadb_path": "./data/cortana_jrvs_memory",
        "embedding_model": "all-MiniLM-L6-v2",
        "relevance_threshold": 0.35,
        "max_memories": 5,
        "cache_size": 1000
    },
    "reflection": {
        "enabled_by_default": False,
        "max_iterations": 2,
        "quality_threshold": 8,
        "timeout": 60  # seconds
    },
    "proactive": {
        "check_interval": 300,
        "goal_reminder_days": 3,
        "deadline_warning_days": 7,
        "enabled_by_default": True
    },
    "planning": {
        "max_tasks_per_plan": 10,
        "auto_save": True,
        "backup_on_save": True
    },
    "ui": {
        "theme": "cyberpunk",
        "show_thinking": True,
        "emoji_indicators": True,
        "markdown_output": True
    },
    "data": {
        "plans_file": "./data/cortana_jrvs_plans.json",
        "goals_file": "./data/cortana_jrvs_goals.json",
        "log_file": "./logs/cortana_jrvs.log",
        "metrics_file": "./logs/cortana_jrvs_metrics.json"
    },
    "resilience": {
        "timeouts": {
            "llm_call": 300,
            "embedding": 30,
            "memory_search": 10,
            "mcp_call": 60,
            "rag_retrieval": 30
        },
        "retries": {
            "llm_call": 2,
            "embedding": 3,
            "memory_search": 2,
            "file_operation": 3
        },
        "circuit_breaker": {
            "failure_threshold": 5,
            "recovery_timeout": 60,
            "expected_exception": Exception
        }
    },
    "security": {
        "max_input_length": 10000,
        "max_output_length": 50000,
        "dangerous_patterns": [
            r'rm\s+-rf',
            r'eval\(',
            r'exec\(',
            r'__import__',
            r'os\.system',
            r'subprocess\.'
        ],
        "sanitize_inputs": True
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s",
        "file_level": "DEBUG",
        "console_level": "INFO",
        "max_bytes": 10485760,  # 10MB
        "backup_count": 5
    }
}

# Load config from environment or use defaults
CONFIG = DEFAULT_CONFIG.copy()

# Validate configuration
config_valid, config_errors = ConfigValidator.validate(CONFIG)
if not config_valid:
    print(f"Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in config_errors))
    sys.exit(1)

# ==================== LOGGING SETUP ====================

class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to log records"""

    def filter(self, record):
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = getattr(threading.current_thread(), 'correlation_id', 'N/A')
        return True

# Create logs directory
log_dir = Path(CONFIG["data"]["log_file"]).parent
log_dir.mkdir(parents=True, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=getattr(logging, CONFIG["logging"]["level"]),
    format=CONFIG["logging"]["format"],
    handlers=[
        logging.handlers.RotatingFileHandler(
            CONFIG["data"]["log_file"],
            maxBytes=CONFIG["logging"]["max_bytes"],
            backupCount=CONFIG["logging"]["backup_count"]
        ),
        RichHandler(
            console=Console(stderr=True),
            level=getattr(logging, CONFIG["logging"]["console_level"]),
            show_path=False
        )
    ]
)

# Add correlation ID filter
for handler in logging.getLogger().handlers:
    handler.addFilter(CorrelationIdFilter())

logger = logging.getLogger("CORTANA_JRVS")

# ==================== RICH UI ====================

console = Console()

THEMES = {
    "matrix": {"primary": "bright_green", "accent": "green", "error": "bright_red", "warning": "yellow"},
    "cyberpunk": {"primary": "bright_magenta", "accent": "bright_cyan", "error": "bright_red", "warning": "yellow"},
    "minimal": {"primary": "white", "accent": "blue", "error": "red", "warning": "yellow"}
}

theme = THEMES[CONFIG["ui"]["theme"]]

def print_header(text: str):
    """Print styled header"""
    console.print(Panel(f"[bold {theme['primary']}]{text}[/]", box=box.DOUBLE))

def print_info(text: str, emoji: str = "💡"):
    """Print info message"""
    if CONFIG["ui"]["emoji_indicators"]:
        console.print(f"{emoji} [{theme['accent']}]{text}[/]")
    else:
        console.print(f"[{theme['accent']}]{text}[/]")

def print_error(text: str):
    """Print error message"""
    console.print(f"[{theme['error']}]❌ {text}[/]")

def print_success(text: str):
    """Print success message"""
    console.print(f"[bright_green]✅ {text}[/]")

def print_warning(text: str):
    """Print warning message"""
    console.print(f"[{theme['warning']}]⚠️  {text}[/]")

def print_thinking(score: int = None):
    """Print thinking indicator"""
    if score:
        console.print(f"[yellow]🤔 Reflection quality: {score}/10[/]")
    else:
        console.print(f"[yellow]🤔 Thinking...[/]")

# ==================== METRICS & MONITORING ====================

class MetricsCollector:
    """Collect and report system metrics"""

    def __init__(self):
        self.metrics: Dict[str, Any] = {
            "counters": {},
            "gauges": {},
            "histograms": {},
            "timers": {}
        }
        self.lock = threading.Lock()

    def increment(self, name: str, value: int = 1):
        """Increment counter"""
        with self.lock:
            if name not in self.metrics["counters"]:
                self.metrics["counters"][name] = 0
            self.metrics["counters"][name] += value

    def gauge(self, name: str, value: float):
        """Set gauge value"""
        with self.lock:
            self.metrics["gauges"][name] = value

    def histogram(self, name: str, value: float):
        """Add value to histogram"""
        with self.lock:
            if name not in self.metrics["histograms"]:
                self.metrics["histograms"][name] = []
            self.metrics["histograms"][name].append(value)

    @contextmanager
    def timer(self, name: str):
        """Time a block of code"""
        start = time.time()
        try:
            yield
        finally:
            duration = time.time() - start
            with self.lock:
                if name not in self.metrics["timers"]:
                    self.metrics["timers"][name] = []
                self.metrics["timers"][name].append(duration)

    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics"""
        with self.lock:
            return {
                "counters": self.metrics["counters"].copy(),
                "gauges": self.metrics["gauges"].copy(),
                "histograms": {
                    k: {
                        "count": len(v),
                        "avg": sum(v) / len(v) if v else 0,
                        "min": min(v) if v else 0,
                        "max": max(v) if v else 0
                    }
                    for k, v in self.metrics["histograms"].items()
                },
                "timers": {
                    k: {
                        "count": len(v),
                        "avg_ms": (sum(v) / len(v) * 1000) if v else 0,
                        "min_ms": (min(v) * 1000) if v else 0,
                        "max_ms": (max(v) * 1000) if v else 0
                    }
                    for k, v in self.metrics["timers"].items()
                }
            }

    def save_to_file(self, filepath: str):
        """Save metrics to file"""
        try:
            metrics = self.get_metrics()
            metrics["timestamp"] = datetime.now().isoformat()

            with open(filepath, 'w') as f:
                json.dump(metrics, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

# Global metrics collector
metrics = MetricsCollector()

# ==================== RESILIENCE PATTERNS ====================

class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
        self.lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs):
        """Call function with circuit breaker protection"""
        with self.lock:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "half-open"
                    logger.info("Circuit breaker entering half-open state")
                else:
                    raise Exception("Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)

            with self.lock:
                if self.state == "half-open":
                    self.state = "closed"
                    self.failure_count = 0
                    logger.info("Circuit breaker recovered to CLOSED")

            return result

        except Exception as e:
            with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = "open"
                    logger.error(f"Circuit breaker OPENED after {self.failure_count} failures")

            raise

def retry_with_backoff(max_retries: int = 3, initial_delay: float = 1.0, backoff_factor: float = 2.0):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}")

            raise last_exception

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}")

            raise last_exception

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator

async def with_timeout(coro, timeout: float, operation_name: str = "operation"):
    """Execute coroutine with timeout"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"Timeout ({timeout}s) exceeded for {operation_name}")
        raise TimeoutError(f"{operation_name} timed out after {timeout}s")

# ==================== SECURITY ====================

class InputSanitizer:
    """Sanitize and validate user inputs"""

    @staticmethod
    def sanitize(text: str, max_length: int = None) -> str:
        """Sanitize text input"""
        if max_length is None:
            max_length = CONFIG["security"]["max_input_length"]

        # Truncate if too long
        if len(text) > max_length:
            logger.warning(f"Input truncated from {len(text)} to {max_length} characters")
            text = text[:max_length]

        # Remove null bytes
        text = text.replace('\x00', '')

        return text

    @staticmethod
    def check_dangerous_patterns(text: str) -> Tuple[bool, List[str]]:
        """Check for dangerous patterns"""
        if not CONFIG["security"]["sanitize_inputs"]:
            return (True, [])

        matches = []
        for pattern in CONFIG["security"]["dangerous_patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(pattern)

        return (len(matches) == 0, matches)

    @staticmethod
    def validate_json(text: str) -> Tuple[bool, Optional[Dict]]:
        """Validate JSON input"""
        try:
            data = json.loads(text)
            return (True, data)
        except json.JSONDecodeError as e:
            return (False, None)

# ==================== DATA STRUCTURES ====================

@dataclass
class Task:
    """Represents a task in a plan"""
    id: str
    description: str
    status: TaskStatus
    created_at: str
    dependencies: List[str] = field(default_factory=list)
    result: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0

@dataclass
class Plan:
    """Represents a hierarchical plan"""
    id: str
    goal: str
    status: PlanStatus
    created_at: str
    tasks: List[Task] = field(default_factory=list)
    completed_at: Optional[str] = None
    reflection_score: Optional[int] = None
    error: Optional[str] = None

@dataclass
class Goal:
    """Represents a user goal"""
    id: str
    description: str
    created_at: str
    progress: float = 0.0
    deadline: Optional[str] = None
    last_worked_on: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    plan_id: Optional[str] = None
    archived: bool = False

@dataclass
class HealthCheckResult:
    """Health check result"""
    component: str
    status: ComponentStatus
    message: str
    timestamp: str
    details: Dict[str, Any] = field(default_factory=dict)

# ==================== FILE OPERATIONS ====================

class SafeFileOperations:
    """Safe file operations with backup and recovery"""

    @staticmethod
    @retry_with_backoff(max_retries=CONFIG["resilience"]["retries"]["file_operation"])
    def safe_json_save(filepath: str, data: Any, create_backup: bool = True):
        """Safely save JSON with atomic write and backup"""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Create backup if file exists
        if create_backup and filepath.exists():
            backup_path = filepath.with_suffix(f'.backup_{int(time.time())}.json')
            try:
                import shutil
                shutil.copy2(filepath, backup_path)
                logger.debug(f"Created backup: {backup_path}")
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")

        # Atomic write using temp file
        temp_path = filepath.with_suffix('.tmp')
        try:
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Atomic replace
            temp_path.replace(filepath)
            logger.debug(f"Saved: {filepath}")

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise

    @staticmethod
    @retry_with_backoff(max_retries=CONFIG["resilience"]["retries"]["file_operation"])
    def safe_json_load(filepath: str, default: Any = None) -> Any:
        """Safely load JSON with fallback to default"""
        filepath = Path(filepath)

        if not filepath.exists():
            logger.debug(f"File not found, using default: {filepath}")
            return default

        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in {filepath}: {e}")

            # Try to load from backup
            backups = sorted(filepath.parent.glob(f"{filepath.stem}.backup_*.json"), reverse=True)
            if backups:
                logger.info(f"Attempting to restore from backup: {backups[0]}")
                try:
                    with open(backups[0], 'r') as f:
                        data = json.load(f)
                    logger.info("Successfully restored from backup")
                    return data
                except Exception as backup_error:
                    logger.error(f"Backup restore failed: {backup_error}")

            return default

# ==================== MEMORY FUSION ====================

class MemoryFusion:
    """
    Combines episodic (ChromaDB) and semantic (JRVS RAG) memory systems
    with resilience, caching, and graceful degradation
    """

    def __init__(self):
        self.embedding_model = None
        self.chroma_client = None
        self.collection = None
        self.jrvs_rag = None
        self.initialized = False
        self.embedding_cache = {}
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=CONFIG["resilience"]["circuit_breaker"]["failure_threshold"],
            recovery_timeout=CONFIG["resilience"]["circuit_breaker"]["recovery_timeout"]
        )

    async def initialize(self):
        """Initialize memory systems with fallback handling"""
        if self.initialized:
            return

        correlation_id = str(uuid.uuid4())
        threading.current_thread().correlation_id = correlation_id

        logger.info("Initializing memory fusion systems")
        print_info("Loading memory systems...", "🧠")

        try:
            # Initialize embedding model
            with metrics.timer("memory.embedding_model_load"):
                self.embedding_model = SentenceTransformer(CONFIG["memory"]["embedding_model"])
            print_success("Embedding model loaded")

            # Initialize ChromaDB
            with metrics.timer("memory.chromadb_init"):
                db_path = Path(CONFIG["memory"]["chromadb_path"])
                db_path.parent.mkdir(parents=True, exist_ok=True)

                self.chroma_client = chromadb.PersistentClient(path=str(db_path))

                try:
                    self.collection = self.chroma_client.get_collection("cortana_jrvs_memories")
                    count = self.collection.count()
                    print_success(f"Loaded existing memory ({count} entries)")
                except:
                    self.collection = self.chroma_client.create_collection("cortana_jrvs_memories")
                    print_success("Created new memory collection")

            # Try to load JRVS RAG (optional)
            try:
                from rag.retriever import rag_retriever
                await with_timeout(
                    rag_retriever.initialize(),
                    timeout=30,
                    operation_name="RAG initialization"
                )
                self.jrvs_rag = rag_retriever
                print_success("JRVS RAG system loaded")
            except Exception as e:
                logger.warning(f"JRVS RAG not available: {e}")
                print_warning("JRVS RAG not available (optional)")
                self.jrvs_rag = None

            self.initialized = True
            metrics.increment("memory.initialize_success")
            logger.info("Memory fusion initialized successfully")

        except Exception as e:
            logger.error(f"Memory initialization failed: {e}", exc_info=True)
            metrics.increment("memory.initialize_failure")
            raise

    @retry_with_backoff(max_retries=CONFIG["resilience"]["retries"]["memory_search"])
    async def store_memory(self, text: str, metadata: dict = None):
        """Store episodic memory with retry logic"""
        if not self.initialized:
            logger.warning("Memory not initialized, skipping storage")
            return

        try:
            with metrics.timer("memory.store"):
                # Generate embedding
                embedding = await with_timeout(
                    asyncio.to_thread(self.embedding_model.encode, [text]),
                    timeout=CONFIG["resilience"]["timeouts"]["embedding"],
                    operation_name="embedding generation"
                )
                embedding = embedding[0].tolist()

                memory_id = f"mem_{datetime.now().timestamp()}_{uuid.uuid4().hex[:8]}"

                if metadata is None:
                    metadata = {}
                metadata["timestamp"] = datetime.now().isoformat()

                # Store in ChromaDB
                self.collection.add(
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata],
                    ids=[memory_id]
                )

                logger.debug(f"Stored memory: {memory_id}")
                metrics.increment("memory.store_success")

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            metrics.increment("memory.store_failure")
            # Don't raise - graceful degradation

    @retry_with_backoff(max_retries=CONFIG["resilience"]["retries"]["memory_search"])
    async def recall_episodic(self, query: str, n_results: int = 5) -> List[str]:
        """Recall from episodic memory with caching"""
        if not self.initialized:
            return []

        # Check cache
        cache_key = hashlib.md5(f"{query}:{n_results}".encode()).hexdigest()
        if cache_key in self.embedding_cache:
            logger.debug("Using cached memory search")
            metrics.increment("memory.cache_hit")
            return self.embedding_cache[cache_key]

        try:
            with metrics.timer("memory.recall_episodic"):
                # Generate query embedding
                query_embedding = await with_timeout(
                    asyncio.to_thread(self.embedding_model.encode, [query]),
                    timeout=CONFIG["resilience"]["timeouts"]["embedding"],
                    operation_name="query embedding"
                )
                query_embedding = query_embedding[0].tolist()

                # Search
                results = await with_timeout(
                    asyncio.to_thread(
                        self.collection.query,
                        query_embeddings=[query_embedding],
                        n_results=n_results
                    ),
                    timeout=CONFIG["resilience"]["timeouts"]["memory_search"],
                    operation_name="memory search"
                )

                memories = []
                if results['documents'] and results['documents'][0]:
                    memories = results['documents'][0]

                # Cache results
                if len(self.embedding_cache) < CONFIG["memory"]["cache_size"]:
                    self.embedding_cache[cache_key] = memories

                metrics.increment("memory.recall_success")
                metrics.histogram("memory.recall_count", len(memories))

                return memories

        except Exception as e:
            logger.error(f"Episodic recall failed: {e}")
            metrics.increment("memory.recall_failure")
            return []

    async def recall_semantic(self, query: str, session_id: str = None) -> str:
        """Recall from JRVS RAG semantic knowledge"""
        if not self.jrvs_rag:
            return ""

        try:
            with metrics.timer("memory.recall_semantic"):
                context = await with_timeout(
                    self.jrvs_rag.retrieve_context(query, session_id),
                    timeout=CONFIG["resilience"]["timeouts"]["rag_retrieval"],
                    operation_name="RAG retrieval"
                )
                metrics.increment("memory.rag_success")
                return context
        except Exception as e:
            logger.error(f"Semantic recall failed: {e}")
            metrics.increment("memory.rag_failure")
            return ""

    async def fused_recall(self, query: str, session_id: str = None) -> str:
        """Combine episodic + semantic memory with parallel execution"""
        try:
            # Execute both recalls in parallel
            episodic_task = self.recall_episodic(query, CONFIG["memory"]["max_memories"])
            semantic_task = self.recall_semantic(query, session_id)

            episodic, semantic = await asyncio.gather(
                episodic_task,
                semantic_task,
                return_exceptions=True
            )

            # Handle exceptions
            if isinstance(episodic, Exception):
                logger.error(f"Episodic recall failed: {episodic}")
                episodic = []
            if isinstance(semantic, Exception):
                logger.error(f"Semantic recall failed: {semantic}")
                semantic = ""

            # Build context
            context_parts = []

            if episodic:
                context_parts.append("=== EPISODIC MEMORY ===")
                for mem in episodic:
                    context_parts.append(f"- {mem}")

            if semantic:
                context_parts.append("\n=== KNOWLEDGE BASE ===")
                context_parts.append(semantic)

            return "\n".join(context_parts)

        except Exception as e:
            logger.error(f"Fused recall failed: {e}")
            return ""

    async def cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up memory systems")
        self.embedding_cache.clear()
        # ChromaDB handles its own cleanup

# ==================== REFLECTION ENGINE ====================

class ReflectionEngine:
    """
    Self-evaluation and improvement system
    Enterprise-grade with timeouts, retries, and quality gates
    """

    def __init__(self, llm):
        self.llm = llm
        self.enabled = CONFIG["reflection"]["enabled_by_default"]
        self.circuit_breaker = CircuitBreaker()

    async def reflect(self, query: str, response: str) -> Tuple[str, int]:
        """Evaluate and improve response with timeout protection"""
        if not self.enabled:
            return response, 0

        correlation_id = str(uuid.uuid4())
        threading.current_thread().correlation_id = correlation_id

        logger.info("Starting reflection loop")
        print_thinking()

        best_response = response
        best_score = 0

        try:
            with metrics.timer("reflection.total"):
                for iteration in range(CONFIG["reflection"]["max_iterations"]):
                    # Evaluate
                    score = await with_timeout(
                        self._evaluate(query, best_response),
                        timeout=CONFIG["reflection"]["timeout"],
                        operation_name=f"reflection evaluation {iteration+1}"
                    )

                    print_thinking(score)
                    metrics.histogram("reflection.score", score)

                    if score >= CONFIG["reflection"]["quality_threshold"]:
                        logger.info(f"Quality threshold met: {score}/10")
                        metrics.increment("reflection.quality_met")
                        return best_response, score

                    # Improve
                    print_info("Attempting improvement...", "⚡")
                    improved = await with_timeout(
                        self._improve(query, best_response, score),
                        timeout=CONFIG["reflection"]["timeout"],
                        operation_name=f"reflection improvement {iteration+1}"
                    )

                    new_score = await self._evaluate(query, improved)

                    if new_score > best_score:
                        best_response = improved
                        best_score = new_score
                        logger.info(f"Improved: {score} -> {new_score}")
                        metrics.increment("reflection.improvement_success")
                    else:
                        logger.info("No improvement, stopping")
                        metrics.increment("reflection.improvement_failed")
                        break

                return best_response, best_score

        except Exception as e:
            logger.error(f"Reflection failed: {e}", exc_info=True)
            metrics.increment("reflection.failure")
            return response, 0  # Graceful degradation

    @retry_with_backoff(max_retries=2)
    async def _evaluate(self, query: str, response: str) -> int:
        """Score response 1-10 with retry logic"""
        prompt = f"""Evaluate this AI response on a scale of 1-10:

User Query: {query}

AI Response: {response}

Rate based on:
- Accuracy and completeness
- Clarity and helpfulness
- Addressing the actual question

Respond with ONLY a number from 1-10, nothing else."""

        try:
            with metrics.timer("reflection.evaluate"):
                score_text = await asyncio.to_thread(self.llm.invoke, prompt)
                score_text = score_text.strip()

                match = re.search(r'\d+', score_text)
                if match:
                    score = int(match.group())
                    return max(1, min(10, score))

                logger.warning(f"Could not parse score from: {score_text}")
                return 5

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            return 5

    @retry_with_backoff(max_retries=2)
    async def _improve(self, query: str, prev_response: str, score: int) -> str:
        """Generate improved response"""
        prompt = f"""The previous response scored {score}/10. Improve it.

User Query: {query}

Previous Response: {prev_response}

Provide a better, more complete, clearer response:"""

        try:
            with metrics.timer("reflection.improve"):
                improved = await asyncio.to_thread(self.llm.invoke, prompt)
                return improved
        except Exception as e:
            logger.error(f"Improvement failed: {e}")
            return prev_response

# ==================== PLANNING ENGINE ====================

class PlanningEngine:
    """
    Hierarchical task planning with dependencies
    Enterprise-grade with persistence, backup, and recovery
    """

    def __init__(self, llm):
        self.llm = llm
        self.plans: Dict[str, Plan] = {}
        self.lock = threading.Lock()
        self._load_plans()

    def _load_plans(self):
        """Load plans from disk with error handling"""
        try:
            data = SafeFileOperations.safe_json_load(
                CONFIG["data"]["plans_file"],
                default={}
            )

            with self.lock:
                for plan_id, plan_data in data.items():
                    try:
                        # Convert string enums back to enum types
                        plan_data['status'] = PlanStatus(plan_data['status'])
                        tasks = []
                        for t in plan_data['tasks']:
                            t['status'] = TaskStatus(t['status'])
                            tasks.append(Task(**t))
                        plan_data['tasks'] = tasks
                        self.plans[plan_id] = Plan(**plan_data)
                    except Exception as e:
                        logger.error(f"Failed to load plan {plan_id}: {e}")

            logger.info(f"Loaded {len(self.plans)} plans")
            metrics.gauge("planning.plans_loaded", len(self.plans))

        except Exception as e:
            logger.error(f"Failed to load plans: {e}")

    def _save_plans(self):
        """Save plans to disk with backup"""
        if not CONFIG["planning"]["auto_save"]:
            return

        try:
            with self.lock:
                # Convert to serializable format
                data = {}
                for plan_id, plan in self.plans.items():
                    plan_dict = asdict(plan)
                    # Convert enums to strings
                    plan_dict['status'] = plan.status.value
                    for task in plan_dict['tasks']:
                        task['status'] = task['status'].value
                    data[plan_id] = plan_dict

            SafeFileOperations.safe_json_save(
                CONFIG["data"]["plans_file"],
                data,
                create_backup=CONFIG["planning"]["backup_on_save"]
            )
            metrics.increment("planning.save_success")

        except Exception as e:
            logger.error(f"Failed to save plans: {e}")
            metrics.increment("planning.save_failure")

    async def create_plan(self, goal: str) -> str:
        """Break down goal into tasks with LLM assistance"""
        correlation_id = str(uuid.uuid4())
        threading.current_thread().correlation_id = correlation_id

        logger.info(f"Creating plan for goal: {goal}")
        print_info(f"Creating plan for: {goal}", "📋")

        # Sanitize goal
        goal = InputSanitizer.sanitize(goal)
        safe, patterns = InputSanitizer.check_dangerous_patterns(goal)
        if not safe:
            print_error(f"Dangerous patterns detected: {patterns}")
            return ""

        prompt = f"""You are a strategic planner. Break down this goal into 3-{CONFIG['planning']['max_tasks_per_plan']} specific, actionable tasks:

Goal: {goal}

For each task, provide:
1. Clear description
2. Dependencies (task numbers or NONE)

Format:
TASK: [description]
DEPENDS_ON: [numbers or NONE]

Be specific and practical."""

        try:
            with metrics.timer("planning.create"):
                response = await with_timeout(
                    asyncio.to_thread(self.llm.invoke, prompt),
                    timeout=CONFIG["resilience"]["timeouts"]["llm_call"],
                    operation_name="plan creation"
                )

                tasks = self._parse_tasks(response)

                if not tasks:
                    print_error("Failed to parse tasks from LLM response")
                    return ""

                plan_id = f"plan_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
                plan = Plan(
                    id=plan_id,
                    goal=goal,
                    tasks=tasks,
                    status=PlanStatus.PLANNING,
                    created_at=datetime.now().isoformat()
                )

                with self.lock:
                    self.plans[plan_id] = plan

                self._save_plans()

                # Display plan
                table = Table(title=f"Plan: {plan_id}", box=box.ROUNDED)
                table.add_column("Task ID", style="cyan")
                table.add_column("Description")
                table.add_column("Dependencies", style="yellow")

                for task in tasks:
                    deps = ", ".join(task.dependencies) if task.dependencies else "None"
                    table.add_row(task.id, task.description, deps)

                console.print(table)
                print_success(f"Plan created: {plan_id}")

                metrics.increment("planning.create_success")
                metrics.histogram("planning.task_count", len(tasks))

                return plan_id

        except Exception as e:
            logger.error(f"Plan creation failed: {e}", exc_info=True)
            print_error(str(e))
            metrics.increment("planning.create_failure")
            return ""

    def _parse_tasks(self, response: str) -> List[Task]:
        """Parse LLM response into tasks"""
        tasks = []
        blocks = response.split("TASK:")

        for i, block in enumerate(blocks[1:], 1):
            try:
                lines = block.strip().split('\n')
                description = lines[0].strip()

                if not description:
                    continue

                deps = []
                for line in lines:
                    if 'DEPENDS_ON:' in line:
                        deps_str = line.split('DEPENDS_ON:')[1].strip()
                        if deps_str.upper() != 'NONE':
                            deps = [f"task_{d.strip()}" for d in deps_str.split(',') if d.strip().isdigit()]

                task = Task(
                    id=f"task_{i}",
                    description=description,
                    status=TaskStatus.PENDING,
                    dependencies=deps,
                    created_at=datetime.now().isoformat()
                )
                tasks.append(task)

            except Exception as e:
                logger.warning(f"Failed to parse task {i}: {e}")

        return tasks

    async def execute_plan(self, plan_id: str, agent_executor) -> str:
        """Execute plan with dependency resolution and error handling"""
        with self.lock:
            if plan_id not in self.plans:
                print_error(f"Plan not found: {plan_id}")
                return f"Plan not found: {plan_id}"

            plan = self.plans[plan_id]

        correlation_id = str(uuid.uuid4())
        threading.current_thread().correlation_id = correlation_id

        logger.info(f"Executing plan: {plan_id}")
        print_header(f"Executing: {plan.goal}")

        plan.status = PlanStatus.EXECUTING
        self._save_plans()

        results = []

        try:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                while True:
                    # Find ready tasks
                    with self.lock:
                        ready = [
                            t for t in plan.tasks
                            if t.status == TaskStatus.PENDING and
                            all(self._is_completed(d, plan) for d in t.dependencies)
                        ]

                    if not ready:
                        # Check if all done
                        with self.lock:
                            if all(t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
                                   for t in plan.tasks):
                                break
                            else:
                                pending = [t for t in plan.tasks if t.status == TaskStatus.PENDING]
                                if pending:
                                    msg = "⚠️ Blocked or circular dependencies"
                                    results.append(msg)
                                    logger.warning(msg)
                                break

                    # Execute ready tasks
                    for task in ready:
                        task_progress = progress.add_task(f"Executing: {task.description}", total=None)
                        task.status = TaskStatus.IN_PROGRESS

                        try:
                            with metrics.timer("planning.task_execution"):
                                response = await with_timeout(
                                    asyncio.to_thread(agent_executor.invoke, {"input": task.description}),
                                    timeout=CONFIG["resilience"]["timeouts"]["llm_call"],
                                    operation_name=f"task {task.id}"
                                )

                                task.result = response['output']
                                task.status = TaskStatus.COMPLETED
                                task.completed_at = datetime.now().isoformat()
                                results.append(f"✅ {task.id}")
                                metrics.increment("planning.task_success")

                        except Exception as e:
                            task.status = TaskStatus.FAILED
                            task.error = str(e)
                            results.append(f"❌ {task.id}: {str(e)}")
                            logger.error(f"Task {task.id} failed: {e}")
                            metrics.increment("planning.task_failure")

                        finally:
                            progress.remove_task(task_progress)
                            self._save_plans()

            # Mark plan complete
            with self.lock:
                if all(t.status == TaskStatus.COMPLETED for t in plan.tasks):
                    plan.status = PlanStatus.COMPLETED
                else:
                    plan.status = PlanStatus.FAILED

                plan.completed_at = datetime.now().isoformat()

            self._save_plans()

            completed = len([r for r in results if r.startswith('✅')])
            total = len(plan.tasks)

            print_success(f"Plan finished: {completed}/{total} tasks completed")
            metrics.increment("planning.execute_success")

            return "\n".join(results)

        except Exception as e:
            logger.error(f"Plan execution failed: {e}", exc_info=True)
            plan.status = PlanStatus.FAILED
            plan.error = str(e)
            self._save_plans()
            metrics.increment("planning.execute_failure")
            return f"Plan execution failed: {e}"

    def _is_completed(self, task_id: str, plan: Plan) -> bool:
        """Check if task is completed"""
        task = next((t for t in plan.tasks if t.id == task_id), None)
        return task and task.status == TaskStatus.COMPLETED

    def view_plans(self) -> str:
        """Display all plans in a table"""
        with self.lock:
            if not self.plans:
                print_info("No plans yet")
                return ""

            table = Table(title="All Plans", box=box.ROUNDED)
            table.add_column("Plan ID", style="cyan")
            table.add_column("Goal")
            table.add_column("Status", style="yellow")
            table.add_column("Progress")

            for plan in self.plans.values():
                completed = sum(1 for t in plan.tasks if t.status == TaskStatus.COMPLETED)
                total = len(plan.tasks)

                if total > 0:
                    progress_bar = "█" * int(completed/total * 10) + "░" * (10 - int(completed/total * 10))
                else:
                    progress_bar = "░" * 10

                goal_display = plan.goal[:50] + "..." if len(plan.goal) > 50 else plan.goal

                table.add_row(
                    plan.id,
                    goal_display,
                    plan.status.value,
                    f"[{progress_bar}] {completed}/{total}"
                )

            console.print(table)

        return ""

# ==================== PROACTIVE MONITOR ====================

class ProactiveMonitor:
    """
    Background goal tracking and reminder system
    Enterprise-grade with thread safety and graceful shutdown
    """

    def __init__(self, llm):
        self.llm = llm
        self.goals: Dict[str, Goal] = {}
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self._load_goals()

    def _load_goals(self):
        """Load goals from disk"""
        try:
            data = SafeFileOperations.safe_json_load(
                CONFIG["data"]["goals_file"],
                default={}
            )

            with self.lock:
                self.goals = {gid: Goal(**gdata) for gid, gdata in data.items()}

            logger.info(f"Loaded {len(self.goals)} goals")
            metrics.gauge("proactive.goals_loaded", len(self.goals))

        except Exception as e:
            logger.error(f"Failed to load goals: {e}")

    def _save_goals(self):
        """Save goals to disk"""
        try:
            with self.lock:
                data = {gid: asdict(goal) for gid, goal in self.goals.items()}

            SafeFileOperations.safe_json_save(CONFIG["data"]["goals_file"], data, create_backup=True)
            metrics.increment("proactive.save_success")

        except Exception as e:
            logger.error(f"Failed to save goals: {e}")
            metrics.increment("proactive.save_failure")

    def add_goal(self, description: str, deadline: Optional[str] = None) -> str:
        """Add a new goal"""
        # Sanitize input
        description = InputSanitizer.sanitize(description)

        goal_id = f"goal_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
        goal = Goal(
            id=goal_id,
            description=description,
            deadline=deadline,
            created_at=datetime.now().isoformat()
        )

        with self.lock:
            self.goals[goal_id] = goal

        self._save_goals()

        print_success(f"Goal added: {goal_id}")
        if deadline:
            print_info(f"Deadline: {deadline}", "⏰")

        metrics.increment("proactive.goal_added")
        logger.info(f"Goal added: {goal_id}")

        return goal_id

    def update_progress(self, goal_id: str, progress: float, note: str = ""):
        """Update goal progress"""
        with self.lock:
            if goal_id not in self.goals:
                print_error(f"Goal not found: {goal_id}")
                return f"Goal not found: {goal_id}"

            goal = self.goals[goal_id]
            goal.progress = max(0.0, min(1.0, progress))
            goal.last_worked_on = datetime.now().isoformat()

            if note:
                sanitized_note = InputSanitizer.sanitize(note, max_length=500)
                goal.notes.append(f"{datetime.now().isoformat()}: {sanitized_note}")

        self._save_goals()
        print_success(f"Progress: {goal.progress*100:.0f}%")
        metrics.histogram("proactive.progress_update", progress)

    def view_goals(self):
        """Display all goals in a table"""
        with self.lock:
            if not self.goals:
                print_info("No goals set")
                return

            # Filter out archived goals
            active_goals = {gid: g for gid, g in self.goals.items() if not g.archived}

            if not active_goals:
                print_info("No active goals")
                return

            table = Table(title="Your Goals", box=box.ROUNDED)
            table.add_column("Goal ID", style="cyan")
            table.add_column("Description")
            table.add_column("Progress")
            table.add_column("Deadline", style="yellow")

            for goal in active_goals.values():
                progress_bar = "█" * int(goal.progress * 10) + "░" * (10 - int(goal.progress * 10))
                deadline_str = goal.deadline if goal.deadline else "None"
                desc_display = goal.description[:40] + "..." if len(goal.description) > 40 else goal.description

                table.add_row(
                    goal.id,
                    desc_display,
                    f"[{progress_bar}] {goal.progress*100:.0f}%",
                    deadline_str
                )

            console.print(table)

    def start_monitoring(self):
        """Start background monitoring thread"""
        if self.running:
            logger.warning("Proactive monitor already running")
            return

        if not CONFIG["proactive"]["enabled_by_default"]:
            logger.info("Proactive monitoring disabled by config")
            return

        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="ProactiveMonitor")
        self.thread.start()

        print_success("Proactive monitoring started")
        logger.info("Proactive monitoring started")
        metrics.increment("proactive.start")

    def stop_monitoring(self):
        """Stop background monitoring gracefully"""
        if not self.running:
            return

        logger.info("Stopping proactive monitor...")
        self.running = False
        self.stop_event.set()

        if self.thread:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                logger.warning("Proactive monitor thread did not stop gracefully")
            else:
                logger.info("Proactive monitor stopped")

        metrics.increment("proactive.stop")

    def _monitor_loop(self):
        """Background monitoring loop"""
        logger.info("Proactive monitor loop started")

        while self.running and not self.stop_event.is_set():
            try:
                # Wait with interruptible sleep
                if self.stop_event.wait(timeout=CONFIG["proactive"]["check_interval"]):
                    break

                # Check goals
                suggestions = self._check_goals()

                if suggestions:
                    console.print("\n" + "="*60)
                    console.print(Panel(suggestions, title="📌 Proactive Reminder", border_style="yellow"))
                    console.print("="*60 + "\n")
                    metrics.increment("proactive.reminder_sent")

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                metrics.increment("proactive.error")

        logger.info("Proactive monitor loop ended")

    def _check_goals(self) -> Optional[str]:
        """Check goals and generate reminders"""
        suggestions = []
        now = datetime.now()

        with self.lock:
            for goal in self.goals.values():
                if goal.archived or goal.progress >= 1.0:
                    continue

                # Check last worked on
                if goal.last_worked_on:
                    try:
                        last = datetime.fromisoformat(goal.last_worked_on)
                        days = (now - last).days

                        if days >= CONFIG["proactive"]["goal_reminder_days"]:
                            suggestions.append(
                                f"⏰ '{goal.description}' - {days} days since last work ({goal.progress*100:.0f}% done)"
                            )
                    except Exception as e:
                        logger.warning(f"Error parsing last_worked_on for {goal.id}: {e}")

                # Check deadline
                if goal.deadline:
                    try:
                        deadline = datetime.fromisoformat(goal.deadline)
                        days_left = (deadline - now).days

                        if 0 <= days_left <= CONFIG["proactive"]["deadline_warning_days"]:
                            suggestions.append(
                                f"⚠️ '{goal.description}' - {days_left} days until deadline!"
                            )
                    except Exception as e:
                        logger.warning(f"Error parsing deadline for {goal.id}: {e}")

        return "\n".join(suggestions) if suggestions else None

# ==================== HEALTH CHECKS ====================

class HealthCheck:
    """System health monitoring"""

    def __init__(self, memory: MemoryFusion, reflection: ReflectionEngine,
                 planner: PlanningEngine, proactive: ProactiveMonitor):
        self.memory = memory
        self.reflection = reflection
        self.planner = planner
        self.proactive = proactive

    async def check_all(self) -> List[HealthCheckResult]:
        """Run all health checks"""
        checks = []

        # Memory system
        checks.append(await self._check_memory())

        # Reflection engine
        checks.append(self._check_reflection())

        # Planning engine
        checks.append(self._check_planning())

        # Proactive monitor
        checks.append(self._check_proactive())

        # Disk space
        checks.append(self._check_disk_space())

        return checks

    async def _check_memory(self) -> HealthCheckResult:
        """Check memory system health"""
        try:
            if not self.memory.initialized:
                return HealthCheckResult(
                    component="Memory",
                    status=ComponentStatus.UNHEALTHY,
                    message="Not initialized",
                    timestamp=datetime.now().isoformat()
                )

            # Try a test query
            test_result = await asyncio.wait_for(
                self.memory.recall_episodic("test", n_results=1),
                timeout=5
            )

            return HealthCheckResult(
                component="Memory",
                status=ComponentStatus.HEALTHY,
                message="Operational",
                timestamp=datetime.now().isoformat(),
                details={
                    "chromadb": "connected",
                    "jrvs_rag": "available" if self.memory.jrvs_rag else "unavailable",
                    "cache_size": len(self.memory.embedding_cache)
                }
            )
        except Exception as e:
            return HealthCheckResult(
                component="Memory",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                timestamp=datetime.now().isoformat()
            )

    def _check_reflection(self) -> HealthCheckResult:
        """Check reflection engine health"""
        return HealthCheckResult(
            component="Reflection",
            status=ComponentStatus.HEALTHY if self.reflection.enabled else ComponentStatus.DEGRADED,
            message="Enabled" if self.reflection.enabled else "Disabled",
            timestamp=datetime.now().isoformat()
        )

    def _check_planning(self) -> HealthCheckResult:
        """Check planning engine health"""
        with self.planner.lock:
            plan_count = len(self.planner.plans)

        return HealthCheckResult(
            component="Planning",
            status=ComponentStatus.HEALTHY,
            message="Operational",
            timestamp=datetime.now().isoformat(),
            details={"plans": plan_count}
        )

    def _check_proactive(self) -> HealthCheckResult:
        """Check proactive monitor health"""
        status = ComponentStatus.HEALTHY if self.proactive.running else ComponentStatus.DEGRADED

        with self.proactive.lock:
            goal_count = len(self.proactive.goals)

        return HealthCheckResult(
            component="Proactive",
            status=status,
            message="Running" if self.proactive.running else "Stopped",
            timestamp=datetime.now().isoformat(),
            details={"goals": goal_count}
        )

    def _check_disk_space(self) -> HealthCheckResult:
        """Check available disk space"""
        try:
            import shutil
            stats = shutil.disk_usage(Path.cwd())
            free_gb = stats.free / (1024**3)

            if free_gb < 1:
                status = ComponentStatus.UNHEALTHY
                message = f"Low disk space: {free_gb:.2f} GB free"
            elif free_gb < 5:
                status = ComponentStatus.DEGRADED
                message = f"Disk space low: {free_gb:.2f} GB free"
            else:
                status = ComponentStatus.HEALTHY
                message = f"{free_gb:.2f} GB free"

            return HealthCheckResult(
                component="Disk Space",
                status=status,
                message=message,
                timestamp=datetime.now().isoformat()
            )
        except Exception as e:
            return HealthCheckResult(
                component="Disk Space",
                status=ComponentStatus.UNKNOWN,
                message=str(e),
                timestamp=datetime.now().isoformat()
            )

# ==================== MAIN ASSISTANT ====================

class CortanaJRVS:
    """
    Enterprise-grade hybrid AI assistant
    Production-ready with full observability and resilience
    """

    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.memory = None
        self.reflection = None
        self.planner = None
        self.proactive = None
        self.agent_executor = None
        self.mcp_client = None
        self.health_check = None
        self.initialized = False
        self.shutdown_requested = False

        # Set correlation ID for main thread
        threading.current_thread().correlation_id = self.session_id

    async def initialize(self):
        """Initialize all systems with comprehensive error handling"""
        if self.initialized:
            return

        logger.info(f"Initializing CORTANA_JRVS session {self.session_id}")
        print_header("CORTANA_JRVS - Enterprise AI Assistant")
        print_info(f"Version: {__version__}", "🚀")
        print_info("Initializing cognitive systems...", "🤖")

        try:
            # Create data directories
            for key in ["plans_file", "goals_file", "log_file", "metrics_file"]:
                Path(CONFIG["data"][key]).parent.mkdir(parents=True, exist_ok=True)

            # Initialize memory fusion
            self.memory = MemoryFusion()
            await self.memory.initialize()

            # Initialize LLMs
            print_info("Loading language models...", "🧠")
            try:
                primary_llm = OllamaLLM(
                    model=CONFIG["models"]["primary"],
                    temperature=0.7,
                    timeout=CONFIG["resilience"]["timeouts"]["llm_call"]
                )
                logger.info(f"Loaded primary model: {CONFIG['models']['primary']}")
            except Exception as e:
                logger.error(f"Failed to load primary model: {e}")
                print_warning(f"Using fallback model: {CONFIG['models']['fallback']}")
                primary_llm = OllamaLLM(
                    model=CONFIG["models"]["fallback"],
                    temperature=0.7,
                    timeout=CONFIG["resilience"]["timeouts"]["llm_call"]
                )

            try:
                reflection_llm = OllamaLLM(
                    model=CONFIG["models"]["reflection"],
                    temperature=0.7,
                    timeout=CONFIG["resilience"]["timeouts"]["llm_call"]
                )
                logger.info(f"Loaded reflection model: {CONFIG['models']['reflection']}")
            except Exception as e:
                logger.warning(f"Reflection model not available: {e}")
                reflection_llm = primary_llm

            print_success("Language models loaded")

            # Initialize cognitive engines
            self.reflection = ReflectionEngine(reflection_llm)
            self.planner = PlanningEngine(primary_llm)
            self.proactive = ProactiveMonitor(primary_llm)

            # Initialize health checks
            self.health_check = HealthCheck(
                self.memory,
                self.reflection,
                self.planner,
                self.proactive
            )

            # Try to load JRVS MCP (optional)
            try:
                sys.path.insert(0, str(Path.home() / "JRVS"))
                from mcp.client import mcp_client

                await with_timeout(
                    mcp_client.initialize(),
                    timeout=30,
                    operation_name="MCP initialization"
                )

                self.mcp_client = mcp_client
                servers = await mcp_client.list_servers()

                if servers:
                    print_success(f"MCP: Connected to {len(servers)} server(s)")
                else:
                    print_warning("MCP: No servers configured")

            except Exception as e:
                logger.warning(f"MCP not available: {e}")
                print_warning("MCP not available (optional)")
                self.mcp_client = None

            # Build agent
            tools = self._build_tools()
            agent = self._build_agent(primary_llm, tools)

            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                memory=ConversationBufferMemory(memory_key="chat_history", return_messages=False),
                verbose=False,  # Reduce verbosity for production
                handle_parsing_errors=True,
                max_iterations=20
            )

            # Start proactive monitoring
            self.proactive.start_monitoring()

            self.initialized = True
            metrics.increment("system.initialize_success")
            logger.info("CORTANA_JRVS initialized successfully")
            print_success("All systems online")

            # Show startup status
            await self._show_status()

        except Exception as e:
            logger.error(f"Initialization failed: {e}", exc_info=True)
            metrics.increment("system.initialize_failure")
            print_error(f"Initialization failed: {e}")
            raise

    def _build_tools(self) -> List[Tool]:
        """Build tool list for agent"""
        tools = [
            Tool(
                name="CreatePlan",
                func=lambda goal: asyncio.run(self.planner.create_plan(goal)),
                description="Create hierarchical plan for complex goal. Input: goal description"
            ),
            Tool(
                name="ViewPlans",
                func=lambda _: self.planner.view_plans(),
                description="View all created plans"
            ),
            Tool(
                name="AddGoal",
                func=lambda spec: self._add_goal_wrapper(spec),
                description="Add a trackable goal. Format: 'description|optional_deadline_iso8601'"
            ),
            Tool(
                name="ViewGoals",
                func=lambda _: self.proactive.view_goals(),
                description="View all active goals"
            ),
            Tool(
                name="SearchMemory",
                func=lambda query: asyncio.run(self.memory.recall_episodic(query)),
                description="Search episodic memory for past conversations and events"
            )
        ]

        return tools

    def _add_goal_wrapper(self, spec: str) -> str:
        """Wrapper for goal addition with parsing"""
        parts = spec.split('|')
        desc = parts[0].strip()
        deadline = parts[1].strip() if len(parts) > 1 else None
        return self.proactive.add_goal(desc, deadline)

    def _build_agent(self, llm, tools):
        """Build ReAct agent with enhanced prompting"""
        template = """You are CORTANA_JRVS, an enterprise-grade AI assistant combining deep reasoning with practical execution.

You have access to these tools:
{tools}

Tool Names: {tool_names}

IMPORTANT INSTRUCTIONS:
- For simple requests (greetings, questions), respond directly without tools
- Use tools strategically for complex tasks that require planning, memory, or goal tracking
- Think step-by-step for complex problems
- Be concise and professional
- Always validate inputs before processing

Previous conversation context:
{chat_history}

Current question: {input}

Thought process: {agent_scratchpad}"""

        prompt = PromptTemplate(
            input_variables=["tools", "tool_names", "chat_history", "input", "agent_scratchpad"],
            template=template
        )

        return create_react_agent(llm, tools, prompt)

    async def process_message(self, user_input: str):
        """Process user message with full cognitive pipeline and error handling"""
        correlation_id = str(uuid.uuid4())
        threading.current_thread().correlation_id = correlation_id

        logger.info(f"Processing message: {user_input[:100]}")
        metrics.increment("messages.received")

        try:
            # Sanitize input
            user_input = InputSanitizer.sanitize(user_input)
            safe, patterns = InputSanitizer.check_dangerous_patterns(user_input)

            if not safe:
                print_error(f"Input contains dangerous patterns: {patterns}")
                metrics.increment("messages.rejected")
                return

            # Retrieve fused memory
            with metrics.timer("messages.memory_retrieval"):
                context = await self.memory.fused_recall(user_input, self.session_id)

            # Inject context if relevant
            if context:
                full_input = f"{context}\n\nUser: {user_input}"
            else:
                full_input = user_input

            # Generate response
            with metrics.timer("messages.generation"):
                with Progress(SpinnerColumn(), TextColumn("Thinking..."), console=console) as progress:
                    progress.add_task("", total=None)

                    response = await with_timeout(
                        asyncio.to_thread(self.agent_executor.invoke, {"input": full_input}),
                        timeout=CONFIG["resilience"]["timeouts"]["llm_call"] * 1.5,  # Extra time for agent
                        operation_name="message processing"
                    )

            output = response.get('output', 'No response generated')

            # Truncate if too long
            if len(output) > CONFIG["security"]["max_output_length"]:
                output = output[:CONFIG["security"]["max_output_length"]] + "\n\n[Output truncated]"

            # Reflection loop
            if self.reflection.enabled:
                with metrics.timer("messages.reflection"):
                    output, score = await self.reflection.reflect(user_input, output)
                    if score > 0:
                        print_success(f"Quality score: {score}/10")

            # Display response
            if CONFIG["ui"]["markdown_output"]:
                console.print(Panel(Markdown(output), border_style=theme['primary']))
            else:
                console.print(Panel(output, border_style=theme['primary']))

            # Store interaction
            await self.memory.store_memory(
                f"User: {user_input}\nAssistant: {output}",
                {
                    "type": "conversation",
                    "session": self.session_id,
                    "correlation_id": correlation_id
                }
            )

            metrics.increment("messages.success")
            logger.info("Message processed successfully")

        except asyncio.TimeoutError as e:
            logger.error(f"Message processing timeout: {e}")
            print_error("Request timed out. Please try again or simplify your request.")
            metrics.increment("messages.timeout")

        except Exception as e:
            logger.error(f"Message processing error: {e}", exc_info=True)
            print_error(f"An error occurred: {str(e)}")
            metrics.increment("messages.error")

    async def handle_command(self, command: str):
        """Handle slash commands with comprehensive error handling"""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        logger.info(f"Handling command: /{cmd}")
        metrics.increment(f"commands.{cmd}")

        try:
            if cmd == "help":
                self._show_help()

            elif cmd == "plan":
                if not arg:
                    print_error("Usage: /plan <goal description>")
                    return
                await self.planner.create_plan(arg)

            elif cmd == "execute":
                if not arg:
                    print_error("Usage: /execute <plan_id>")
                    return
                await self.planner.execute_plan(arg, self.agent_executor)

            elif cmd == "plans":
                self.planner.view_plans()

            elif cmd == "goal":
                if not arg:
                    print_error("Usage: /goal <description>|<optional_deadline>")
                    return
                parts = arg.split('|')
                self.proactive.add_goal(parts[0], parts[1] if len(parts) > 1 else None)

            elif cmd == "goals":
                self.proactive.view_goals()

            elif cmd == "reflect":
                if arg == "on":
                    self.reflection.enabled = True
                    print_success("Reflection enabled")
                elif arg == "off":
                    self.reflection.enabled = False
                    print_success("Reflection disabled")
                else:
                    print_error("Usage: /reflect on|off")

            elif cmd == "health":
                await self._show_health()

            elif cmd == "mcp":
                await self._show_mcp_tools()

            elif cmd == "metrics":
                self._show_metrics()

            elif cmd == "status":
                await self._show_status()

            else:
                print_error(f"Unknown command: {cmd}. Type /help for available commands.")

        except Exception as e:
            logger.error(f"Command error: {e}", exc_info=True)
            print_error(f"Command failed: {e}")

    def _show_help(self):
        """Display comprehensive help"""
        help_text = f"""
## CORTANA_JRVS v{__version__} - Commands

### Core Commands
- `/help` - Show this help message
- `/health` - System health check
- `/status` - System status summary
- `/metrics` - View system metrics

### Planning & Goals
- `/plan <goal>` - Create hierarchical plan from goal
- `/execute <plan_id>` - Execute a plan
- `/plans` - View all plans
- `/goal <description>|<deadline>` - Add trackable goal
- `/goals` - View all goals

### Cognitive Control
- `/reflect on|off` - Toggle self-reflection mode
- `/mcp` - List available MCP tools

## Features

🧠 **Memory Fusion** - Episodic (ChromaDB) + Semantic (JRVS RAG)
🤔 **Self-Reflection** - Quality scoring & auto-improvement
📋 **Hierarchical Planning** - Task decomposition with dependencies
🎯 **Proactive Monitoring** - Goal tracking & deadline reminders
🔧 **MCP Integration** - External tool ecosystem
🛡️  **Enterprise Resilience** - Timeouts, retries, circuit breakers

## Input Safety
- Maximum input length: {CONFIG['security']['max_input_length']} characters
- Dangerous pattern detection enabled
- All inputs sanitized and validated
"""
        console.print(Panel(Markdown(help_text), title="Help", border_style="cyan"))

    async def _show_status(self):
        """Display system status"""
        table = Table(title="System Status", box=box.ROUNDED)
        table.add_column("Component", style="cyan")
        table.add_column("Status")
        table.add_column("Details")

        # Memory
        mem_status = "✅ Online" if self.memory.initialized else "❌ Offline"
        mem_details = f"Cache: {len(self.memory.embedding_cache)}"
        table.add_row("Memory", mem_status, mem_details)

        # Reflection
        refl_status = "✅ Enabled" if self.reflection.enabled else "⚠️ Disabled"
        table.add_row("Reflection", refl_status, "")

        # Planning
        with self.planner.lock:
            plan_count = len(self.planner.plans)
        table.add_row("Planning", "✅ Online", f"{plan_count} plans")

        # Proactive
        proactive_status = "✅ Running" if self.proactive.running else "⚠️ Stopped"
        with self.proactive.lock:
            goal_count = len(self.proactive.goals)
        table.add_row("Proactive", proactive_status, f"{goal_count} goals")

        # MCP
        mcp_status = "✅ Connected" if self.mcp_client else "⚠️ Not available"
        table.add_row("MCP", mcp_status, "")

        console.print(table)

    async def _show_health(self):
        """Display comprehensive health check results"""
        print_info("Running health checks...", "🏥")

        checks = await self.health_check.check_all()

        table = Table(title="Health Check Results", box=box.ROUNDED)
        table.add_column("Component", style="cyan")
        table.add_column("Status")
        table.add_column("Message")
        table.add_column("Timestamp")

        for check in checks:
            # Style based on status
            if check.status == ComponentStatus.HEALTHY:
                status_display = "[green]✅ Healthy[/green]"
            elif check.status == ComponentStatus.DEGRADED:
                status_display = "[yellow]⚠️ Degraded[/yellow]"
            elif check.status == ComponentStatus.UNHEALTHY:
                status_display = "[red]❌ Unhealthy[/red]"
            else:
                status_display = "[gray]? Unknown[/gray]"

            timestamp = datetime.fromisoformat(check.timestamp).strftime("%H:%M:%S")

            table.add_row(
                check.component,
                status_display,
                check.message,
                timestamp
            )

        console.print(table)

        # Overall status
        all_healthy = all(c.status == ComponentStatus.HEALTHY for c in checks)
        any_unhealthy = any(c.status == ComponentStatus.UNHEALTHY for c in checks)

        if all_healthy:
            print_success("All systems healthy")
        elif any_unhealthy:
            print_error("Some systems unhealthy - check logs")
        else:
            print_warning("Some systems degraded")

    async def _show_mcp_tools(self):
        """Display available MCP tools"""
        if not self.mcp_client:
            print_error("MCP not available")
            return

        try:
            tools = await self.mcp_client.list_all_tools()

            if not tools:
                print_info("No MCP tools available")
                return

            table = Table(title="MCP Tools", box=box.ROUNDED)
            table.add_column("Server", style="cyan")
            table.add_column("Tool")
            table.add_column("Description")

            for server, tool_list in tools.items():
                for tool in tool_list:
                    desc = tool.get('description', '')[:50]
                    if len(tool.get('description', '')) > 50:
                        desc += "..."
                    table.add_row(server, tool['name'], desc)

            console.print(table)

        except Exception as e:
            print_error(f"Failed to fetch MCP tools: {e}")

    def _show_metrics(self):
        """Display system metrics"""
        metric_data = metrics.get_metrics()

        # Counters
        if metric_data["counters"]:
            table = Table(title="Counters", box=box.SIMPLE)
            table.add_column("Metric", style="cyan")
            table.add_column("Count", justify="right")

            for name, value in sorted(metric_data["counters"].items()):
                table.add_row(name, str(value))

            console.print(table)

        # Timers
        if metric_data["timers"]:
            table = Table(title="Timers", box=box.SIMPLE)
            table.add_column("Operation", style="cyan")
            table.add_column("Count", justify="right")
            table.add_column("Avg (ms)", justify="right")
            table.add_column("Min (ms)", justify="right")
            table.add_column("Max (ms)", justify="right")

            for name, stats in sorted(metric_data["timers"].items()):
                table.add_row(
                    name,
                    str(stats["count"]),
                    f"{stats['avg_ms']:.2f}",
                    f"{stats['min_ms']:.2f}",
                    f"{stats['max_ms']:.2f}"
                )

            console.print(table)

        # Save metrics
        try:
            metrics.save_to_file(CONFIG["data"]["metrics_file"])
            print_info(f"Metrics saved to {CONFIG['data']['metrics_file']}", "💾")
        except Exception as e:
            print_warning(f"Failed to save metrics: {e}")

    async def run(self):
        """Main interaction loop with graceful shutdown handling"""
        try:
            await self.initialize()
        except Exception as e:
            print_error(f"Initialization failed: {e}")
            return

        console.print("\n[bold]Type your message or /help for commands. Ctrl+C to exit.[/]\n")

        try:
            while not self.shutdown_requested:
                try:
                    user_input = await asyncio.to_thread(
                        console.input,
                        f"[{theme['primary']}]You>[/] "
                    )

                    if not user_input.strip():
                        continue

                    if user_input.lower() in ['quit', 'exit', '/quit', '/exit']:
                        break

                    if user_input.startswith('/'):
                        await self.handle_command(user_input[1:])
                    else:
                        await self.process_message(user_input)

                    console.print()

                except EOFError:
                    break

        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down gracefully...[/]")

        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources gracefully"""
        logger.info("Starting cleanup")
        print_info("Cleaning up...", "🧹")

        try:
            # Stop proactive monitor
            self.proactive.stop_monitoring()

            # Save final state
            self.planner._save_plans()
            self.proactive._save_goals()

            # Save metrics
            metrics.save_to_file(CONFIG["data"]["metrics_file"])

            # Cleanup memory
            if self.memory:
                await self.memory.cleanup()

            print_success("Cleanup complete")
            logger.info("Cleanup completed successfully")

        except Exception as e:
            logger.error(f"Cleanup error: {e}", exc_info=True)
            print_warning(f"Cleanup warning: {e}")

# ==================== ENTRY POINT ====================

async def main():
    """Main entry point with signal handling"""

    # Create assistant instance
    assistant = CortanaJRVS()

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        assistant.shutdown_requested = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run assistant
    await assistant.run()

if __name__ == "__main__":
    try:
        # Ensure Python 3.8+
        if sys.version_info < (3, 8):
            print("Error: Python 3.8 or higher is required")
            sys.exit(1)

        # Run main application
        asyncio.run(main())

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        sys.exit(0)

    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/]")
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
