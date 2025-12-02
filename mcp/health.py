"""
Health check and monitoring system for JRVS MCP Server

Provides comprehensive health checks for all system components
and dependencies.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component"""
    component: str
    status: HealthStatus
    message: str
    last_check: datetime
    response_time_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data["status"] = self.status.value
        data["last_check"] = self.last_check.isoformat()
        return data


class HealthChecker:
    """Perform health checks on system components"""

    def __init__(self):
        self.checks: Dict[str, ComponentHealth] = {}
        self._check_functions: Dict[str, callable] = {}

    def register_check(self, component: str, check_func: callable):
        """Register a health check function"""
        self._check_functions[component] = check_func

    async def check_component(self, component: str) -> ComponentHealth:
        """Run health check for a specific component"""
        if component not in self._check_functions:
            return ComponentHealth(
                component=component,
                status=HealthStatus.UNKNOWN,
                message="No health check registered",
                last_check=datetime.utcnow()
            )

        start_time = datetime.utcnow()

        try:
            check_func = self._check_functions[component]
            result = await check_func()

            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            if isinstance(result, ComponentHealth):
                result.response_time_ms = response_time
                self.checks[component] = result
                return result

            # If function returns bool
            health = ComponentHealth(
                component=component,
                status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                message="OK" if result else "Check failed",
                last_check=datetime.utcnow(),
                response_time_ms=response_time
            )

            self.checks[component] = health
            return health

        except Exception as e:
            logger.error(f"Health check failed for {component}: {e}")

            health = ComponentHealth(
                component=component,
                status=HealthStatus.UNHEALTHY,
                message=f"Error: {str(e)}",
                last_check=datetime.utcnow(),
                response_time_ms=(datetime.utcnow() - start_time).total_seconds() * 1000
            )

            self.checks[component] = health
            return health

    async def check_all(self) -> Dict[str, ComponentHealth]:
        """Run all registered health checks"""
        results = await asyncio.gather(
            *[self.check_component(comp) for comp in self._check_functions.keys()],
            return_exceptions=True
        )

        return {
            check.component: check
            for check in results
            if isinstance(check, ComponentHealth)
        }

    def get_overall_status(self) -> HealthStatus:
        """Get overall system health status"""
        if not self.checks:
            return HealthStatus.UNKNOWN

        statuses = [check.status for check in self.checks.values()]

        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        elif all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN

    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report"""
        overall_status = self.get_overall_status()

        return {
            "status": overall_status.value,
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                name: check.to_dict()
                for name, check in self.checks.items()
            },
            "summary": {
                "total_components": len(self.checks),
                "healthy": sum(1 for c in self.checks.values() if c.status == HealthStatus.HEALTHY),
                "degraded": sum(1 for c in self.checks.values() if c.status == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for c in self.checks.values() if c.status == HealthStatus.UNHEALTHY),
            }
        }


# Global health checker
health_checker = HealthChecker()


# Standard health check functions
async def check_ollama_health() -> ComponentHealth:
    """Check Ollama service health"""
    try:
        from llm.ollama_client import ollama_client

        # Try to list models
        models = await ollama_client.discover_models()

        if not models:
            return ComponentHealth(
                component="ollama",
                status=HealthStatus.DEGRADED,
                message="Connected but no models available",
                last_check=datetime.utcnow()
            )

        return ComponentHealth(
            component="ollama",
            status=HealthStatus.HEALTHY,
            message=f"Connected - {len(models)} models available",
            last_check=datetime.utcnow(),
            details={"model_count": len(models), "current_model": ollama_client.current_model}
        )

    except Exception as e:
        return ComponentHealth(
            component="ollama",
            status=HealthStatus.UNHEALTHY,
            message=f"Connection failed: {str(e)}",
            last_check=datetime.utcnow()
        )


async def check_database_health() -> ComponentHealth:
    """Check database health"""
    try:
        from core.database import db

        # Try a simple query
        await db.initialize()

        return ComponentHealth(
            component="database",
            status=HealthStatus.HEALTHY,
            message="Database operational",
            last_check=datetime.utcnow(),
            details={"path": str(db.db_path) if hasattr(db, 'db_path') else None}
        )

    except Exception as e:
        return ComponentHealth(
            component="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database error: {str(e)}",
            last_check=datetime.utcnow()
        )


async def check_rag_health() -> ComponentHealth:
    """Check RAG system health"""
    try:
        from rag.retriever import rag_retriever

        await rag_retriever.initialize()
        stats = await rag_retriever.get_stats()

        vector_count = stats.get("vector_store", {}).get("total_vectors", 0)

        if vector_count == 0:
            return ComponentHealth(
                component="rag",
                status=HealthStatus.DEGRADED,
                message="RAG initialized but no vectors indexed",
                last_check=datetime.utcnow(),
                details=stats
            )

        return ComponentHealth(
            component="rag",
            status=HealthStatus.HEALTHY,
            message=f"RAG operational - {vector_count} vectors indexed",
            last_check=datetime.utcnow(),
            details=stats
        )

    except Exception as e:
        return ComponentHealth(
            component="rag",
            status=HealthStatus.UNHEALTHY,
            message=f"RAG error: {str(e)}",
            last_check=datetime.utcnow()
        )


async def check_calendar_health() -> ComponentHealth:
    """Check calendar system health"""
    try:
        from core.calendar import calendar

        await calendar.initialize()

        return ComponentHealth(
            component="calendar",
            status=HealthStatus.HEALTHY,
            message="Calendar operational",
            last_check=datetime.utcnow()
        )

    except Exception as e:
        return ComponentHealth(
            component="calendar",
            status=HealthStatus.UNHEALTHY,
            message=f"Calendar error: {str(e)}",
            last_check=datetime.utcnow()
        )


async def check_cache_health() -> ComponentHealth:
    """Check cache system health"""
    try:
        from .cache import cache_manager

        stats = cache_manager.get_all_stats()

        total_size = sum(s["size"] for s in stats.values())
        total_hits = sum(s["hits"] for s in stats.values())
        total_misses = sum(s["misses"] for s in stats.values())

        total_requests = total_hits + total_misses
        hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0

        return ComponentHealth(
            component="cache",
            status=HealthStatus.HEALTHY,
            message=f"Cache operational - {hit_rate:.1f}% hit rate",
            last_check=datetime.utcnow(),
            details={
                "total_entries": total_size,
                "hit_rate": round(hit_rate, 2),
                "caches": stats
            }
        )

    except Exception as e:
        return ComponentHealth(
            component="cache",
            status=HealthStatus.DEGRADED,
            message=f"Cache error: {str(e)}",
            last_check=datetime.utcnow()
        )


# Register default health checks
def register_default_checks():
    """Register all default health checks"""
    health_checker.register_check("ollama", check_ollama_health)
    health_checker.register_check("database", check_database_health)
    health_checker.register_check("rag", check_rag_health)
    health_checker.register_check("calendar", check_calendar_health)
    health_checker.register_check("cache", check_cache_health)


async def health_monitor_task(interval_seconds: int = 60):
    """Background task to periodically run health checks"""
    while True:
        try:
            await health_checker.check_all()
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Health monitor error: {e}")
            await asyncio.sleep(interval_seconds)
