"""
JRVS Observability — Structured event tracing and resource monitoring.

Provides:
  1. TraceEvent — structured events with correlation IDs for full request traces
  2. Tracer — singleton that collects events and exposes them via SSE / polling
  3. ResourceMonitor — CPU / RAM / VRAM / disk / model-load status
  4. FastAPI integration — /api/trace and /api/resources endpoints

Every major operation (RAG retrieval, LLM inference, tool calls, web scraping)
emits a TraceEvent so the user can always see exactly what JRVS is doing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Trace Events ──────────────────────────────────────────────────────────────

@dataclass
class TraceEvent:
    """A single traced operation within a request."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    trace_id: str = ""          # Correlation ID for the full request
    timestamp: str = ""         # ISO-8601
    category: str = ""          # "rag", "llm", "tool", "scrape", "agent", "system"
    operation: str = ""         # e.g. "retrieve_context", "generate", "web_search"
    status: str = "started"     # "started", "completed", "error"
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Strip None values for cleaner JSON output
        return {k: v for k, v in d.items() if v is not None}


class Tracer:
    """
    Singleton trace collector.

    Usage:
        trace_id = tracer.start_trace("user_chat")
        tracer.emit(trace_id, "rag", "retrieve_context", metadata={"query": "..."})
        ...
        tracer.complete(event_id, duration_ms=42.5)
    """

    def __init__(self, max_events: int = 2000, max_traces: int = 200) -> None:
        self._events: Deque[TraceEvent] = deque(maxlen=max_events)
        self._active_traces: Dict[str, List[TraceEvent]] = {}
        self._max_traces = max_traces
        self._trace_order: Deque[str] = deque()
        self._listeners: List[asyncio.Queue] = []

    def start_trace(self, label: str = "") -> str:
        """Start a new trace and return its trace_id."""
        trace_id = str(uuid.uuid4())[:12]
        self._active_traces[trace_id] = []
        self._trace_order.append(trace_id)
        # Evict oldest traces if over limit
        while len(self._active_traces) > self._max_traces:
            old = self._trace_order.popleft()
            self._active_traces.pop(old, None)
        self.emit(trace_id, "system", "trace_start", metadata={"label": label})
        return trace_id

    def emit(
        self,
        trace_id: str,
        category: str,
        operation: str,
        status: str = "started",
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> str:
        """Emit a trace event. Returns the event_id."""
        event = TraceEvent(
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            category=category,
            operation=operation,
            status=status,
            duration_ms=duration_ms,
            metadata=metadata or {},
            error=error,
        )
        self._events.append(event)
        if trace_id in self._active_traces:
            self._active_traces[trace_id].append(event)

        # Notify SSE listeners
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

        return event.event_id

    def get_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        """Get all events for a specific trace."""
        events = self._active_traces.get(trace_id, [])
        return [e.to_dict() for e in events]

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get the most recent events across all traces."""
        recent = list(self._events)[-limit:]
        return [e.to_dict() for e in recent]

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to real-time trace events (for SSE streaming)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a listener."""
        try:
            self._listeners.remove(q)
        except ValueError:
            pass


class ResourceMonitor:
    """Collects system resource metrics for the local device."""

    @staticmethod
    def snapshot() -> Dict[str, Any]:
        """Return a point-in-time resource snapshot."""
        info: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device_class": os.environ.get("JRVS_DEVICE_CLASS", "desktop"),
        }

        try:
            import psutil
            mem = psutil.virtual_memory()
            info["cpu"] = {
                "percent": psutil.cpu_percent(interval=0.1),
                "cores": psutil.cpu_count(),
            }
            info["memory"] = {
                "total_mb": round(mem.total / 1024 / 1024),
                "used_mb": round(mem.used / 1024 / 1024),
                "percent": mem.percent,
            }
            disk = psutil.disk_usage("/")
            info["disk"] = {
                "total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
                "used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                "percent": disk.percent,
            }
        except ImportError:
            info["cpu"] = {"error": "psutil not installed"}
            info["memory"] = {"error": "psutil not installed"}
            info["disk"] = {"error": "psutil not installed"}

        # GPU/VRAM (optional — only if torch is available)
        try:
            import torch
            if torch.cuda.is_available():
                info["gpu"] = {
                    "name": torch.cuda.get_device_name(0),
                    "vram_total_mb": round(torch.cuda.get_device_properties(0).total_memory / 1024 / 1024),
                    "vram_allocated_mb": round(torch.cuda.memory_allocated(0) / 1024 / 1024),
                    "vram_reserved_mb": round(torch.cuda.memory_reserved(0) / 1024 / 1024),
                }
            else:
                info["gpu"] = {"available": False}
        except ImportError:
            info["gpu"] = {"available": False, "note": "torch not installed"}

        return info


# ── Singleton instances ───────────────────────────────────────────────────────

tracer = Tracer()
resource_monitor = ResourceMonitor()


# ── Convenience context manager for timed trace spans ─────────────────────────

class trace_span:
    """
    Context manager that emits start/complete trace events with timing.

    Usage:
        with trace_span(trace_id, "rag", "retrieve_context", metadata={...}) as span:
            results = await rag_retriever.search(...)
            span.metadata["chunks_found"] = len(results)
    """

    def __init__(
        self,
        trace_id: str,
        category: str,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.trace_id = trace_id
        self.category = category
        self.operation = operation
        self.metadata = metadata or {}
        self._start: float = 0
        self.event_id: str = ""

    def __enter__(self) -> "trace_span":
        self._start = time.perf_counter()
        self.event_id = tracer.emit(
            self.trace_id, self.category, self.operation,
            status="started", metadata=self.metadata,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.perf_counter() - self._start) * 1000
        if exc_type is not None:
            tracer.emit(
                self.trace_id, self.category, self.operation,
                status="error", duration_ms=round(duration_ms, 2),
                metadata=self.metadata, error=str(exc_val),
            )
        else:
            tracer.emit(
                self.trace_id, self.category, self.operation,
                status="completed", duration_ms=round(duration_ms, 2),
                metadata=self.metadata,
            )
        return None  # Don't suppress exceptions


class async_trace_span:
    """Async version of trace_span for use with `async with`."""

    def __init__(
        self,
        trace_id: str,
        category: str,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.trace_id = trace_id
        self.category = category
        self.operation = operation
        self.metadata = metadata or {}
        self._start: float = 0
        self.event_id: str = ""

    async def __aenter__(self) -> "async_trace_span":
        self._start = time.perf_counter()
        self.event_id = tracer.emit(
            self.trace_id, self.category, self.operation,
            status="started", metadata=self.metadata,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.perf_counter() - self._start) * 1000
        if exc_type is not None:
            tracer.emit(
                self.trace_id, self.category, self.operation,
                status="error", duration_ms=round(duration_ms, 2),
                metadata=self.metadata, error=str(exc_val),
            )
        else:
            tracer.emit(
                self.trace_id, self.category, self.operation,
                status="completed", duration_ms=round(duration_ms, 2),
                metadata=self.metadata,
            )
        return None
