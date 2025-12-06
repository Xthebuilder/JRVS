"""
Metrics collection and reporting
"""

import json
import threading
import time
import logging
from contextlib import contextmanager
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger("CORTANA.metrics")


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
            metrics["timestamp"] = time.time()

            # Ensure directory exists
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)

            with open(filepath, 'w') as f:
                json.dump(metrics, f, indent=2)

            logger.debug(f"Metrics saved to {filepath}")

        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    def reset(self):
        """Reset all metrics"""
        with self.lock:
            self.metrics = {
                "counters": {},
                "gauges": {},
                "histograms": {},
                "timers": {}
            }


# Global metrics instance
metrics = MetricsCollector()
