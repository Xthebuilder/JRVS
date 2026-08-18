"""
Post-execution verification for JARVIS write actions.

A tool's return value is not evidence. nextcloud_create once returned a
complete event dict — real UUID, real html_link, no error field — for an event
it had filed under 18 July 2024 instead of tomorrow, and nothing in the agent
noticed. The only thing that catches that is going back to the system and
reading the record again.

Each verifier answers one question: does the thing the user asked for now
exist, in the state they asked for? Verifiers return (ok, detail); detail is
fed back into the replan so a failure says what was wrong, not just that
something was.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

# Verification outcomes.
VERIFIED   = "verified"    # read back and matched
FAILED     = "failed"      # read back and did NOT match — the action did not take
UNVERIFIED = "unverified"  # no verifier exists for this tool; nothing was proven


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _same_instant(a: Any, b: Any) -> bool:
    """Compare two datetime-ish values, tolerating tz/format differences."""
    from datetime import datetime
    def parse(v):
        if isinstance(v, datetime):
            return v
        text = str(v or "").strip().replace("Z", "+00:00")
        for cut in (text, text[:19]):
            try:
                return datetime.fromisoformat(cut)
            except ValueError:
                continue
        return None
    da, db = parse(a), parse(b)
    if da is None or db is None:
        return False
    # A naive value is local wall-clock time — the planner writes "18:00" while
    # CalDAV stores "01:00Z". Those are the same instant, so naive values get
    # the local zone attached before comparing rather than being compared raw.
    local = datetime.now().astimezone().tzinfo
    if da.tzinfo is None:
        da = da.replace(tzinfo=local)
    if db.tzinfo is None:
        db = db.replace(tzinfo=local)
    return abs((da - db).total_seconds()) < 60


async def _verify_nextcloud_create(args: dict, result: Any) -> tuple[bool, str]:
    """Fetch the event back by id and confirm summary and start time match."""
    if not isinstance(result, dict) or not result.get("id"):
        return False, "create returned no event id"
    from jrvs.nextcloud.caldav_client import CalDAVClient
    import asyncio
    client = CalDAVClient()
    event = await asyncio.get_event_loop().run_in_executor(
        None, lambda: client.get_event(result["id"])
    )
    if not event:
        return False, f"event {result['id']} is not on the calendar after create"

    want_summary = _norm(args.get("summary"))
    got_summary = _norm(event.get("summary"))
    if want_summary and want_summary != got_summary:
        return False, f"summary is {got_summary!r}, expected {want_summary!r}"

    want_start = args.get("start")
    if want_start and not _same_instant(want_start, event.get("start")):
        return False, (
            f"start is {event.get('start')!r}, expected {want_start!r} — "
            "the event exists but not at the requested time"
        )
    return True, "event found on the calendar with matching summary and start"


async def _verify_nextcloud_delete(args: dict, result: Any) -> tuple[bool, str]:
    """Confirm the event is actually gone."""
    from jrvs.nextcloud.caldav_client import CalDAVClient
    import asyncio
    event_id = args.get("event_id", "")
    if not event_id:
        return False, "no event_id supplied"
    client = CalDAVClient()
    event = await asyncio.get_event_loop().run_in_executor(
        None, lambda: client.get_event(event_id)
    )
    return (event is None), ("event is gone" if event is None else "event still exists after delete")


async def _verify_file_write(args: dict, result: Any) -> tuple[bool, str]:
    """Read the file back and compare its contents to what was requested."""
    from agent.tools import _sandbox_path
    from pathlib import Path
    name = args.get("filename") or (Path(args.get("path", "")).name if args.get("path") else "")
    if not name:
        return False, "no filename supplied"
    fpath = _sandbox_path(name)
    if not fpath.exists():
        return False, f"{fpath} does not exist after write"
    written = fpath.read_text(encoding="utf-8")
    expected = args.get("content", "")
    if expected and written != expected:
        return False, f"file contents differ from what was requested ({len(written)}B on disk)"
    if not written.strip():
        return False, f"{fpath} is empty after write"
    return True, f"{fpath} contains {len(written)} bytes as requested"


async def _verify_gmail_send(args: dict, result: Any) -> tuple[bool, str]:
    """Confirm the message shows up in Sent."""
    from agent.tools import gmail_search
    to_addr = args.get("to", "")
    subject = args.get("subject", "")
    hits = await gmail_search(query=f"in:sent to:{to_addr} subject:{subject[:30]}", max_results=1)
    return (bool(hits), "found in Sent" if hits else "no matching message in Sent")


# tool name -> verifier. A tool absent from this map is UNVERIFIED, never
# assumed successful.
VERIFIERS: dict[str, Callable[[dict, Any], Awaitable[tuple[bool, str]]]] = {
    "nextcloud_create": _verify_nextcloud_create,
    "nextcloud_delete": _verify_nextcloud_delete,
    "file_write":       _verify_file_write,
    "gmail_send":       _verify_gmail_send,
}


async def verify_action(tool: str, args: dict, result: Any) -> tuple[str, str]:
    """
    Check that *tool* actually took effect. Returns (status, detail).

    A verification error is NOT success. The old code returned True whenever a
    check raised, so a broken verifier silently rubber-stamped every action —
    exactly the failure mode verification exists to prevent. An error means the
    outcome is unknown, and unknown is reported as unknown.
    """
    verifier = VERIFIERS.get(tool)
    if verifier is None:
        return UNVERIFIED, f"no verifier for {tool}"
    try:
        ok, detail = await verifier(args, result)
    except Exception as exc:
        log.warning("verify_action: %s verifier raised: %s", tool, exc)
        return FAILED, f"verification of {tool} could not be completed: {exc}"
    return (VERIFIED if ok else FAILED), detail
