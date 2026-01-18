"""
Graceful shutdown handler for JRVS MCP Server

Handles SIGTERM/SIGINT signals and ensures clean shutdown
of all components with proper cleanup.
"""

import signal
import asyncio
import sys
from typing import List, Callable, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """Handle graceful shutdown of the server"""

    def __init__(self):
        self._shutdown_requested = False
        self._cleanup_tasks: List[tuple] = []  # (name, async_func)
        self._shutdown_timeout = 30  # seconds
        self._start_time: Optional[datetime] = None

    def register_cleanup(self, name: str, cleanup_func: Callable):
        """
        Register a cleanup function to run on shutdown

        Args:
            name: Name of the cleanup task
            cleanup_func: Async function to call on shutdown
        """
        self._cleanup_tasks.append((name, cleanup_func))
        logger.debug(f"Registered shutdown cleanup: {name}")

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        # Handle SIGTERM and SIGINT
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info("Signal handlers registered for graceful shutdown")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name} signal, initiating graceful shutdown...")

        self._shutdown_requested = True

        # For asyncio, we need to schedule the shutdown
        # This will be picked up by the main event loop
        asyncio.create_task(self.shutdown())

    async def shutdown(self):
        """Execute graceful shutdown"""
        if self._start_time is not None:
            logger.warning("Shutdown already in progress")
            return

        self._start_time = datetime.utcnow()

        logger.info("=" * 70)
        logger.info("GRACEFUL SHUTDOWN INITIATED")
        logger.info("=" * 70)

        # Run cleanup tasks
        success_count = 0
        failed_count = 0

        for name, cleanup_func in self._cleanup_tasks:
            try:
                logger.info(f"Running cleanup: {name}")

                # Run with timeout
                await asyncio.wait_for(
                    cleanup_func(),
                    timeout=10.0  # 10 seconds per cleanup task
                )

                logger.info(f"✓ Cleanup completed: {name}")
                success_count += 1

            except asyncio.TimeoutError:
                logger.error(f"✗ Cleanup timeout: {name}")
                failed_count += 1

            except Exception as e:
                logger.error(f"✗ Cleanup failed: {name} - {e}", exc_info=True)
                failed_count += 1

        # Calculate shutdown time
        shutdown_duration = (datetime.utcnow() - self._start_time).total_seconds()

        logger.info("=" * 70)
        logger.info("SHUTDOWN SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Successful cleanups: {success_count}")
        logger.info(f"Failed cleanups: {failed_count}")
        logger.info(f"Shutdown duration: {shutdown_duration:.2f}s")
        logger.info("=" * 70)

        logger.info("Server shutdown complete")

        # Exit
        sys.exit(0)

    def is_shutting_down(self) -> bool:
        """Check if shutdown has been requested"""
        return self._shutdown_requested


# Global shutdown handler
shutdown_handler = ShutdownHandler()


async def cleanup_database():
    """Cleanup database connections"""
    try:
        from core.database import db
        if hasattr(db, 'close'):
            await db.close()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Database cleanup error: {e}")


async def cleanup_cache():
    """Cleanup cache"""
    try:
        from .cache import cache_manager
        cache_manager.clear_all()
        logger.info("Cache cleared")
    except Exception as e:
        logger.error(f"Cache cleanup error: {e}")


async def cleanup_ollama():
    """Cleanup Ollama client"""
    try:
        from llm.ollama_client import ollama_client
        # Close any open connections
        if hasattr(ollama_client, 'close'):
            await ollama_client.close()
        logger.info("Ollama client closed")
    except Exception as e:
        logger.error(f"Ollama cleanup error: {e}")


async def cleanup_mcp_client():
    """Cleanup MCP client connections"""
    try:
        from .client import mcp_client
        if mcp_client.initialized:
            await mcp_client.cleanup()
        logger.info("MCP client connections closed")
    except Exception as e:
        logger.error(f"MCP client cleanup error: {e}")


async def save_metrics():
    """Save metrics before shutdown"""
    try:
        from .metrics import metrics
        summary = metrics.get_summary()
        logger.info(f"Final metrics: {summary}")
    except Exception as e:
        logger.error(f"Metrics save error: {e}")


def register_default_cleanup_tasks():
    """Register all default cleanup tasks"""
    shutdown_handler.register_cleanup("save_metrics", save_metrics)
    shutdown_handler.register_cleanup("database", cleanup_database)
    shutdown_handler.register_cleanup("cache", cleanup_cache)
    shutdown_handler.register_cleanup("ollama", cleanup_ollama)
    shutdown_handler.register_cleanup("mcp_client", cleanup_mcp_client)
