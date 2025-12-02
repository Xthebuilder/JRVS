"""
Metrics collection and monitoring for JRVS MCP Server

Provides real-time metrics tracking for performance monitoring,
resource usage, and system health.
"""

import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict, deque
from threading import Lock
import psutil


@dataclass
class MetricPoint:
    """Single metric data point"""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class RequestMetrics:
    """Metrics for a single request"""
    tool_name: str
    success: bool
    duration_ms: float
    timestamp: datetime
    error_type: Optional[str] = None


class MetricsCollector:
    """Collect and aggregate metrics"""

    def __init__(self, retention_seconds: int = 3600):
        self.retention_seconds = retention_seconds
        self._lock = Lock()

        # Request tracking
        self.request_count = defaultdict(int)  # tool_name -> count
        self.error_count = defaultdict(int)    # tool_name -> count
        self.request_history: deque = deque(maxlen=10000)

        # Performance tracking
        self.duration_buckets = defaultdict(list)  # tool_name -> [durations]

        # Resource tracking
        self.resource_samples: deque = deque(maxlen=1000)

        # Rate tracking
        self.rate_windows = defaultdict(lambda: deque(maxlen=100))  # tool_name -> [timestamps]

        # System start time
        self.start_time = datetime.utcnow()

    def record_request(self, metrics: RequestMetrics):
        """Record a request metric"""
        with self._lock:
            # Update counters
            self.request_count[metrics.tool_name] += 1
            if not metrics.success:
                self.error_count[metrics.tool_name] += 1

            # Add to history
            self.request_history.append(metrics)

            # Track duration
            self.duration_buckets[metrics.tool_name].append(metrics.duration_ms)

            # Track rate
            self.rate_windows[metrics.tool_name].append(metrics.timestamp)

            # Cleanup old data
            self._cleanup_old_data()

    def record_resource_usage(self):
        """Record current resource usage"""
        try:
            process = psutil.Process()

            sample = {
                "timestamp": datetime.utcnow(),
                "cpu_percent": process.cpu_percent(),
                "memory_mb": process.memory_info().rss / 1024 / 1024,
                "threads": process.num_threads(),
                "open_files": len(process.open_files()),
            }

            with self._lock:
                self.resource_samples.append(sample)
        except Exception:
            pass  # Silently fail if we can't get metrics

    def get_request_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Get request statistics"""
        with self._lock:
            if tool_name:
                total = self.request_count.get(tool_name, 0)
                errors = self.error_count.get(tool_name, 0)
                durations = self.duration_buckets.get(tool_name, [])
            else:
                total = sum(self.request_count.values())
                errors = sum(self.error_count.values())
                durations = [d for dlist in self.duration_buckets.values() for d in dlist]

            success_rate = ((total - errors) / total * 100) if total > 0 else 0

            stats = {
                "total_requests": total,
                "successful_requests": total - errors,
                "failed_requests": errors,
                "success_rate": round(success_rate, 2),
            }

            if durations:
                stats["performance"] = {
                    "avg_duration_ms": round(sum(durations) / len(durations), 2),
                    "min_duration_ms": round(min(durations), 2),
                    "max_duration_ms": round(max(durations), 2),
                    "p50_duration_ms": round(self._percentile(durations, 50), 2),
                    "p95_duration_ms": round(self._percentile(durations, 95), 2),
                    "p99_duration_ms": round(self._percentile(durations, 99), 2),
                }

            return stats

    def get_tool_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get per-tool statistics"""
        with self._lock:
            return {
                tool: self.get_request_stats(tool)
                for tool in self.request_count.keys()
            }

    def get_rate(self, tool_name: str, window_seconds: int = 60) -> float:
        """Get request rate for a tool"""
        with self._lock:
            timestamps = self.rate_windows.get(tool_name, deque())
            cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)

            recent = [ts for ts in timestamps if ts > cutoff]
            return len(recent) / window_seconds if recent else 0.0

    def get_resource_stats(self) -> Dict[str, Any]:
        """Get resource usage statistics"""
        with self._lock:
            if not self.resource_samples:
                return {}

            recent_samples = list(self.resource_samples)[-100:]  # Last 100 samples

            return {
                "current": recent_samples[-1] if recent_samples else {},
                "avg_cpu_percent": round(
                    sum(s["cpu_percent"] for s in recent_samples) / len(recent_samples), 2
                ),
                "avg_memory_mb": round(
                    sum(s["memory_mb"] for s in recent_samples) / len(recent_samples), 2
                ),
                "max_memory_mb": round(
                    max(s["memory_mb"] for s in recent_samples), 2
                ),
            }

    def get_uptime_seconds(self) -> float:
        """Get server uptime in seconds"""
        return (datetime.utcnow() - self.start_time).total_seconds()

    def get_error_breakdown(self) -> Dict[str, int]:
        """Get breakdown of errors by type"""
        with self._lock:
            error_types = defaultdict(int)

            for req in self.request_history:
                if not req.success and req.error_type:
                    error_types[req.error_type] += 1

            return dict(error_types)

    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive metrics summary"""
        return {
            "uptime_seconds": round(self.get_uptime_seconds(), 2),
            "requests": self.get_request_stats(),
            "tools": self.get_tool_stats(),
            "resources": self.get_resource_stats(),
            "errors": self.get_error_breakdown(),
        }

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile"""
        if not data:
            return 0.0

        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def _cleanup_old_data(self):
        """Remove old data beyond retention period"""
        cutoff = datetime.utcnow() - timedelta(seconds=self.retention_seconds)

        # Clean request history
        while self.request_history and self.request_history[0].timestamp < cutoff:
            self.request_history.popleft()

        # Clean duration buckets (keep last 1000 per tool)
        for tool in self.duration_buckets:
            if len(self.duration_buckets[tool]) > 1000:
                self.duration_buckets[tool] = self.duration_buckets[tool][-1000:]


# Global metrics collector
metrics = MetricsCollector()


async def metrics_monitor_task(interval_seconds: int = 30):
    """Background task to collect resource metrics"""
    while True:
        try:
            metrics.record_resource_usage()
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(interval_seconds)
