"""
Pre-flight state checks — look before you write.

The agent mutated the world without ever reading it first. One goal created
three calendar events without noticing it had already created one, and because
a failed step is retried, "create an event" could run twice and leave two
events behind. Retry logic without idempotency is actively destructive.

A precheck runs immediately before a write tool and answers: does the thing the
user is asking for already exist? If it does, the write is skipped and the
existing record is returned, so running a goal twice converges on one record
instead of two.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


async def _precheck_nextcloud_create(args: dict) -> Optional[dict]:
    """Return an existing event with the same summary at the same time, if any."""
    from jrvs.nextcloud.caldav_client import CalDAVClient
    from agent.verification import _same_instant

    summary = _norm(args.get("summary"))
    start = args.get("start")
    if not summary:
        return None

    client = CalDAVClient()
    matches = await asyncio.get_event_loop().run_in_executor(
        None, lambda: client.find_events(str(args.get("summary") or ""))
    )
    for event in (matches or []):
        if _norm(event.get("summary")) != summary:
            continue
        # Same title on the same day/time is the duplicate we care about.
        if start and not _same_instant(start, event.get("start")):
            continue
        return event
    return None


async def _precheck_file_write(args: dict) -> Optional[dict]:
    """Return the existing file only when its contents already match."""
    from pathlib import Path
    from agent.tools import _sandbox_path

    name = args.get("filename") or (Path(args.get("path", "")).name if args.get("path") else "")
    if not name:
        return None
    fpath = _sandbox_path(name)
    if not fpath.exists():
        return None
    current = fpath.read_text(encoding="utf-8")
    wanted = args.get("content", "")
    # Different content is a legitimate overwrite, not a duplicate.
    if wanted and current == wanted:
        return {"written": str(fpath), "bytes": len(current.encode()), "already_present": True}
    return None


PRECHECKS: dict[str, Callable[[dict], Awaitable[Optional[dict]]]] = {
    "nextcloud_create": _precheck_nextcloud_create,
    "file_write": _precheck_file_write,
}


async def find_existing(tool: str, args: dict) -> Optional[dict]:
    """
    Return an existing record equivalent to what *tool* would create, or None.

    A precheck failure is never allowed to block the write — the cost of a
    missed duplicate is far lower than refusing to act at all.
    """
    check = PRECHECKS.get(tool)
    if check is None:
        return None
    try:
        return await check(args)
    except Exception as exc:
        log.warning("prechecks: %s precheck failed (%s) — proceeding with the write", tool, exc)
        return None
