"""
BaseExtension — abstract base class every JRVS extension must implement.

Extensions are self-contained async services.  JRVS core never imports them
directly; they hook in by writing to shared SQLite/FAISS state and the events
table.  JRVS orchestration code imports extensions and calls their public API.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

logger = logging.getLogger(__name__)


class BaseExtension(ABC):
    """Common interface for all JRVS extension modules."""

    # ---------------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------------

    @abstractmethod
    async def initialize(self) -> None:
        """One-time async setup: load models, open devices, connect to DB."""

    @abstractmethod
    async def stop(self) -> None:
        """Graceful shutdown: flush buffers, release hardware, cancel tasks."""

    # ---------------------------------------------------------------------------
    # Introspection
    # ---------------------------------------------------------------------------

    @abstractmethod
    def is_running(self) -> bool:
        """Return True while the extension's background loop is active."""

    @abstractmethod
    def status(self) -> Dict[str, Any]:
        """Return a snapshot dict suitable for health-check endpoints."""
