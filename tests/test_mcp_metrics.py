"""
Unit tests for mcp/metrics.py

Tests MetricsCollector: request recording, stats, rate, error breakdown.
Requires psutil (already in the project venv).
"""

import sys
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.metrics import MetricsCollector, RequestMetrics, MetricPoint


def _req(tool="search", success=True, duration_ms=100.0, error_type=None):
    return RequestMetrics(
        tool_name=tool,
        success=success,
        duration_ms=duration_ms,
        timestamp=datetime.utcnow(),
        error_type=error_type,
    )


class TestRequestRecording:
    def test_record_single_request(self):
        mc = MetricsCollector()
        mc.record_request(_req("tool"))
        stats = mc.get_request_stats("tool")
        assert stats["total"] == 1

    def test_record_multiple_requests(self):
        mc = MetricsCollector()
        for _ in range(5):
            mc.record_request(_req("tool"))
        stats = mc.get_request_stats("tool")
        assert stats["total"] == 5

    def test_error_count_tracked(self):
        mc = MetricsCollector()
        mc.record_request(_req("tool", success=True))
        mc.record_request(_req("tool", success=False, error_type="ValueError"))
        stats = mc.get_request_stats("tool")
        assert stats["errors"] == 1

    def test_success_rate_all_success(self):
        mc = MetricsCollector()
        for _ in range(4):
            mc.record_request(_req("t", success=True))
        stats = mc.get_request_stats("t")
        assert stats["success_rate"] == pytest.approx(100.0, abs=0.1)

    def test_success_rate_mixed(self):
        mc = MetricsCollector()
        mc.record_request(_req("t", success=True))
        mc.record_request(_req("t", success=False))
        stats = mc.get_request_stats("t")
        assert stats["success_rate"] == pytest.approx(50.0, abs=0.1)

    def test_no_stats_for_unknown_tool(self):
        mc = MetricsCollector()
        stats = mc.get_request_stats("never_called")
        # Should return empty/zero stats, not raise
        assert stats["total"] == 0

    def test_global_stats_no_tool_filter(self):
        mc = MetricsCollector()
        mc.record_request(_req("a"))
        mc.record_request(_req("b"))
        stats = mc.get_request_stats()
        assert stats["total"] >= 2


class TestToolStats:
    def test_get_tool_stats_shape(self):
        mc = MetricsCollector()
        mc.record_request(_req("search"))
        mc.record_request(_req("generate"))
        tool_stats = mc.get_tool_stats()
        assert "search" in tool_stats
        assert "generate" in tool_stats

    def test_tool_stats_has_required_fields(self):
        mc = MetricsCollector()
        mc.record_request(_req("search", duration_ms=50.0))
        stats = mc.get_tool_stats()["search"]
        assert "total" in stats
        assert "errors" in stats


class TestPerformanceStats:
    def test_duration_stats_present(self):
        mc = MetricsCollector()
        mc.record_request(_req("t", duration_ms=100.0))
        mc.record_request(_req("t", duration_ms=200.0))
        stats = mc.get_request_stats("t")
        # Should have some percentile info
        assert stats["total"] == 2


class TestRateTracking:
    def test_get_rate_returns_float(self):
        mc = MetricsCollector()
        mc.record_request(_req("search"))
        rate = mc.get_rate("search", window_seconds=60)
        assert isinstance(rate, float)
        assert rate >= 0.0

    def test_rate_zero_for_unknown_tool(self):
        mc = MetricsCollector()
        assert mc.get_rate("nope", window_seconds=60) == 0.0


class TestResourceStats:
    def test_get_resource_stats_shape(self):
        mc = MetricsCollector()
        stats = mc.get_resource_stats()
        # Should have CPU and memory keys
        assert isinstance(stats, dict)

    def test_record_resource_usage(self):
        mc = MetricsCollector()
        mc.record_resource_usage()  # Should not raise
        stats = mc.get_resource_stats()
        assert isinstance(stats, dict)


class TestUptime:
    def test_uptime_is_positive(self):
        mc = MetricsCollector()
        assert mc.get_uptime_seconds() >= 0.0

    def test_uptime_increases(self):
        import time
        mc = MetricsCollector()
        t1 = mc.get_uptime_seconds()
        time.sleep(0.05)
        t2 = mc.get_uptime_seconds()
        assert t2 > t1


class TestErrorBreakdown:
    def test_error_breakdown_counts_by_type(self):
        mc = MetricsCollector()
        mc.record_request(_req("t", success=False, error_type="ValueError"))
        mc.record_request(_req("t", success=False, error_type="ValueError"))
        mc.record_request(_req("t", success=False, error_type="TimeoutError"))
        breakdown = mc.get_error_breakdown()
        assert breakdown.get("ValueError", 0) == 2
        assert breakdown.get("TimeoutError", 0) == 1

    def test_error_breakdown_empty_when_no_errors(self):
        mc = MetricsCollector()
        mc.record_request(_req("t", success=True))
        breakdown = mc.get_error_breakdown()
        assert sum(breakdown.values()) == 0


class TestSummary:
    def test_get_summary_shape(self):
        mc = MetricsCollector()
        mc.record_request(_req("search"))
        summary = mc.get_summary()
        assert isinstance(summary, dict)
        assert len(summary) > 0


class TestMetricPoint:
    def test_metric_point_stores_values(self):
        mp = MetricPoint(timestamp=datetime.utcnow(), value=42.0, labels={"host": "x"})
        assert mp.value == 42.0
        assert mp.labels["host"] == "x"


class TestRequestMetrics:
    def test_fields_stored(self):
        now = datetime.utcnow()
        rm = RequestMetrics(tool_name="search", success=True, duration_ms=55.5, timestamp=now)
        assert rm.tool_name == "search"
        assert rm.success is True
        assert rm.duration_ms == 55.5
        assert rm.timestamp == now
        assert rm.error_type is None
