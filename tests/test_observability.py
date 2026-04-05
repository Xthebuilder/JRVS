"""
Unit tests for the observability system — Tracer, trace_span, ResourceMonitor.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.observability import (
    Tracer,
    TraceEvent,
    ResourceMonitor,
    trace_span,
)


class TestTraceEvent:
    def test_to_dict_strips_none(self):
        ev = TraceEvent(trace_id="t1", category="rag", operation="search", status="started")
        d = ev.to_dict()
        assert "trace_id" in d
        assert "error" not in d  # None → stripped
        assert d["category"] == "rag"

    def test_to_dict_includes_error_when_present(self):
        ev = TraceEvent(trace_id="t1", category="llm", operation="gen", error="boom")
        d = ev.to_dict()
        assert d["error"] == "boom"


class TestTracer:
    def setup_method(self):
        self.tracer = Tracer(max_events=100, max_traces=10)

    def test_start_trace_returns_id(self):
        tid = self.tracer.start_trace("test_label")
        assert tid
        assert len(tid) == 12  # uuid4()[:12]

    def test_emit_stores_event(self):
        tid = self.tracer.start_trace("test")
        eid = self.tracer.emit(tid, "rag", "search", metadata={"query": "hello"})
        assert eid
        events = self.tracer.get_trace(tid)
        ops = [e["operation"] for e in events]
        assert "search" in ops

    def test_get_recent(self):
        tid = self.tracer.start_trace("test")
        for i in range(5):
            self.tracer.emit(tid, "llm", f"gen_{i}")
        recent = self.tracer.get_recent(limit=3)
        assert len(recent) == 3

    def test_eviction_of_old_traces(self):
        # max_traces=10 → 11th should evict the 1st
        tids = [self.tracer.start_trace(f"t{i}") for i in range(11)]
        assert tids[0] not in self.tracer._active_traces

    def test_subscribe_unsubscribe(self):
        q = self.tracer.subscribe()
        assert q in self.tracer._listeners
        self.tracer.unsubscribe(q)
        assert q not in self.tracer._listeners

    def test_unsubscribe_nonexistent_is_safe(self):
        import asyncio
        q = asyncio.Queue()
        self.tracer.unsubscribe(q)  # Should not raise


class TestTraceSpan:
    def test_span_emits_start_and_complete(self):
        t = Tracer(max_events=50, max_traces=10)
        # Monkeypatch singleton for this test
        import core.observability as obs
        original = obs.tracer
        obs.tracer = t
        try:
            tid = t.start_trace("span_test")
            with trace_span(tid, "rag", "retrieve") as span:
                span.metadata["chunks"] = 5
                time.sleep(0.01)

            events = t.get_trace(tid)
            statuses = [e["status"] for e in events if e["operation"] == "retrieve"]
            assert "started" in statuses
            assert "completed" in statuses

            completed = [e for e in events if e["operation"] == "retrieve" and e["status"] == "completed"][0]
            assert completed["duration_ms"] >= 5  # at least ~10ms
            assert completed["metadata"]["chunks"] == 5
        finally:
            obs.tracer = original

    def test_span_records_error(self):
        t = Tracer(max_events=50, max_traces=10)
        import core.observability as obs
        original = obs.tracer
        obs.tracer = t
        try:
            tid = t.start_trace("err_test")
            with pytest.raises(ValueError):
                with trace_span(tid, "llm", "generate"):
                    raise ValueError("model not ready")

            events = t.get_trace(tid)
            err_events = [e for e in events if e.get("error")]
            assert len(err_events) == 1
            assert "model not ready" in err_events[0]["error"]
        finally:
            obs.tracer = original


class TestResourceMonitor:
    def test_snapshot_returns_expected_keys(self):
        snap = ResourceMonitor.snapshot()
        assert "timestamp" in snap
        assert "device_class" in snap
        # CPU/memory/disk should be present (may have "error" if psutil missing)
        assert "cpu" in snap
        assert "memory" in snap
        assert "disk" in snap

    def test_snapshot_cpu_has_percent(self):
        snap = ResourceMonitor.snapshot()
        if "error" not in snap["cpu"]:
            assert "percent" in snap["cpu"]
            assert "cores" in snap["cpu"]
