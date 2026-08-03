"""
JARVIS dependency-frontier batch scheduling.

Shared by AgentLoop (tool-step execution) and LeadAgent (subtask dispatch,
agent/lead.py) — both run independent units of work concurrently while
respecting a depends_on ordering, in batches bounded by a max-parallelism
limit. This is the same "find everything ready to run next" computation in
both places; only what happens to a batch afterward (execute a tool call vs.
dispatch a sub-agent, replan on failure, etc.) differs, so that part stays
owned by each caller rather than being folded into this helper.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence


def next_ready_batch(
    items: Sequence[Any],
    deps_fn: Callable[[Any], list],
    done_keys,
    max_parallel: int,
) -> Optional[list]:
    """
    Return the next batch (up to max_parallel items) of `items` whose
    dependencies (per deps_fn) are all present in done_keys, or None if no
    item is currently ready (a dependency deadlock — callers should treat
    this as an error condition, not retry it).

    done_keys is any container supporting `in` (typically a dict populated
    with completed items' results) — this function only computes readiness
    from a snapshot of it; the caller owns marking items done between calls.
    """
    ready = [it for it in items if all(dep in done_keys for dep in deps_fn(it))]
    if not ready:
        return None
    return ready[:max_parallel]
