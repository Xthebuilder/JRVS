"""
Cross-run learning — what previous goals got wrong.

Nothing survived a run. goal_state.context_json is keyed on goal_id, and every
ad-hoc Slack request gets a fresh adhoc_<uuid>, so it was dead for exactly the
requests users actually make. The agent would rediscover that file_read takes
'filename' and not 'file_path' forever.

Lessons are recorded when a step fails on its arguments or a goal is audited as
unfulfilled, then the most frequent ones are injected into the planner prompt.
Storage is a small JSON file rather than a table so it survives schema churn and
is trivial to inspect or wipe by hand.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_LESSONS = 200
_PROMPT_LIMIT = 8


def _store_path() -> Path:
    override = os.environ.get("JRVS_LESSONS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "data" / "lessons.json"


def _load() -> list[dict]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("lessons: could not read %s (%s) — starting empty", path, exc)
        return []


def _save(items: list[dict]) -> None:
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-_MAX_LESSONS:], indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("lessons: could not write %s: %s", path, exc)


def record(kind: str, subject: str, lesson: str) -> None:
    """
    Record one lesson. Identical lessons are counted, not duplicated, so the
    prompt shows what actually keeps happening rather than the most recent noise.
    """
    lesson = (lesson or "").strip()
    if not lesson:
        return
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("kind") == kind and item.get("subject") == subject and item.get("lesson") == lesson:
                item["count"] = int(item.get("count", 1)) + 1
                item["last_seen"] = time.time()
                _save(items)
                return
        items.append({
            "kind": kind, "subject": subject, "lesson": lesson,
            "count": 1, "last_seen": time.time(),
        })
        _save(items)


def record_tool_error(tool: str, error: str) -> None:
    """Remember an argument-shape mistake so the next plan does not repeat it."""
    text = (error or "").strip()
    # Only argument-shape errors generalise. A network blip or a missing file is
    # about that moment, not about how the tool must be called.
    markers = ("unexpected argument", "missing required argument",
               "unresolved step placeholder", "is required", "is empty")
    if not any(m in text.lower() for m in markers):
        return
    record("tool_args", tool, f"{tool}: {text[:200]}")


def record_goal_gap(request: str, missing: str) -> None:
    """Remember a goal that ran but did not fulfil what was asked."""
    if not (missing or "").strip():
        return
    record("goal_gap", (request or "")[:80], missing.strip()[:200])


def format_for_prompt(limit: int = _PROMPT_LIMIT) -> str:
    """Render the most frequent lessons for the planner prompt."""
    items = _load()
    if not items:
        return ""
    ranked = sorted(items, key=lambda i: (int(i.get("count", 1)), i.get("last_seen", 0)), reverse=True)
    lines = ["LEARNED FROM PREVIOUS RUNS — do not repeat these mistakes:"]
    for item in ranked[:limit]:
        seen = int(item.get("count", 1))
        suffix = f"  (seen {seen}x)" if seen > 1 else ""
        lines.append(f"  - {item.get('lesson')}{suffix}")
    return "\n".join(lines)


def clear() -> None:
    """Wipe stored lessons (test helper / manual reset)."""
    with _LOCK:
        _save([])
