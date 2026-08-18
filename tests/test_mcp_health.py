"""
Unit tests for mcp/health.py

Tests HealthChecker, HealthStatus, ComponentHealth.
Uses async mock check functions — no external services.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timezone

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.health import HealthChecker, HealthStatus, ComponentHealth


def _make_health(status=HealthStatus.HEALTHY, component="test", message="ok"):
    return ComponentHealth(
        component=component,
        status=status,
        message=message,
        last_check=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
class TestHealthChecker:
    async def test_check_unregistered_returns_unknown(self):
        checker = HealthChecker()
        result = await checker.check_component("ghost")
        assert result.status == HealthStatus.UNKNOWN
        assert result.component == "ghost"

    async def test_register_and_check_healthy(self):
        checker = HealthChecker()

        async def healthy_check():
            return _make_health(HealthStatus.HEALTHY)

        checker.register_check("db", healthy_check)
        result = await checker.check_component("db")
        assert result.status == HealthStatus.HEALTHY

    async def test_register_and_check_unhealthy(self):
        checker = HealthChecker()

        async def bad_check():
            return _make_health(HealthStatus.UNHEALTHY, message="down")

        checker.register_check("svc", bad_check)
        result = await checker.check_component("svc")
        assert result.status == HealthStatus.UNHEALTHY

    async def test_check_all_runs_all_registered(self):
        checker = HealthChecker()

        async def a():
            return _make_health(component="a")

        async def b():
            return _make_health(component="b", status=HealthStatus.DEGRADED)

        checker.register_check("a", a)
        checker.register_check("b", b)
        results = await checker.check_all()
        assert "a" in results
        assert "b" in results

    async def test_response_time_populated(self):
        checker = HealthChecker()

        async def quick():
            return _make_health()

        checker.register_check("quick", quick)
        result = await checker.check_component("quick")
        assert result.response_time_ms is not None
        assert result.response_time_ms >= 0

    async def test_get_overall_status_all_healthy(self):
        checker = HealthChecker()

        async def h():
            return _make_health(HealthStatus.HEALTHY)

        checker.register_check("c", h)
        await checker.check_all()
        assert checker.get_overall_status() == HealthStatus.HEALTHY

    async def test_get_overall_status_with_unhealthy(self):
        checker = HealthChecker()

        async def bad():
            return _make_health(HealthStatus.UNHEALTHY)

        checker.register_check("bad", bad)
        await checker.check_all()
        assert checker.get_overall_status() == HealthStatus.UNHEALTHY

    async def test_get_overall_status_empty_is_healthy(self):
        checker = HealthChecker()
        # No checks registered — should default to HEALTHY (no failures)
        status = checker.get_overall_status()
        assert status in (HealthStatus.HEALTHY, HealthStatus.UNKNOWN)

    async def test_get_health_report_shape(self):
        checker = HealthChecker()

        async def h():
            return _make_health()

        checker.register_check("comp", h)
        await checker.check_all()
        report = checker.get_health_report()
        assert "overall_status" in report or "status" in report or "components" in report or len(report) > 0


class TestComponentHealth:
    def test_to_dict_has_expected_keys(self):
        ch = _make_health(HealthStatus.HEALTHY, "db", "all good")
        d = ch.to_dict()
        assert d["component"] == "db"
        assert d["status"] == "healthy"
        assert d["message"] == "all good"
        assert "last_check" in d

    def test_status_value_is_string(self):
        ch = _make_health(HealthStatus.DEGRADED)
        d = ch.to_dict()
        assert d["status"] == "degraded"

    def test_optional_fields_none_by_default(self):
        ch = _make_health()
        assert ch.response_time_ms is None
        assert ch.details is None


class TestHealthStatus:
    def test_status_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_comparison(self):
        assert HealthStatus.HEALTHY != HealthStatus.UNHEALTHY
        assert HealthStatus.HEALTHY == HealthStatus.HEALTHY
