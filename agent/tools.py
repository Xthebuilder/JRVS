"""
JARVIS built-in tool implementations.

Importing this module registers all tools into tool_registry.
Google API calls are synchronous (google-api-python-client), so each
tool wraps them in run_in_executor to avoid blocking the event loop.

Tools are grouped by tier:
  AUTO    — read-only, safe to run silently
  NOTIFY  — writes/creates, owner notified after execution
  CONFIRM — irreversible (send email, delete event), needs Slack approval
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path
from typing import Any, Optional

from agent.tool_registry import jarvis_tool, AUTO, NOTIFY, CONFIRM

log = logging.getLogger(__name__)

_loop_executor = None


def _run_sync(fn, *args, **kwargs) -> Any:
    """Run a synchronous Google API call in a thread pool."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, partial(fn, *args, **kwargs))


# ── Gmail (AUTO) ──────────────────────────────────────────────────────────────

@jarvis_tool(name="gmail_list", tier=AUTO, desc="List recent inbox emails")
async def gmail_list(max_results: int = 10, label: str = "INBOX", query: str = "") -> list:
    from jrvs.google.gmail_client import GmailClient
    client = GmailClient()
    return await _run_sync(client.list_messages, max_results=max_results, label=label, query=query)


@jarvis_tool(name="gmail_search", tier=AUTO, desc="Search Gmail with query syntax")
async def gmail_search(query: str, max_results: int = 10) -> list:
    from jrvs.google.gmail_client import GmailClient
    client = GmailClient()
    return await _run_sync(client.search_messages, query=query, max_results=max_results)


@jarvis_tool(name="gmail_read", tier=AUTO, desc="Read full email body by ID")
async def gmail_read(message_id: str = "", message_ids: str = "") -> dict:
    from jrvs.google.gmail_client import GmailClient
    client = GmailClient()
    return await _run_sync(client.read_message, message_id or message_ids)


@jarvis_tool(name="gmail_labels", tier=AUTO, desc="List all Gmail labels")
async def gmail_labels() -> list:
    from jrvs.google.gmail_client import GmailClient
    client = GmailClient()
    return await _run_sync(client.list_labels)


# ── Google Docs (AUTO reads) ──────────────────────────────────────────────────

@jarvis_tool(name="docs_list", tier=AUTO, desc="List recent Google Docs")
async def docs_list(max_results: int = 10) -> list:
    from jrvs.google.docs_client import DocsClient
    client = DocsClient()
    return await _run_sync(client.list_documents, max_results=max_results)


@jarvis_tool(name="docs_read", tier=AUTO, desc="Read a Google Doc by ID")
async def docs_read(document_id: str) -> dict:
    from jrvs.google.docs_client import DocsClient
    client = DocsClient()
    return await _run_sync(client.read_document, document_id)


@jarvis_tool(name="docs_find", tier=AUTO, desc="Find a Google Doc by name")
async def docs_find(name: str = "", query: str = "", title: str = "") -> dict:
    from jrvs.google.docs_client import DocsClient
    client = DocsClient()
    return await _run_sync(client.find_document_by_name, name or query or title)


# ── Google Sheets (AUTO reads) ────────────────────────────────────────────────

@jarvis_tool(name="sheets_list", tier=AUTO, desc="List recent Google Sheets")
async def sheets_list(max_results: int = 10) -> list:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.list_spreadsheets, max_results=max_results)


@jarvis_tool(name="sheets_read", tier=AUTO, desc="Read cells from a spreadsheet range")
async def sheets_read(spreadsheet_id: str, range_: str = "Sheet1") -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.read_sheet, spreadsheet_id, range_)


@jarvis_tool(name="sheets_find", tier=AUTO, desc="Find a spreadsheet by name")
async def sheets_find(name: str = "", query: str = "") -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.find_spreadsheet_by_name, name or query)


@jarvis_tool(name="sheets_info", tier=AUTO, desc="Get spreadsheet metadata and sheet names")
async def sheets_info(spreadsheet_id: str) -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.get_spreadsheet_info, spreadsheet_id)


# ── Google Calendar (AUTO reads) ──────────────────────────────────────────────

@jarvis_tool(name="calendar_list_calendars", tier=AUTO, desc="List all Google Calendars")
async def calendar_list_calendars() -> list:
    from jrvs.google.calendar_client import CalendarClient
    client = CalendarClient()
    return await _run_sync(client.list_calendars)


@jarvis_tool(name="calendar_events", tier=AUTO, desc="List upcoming calendar events")
async def calendar_events(max_results: int = 20, calendar_id: str = "primary") -> list:
    from jrvs.google.calendar_client import CalendarClient
    client = CalendarClient()
    return await _run_sync(client.list_events, max_results=max_results, calendar_id=calendar_id)


@jarvis_tool(name="calendar_find", tier=AUTO, desc="Search calendar events by keyword")
async def calendar_find(query: str, max_results: int = 10) -> list:
    from jrvs.google.calendar_client import CalendarClient
    client = CalendarClient()
    return await _run_sync(client.find_events, query=query, max_results=max_results)


# ── Web search (AUTO) ─────────────────────────────────────────────────────────

@jarvis_tool(name="web_search", tier=AUTO, desc="Search the web using Brave Search")
async def web_search(query: str, max_results: int = 5) -> list:
    try:
        from scraper.brave_search import BraveSearchClient
        client = BraveSearchClient()
        return await client.search(query)
    except Exception as exc:
        log.warning("web_search: Brave unavailable (%s), falling back to DDG", exc)
        try:
            from ddgs import DDGS
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, lambda: list(DDGS().text(query, max_results=max_results))
            )
            return results
        except Exception as exc2:
            return [{"error": f"web_search unavailable: {exc2}"}]


# ── Local file sandbox (AUTO reads / NOTIFY writes) ──────────────────────────

_SANDBOX = Path.home() / "jarvis_sandbox"


def _sandbox_path(filename: str) -> Path:
    """Resolve filename inside sandbox, blocking path traversal."""
    safe = (_SANDBOX / Path(filename).name).resolve()
    if not str(safe).startswith(str(_SANDBOX.resolve())):
        raise ValueError(f"Path traversal blocked: {filename}")
    return safe


@jarvis_tool(name="file_read", tier=AUTO, desc="Read a file from the JARVIS sandbox (~/ jarvis_sandbox/)")
async def file_read(filename: str = "", path: str = "") -> str:
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    name = filename or (Path(path).name if path else "")
    if not name:
        return "filename is required"
    fpath = _sandbox_path(name)
    if not fpath.exists():
        return f"File not found: {name}"
    return fpath.read_text(encoding="utf-8")


@jarvis_tool(name="file_write", tier=NOTIFY, desc="Write or overwrite a file in the JARVIS sandbox (~/ jarvis_sandbox/)")
async def file_write(filename: str = "", path: str = "", content: str = "") -> dict:
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    name = filename or (Path(path).name if path else "")
    if not name:
        return {"error": "filename is required"}
    fpath = _sandbox_path(name)
    fpath.write_text(content, encoding="utf-8")
    return {"written": str(fpath), "bytes": len(content.encode())}


@jarvis_tool(name="file_list", tier=AUTO, desc="List files in the JARVIS sandbox")
async def file_list() -> list:
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    return [f.name for f in sorted(_SANDBOX.iterdir()) if f.is_file()]


# ── YouTube analytics (AUTO) ─────────────────────────────────────────────────

@jarvis_tool(name="youtube_analyze", tier=AUTO, desc="Analyse a YouTube channel's performance")
async def youtube_analyze(channel_id: str) -> dict:
    try:
        from jrvs.analytics.channel import ChannelAnalytics
        return await _run_sync(ChannelAnalytics().analyse, channel_id)
    except ImportError:
        return {"error": "YouTube analytics module not available"}


@jarvis_tool(name="youtube_outliers", tier=AUTO, desc="Find viral outlier videos for a channel")
async def youtube_outliers(channel_id: str) -> list:
    try:
        from jrvs.analytics.outliers import OutlierDetector
        return await _run_sync(OutlierDetector().detect, channel_id)
    except ImportError:
        return {"error": "YouTube analytics module not available"}


@jarvis_tool(name="youtube_growth", tier=AUTO, desc="Get growth trend for a YouTube channel")
async def youtube_growth(channel_id: str) -> dict:
    try:
        from jrvs.analytics.timeseries import TimeSeriesAnalyzer
        return await _run_sync(TimeSeriesAnalyzer().growth, channel_id)
    except ImportError:
        return {"error": "YouTube analytics module not available"}


# ── Google Docs (NOTIFY writes) ───────────────────────────────────────────────

@jarvis_tool(name="docs_create", tier=NOTIFY, desc="Create a new Google Doc")
async def docs_create(title: str, content: str = "") -> dict:
    from jrvs.google.docs_client import DocsClient
    client = DocsClient()
    return await _run_sync(client.create_document, title=title, content=content)


@jarvis_tool(name="docs_append", tier=NOTIFY, desc="Append text to a Google Doc")
async def docs_append(document_id: str, content: str) -> dict:
    from jrvs.google.docs_client import DocsClient
    client = DocsClient()
    return await _run_sync(client.append_text, document_id=document_id, text=content)


@jarvis_tool(name="docs_replace", tier=NOTIFY, desc="Find-and-replace text in a Google Doc")
async def docs_replace(document_id: str, find: str, replace: str) -> dict:
    from jrvs.google.docs_client import DocsClient
    client = DocsClient()
    return await _run_sync(client.replace_text, document_id=document_id, old=find, new=replace)


# ── Google Sheets (NOTIFY writes) ────────────────────────────────────────────

@jarvis_tool(name="sheets_write", tier=NOTIFY, desc="Write values to a spreadsheet range")
async def sheets_write(spreadsheet_id: str, range_: str, values: list) -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.write_range, spreadsheet_id, range_, values)


@jarvis_tool(name="sheets_append", tier=NOTIFY, desc="Append rows to a spreadsheet")
async def sheets_append(spreadsheet_id: str, values: list, sheet: str = "Sheet1") -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.append_rows, spreadsheet_id, values, sheet)


@jarvis_tool(name="sheets_create", tier=NOTIFY, desc="Create a new Google Sheets spreadsheet")
async def sheets_create(title: str) -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.create_spreadsheet, title)


@jarvis_tool(name="sheets_clear", tier=NOTIFY, desc="Clear a spreadsheet range")
async def sheets_clear(spreadsheet_id: str, range_: str) -> dict:
    from jrvs.google.sheets_client import SheetsClient
    client = SheetsClient()
    return await _run_sync(client.clear_range, spreadsheet_id, range_)


# ── Google Calendar (NOTIFY writes) ──────────────────────────────────────────

@jarvis_tool(name="calendar_create", tier=NOTIFY, desc="Create a calendar event")
async def calendar_create(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> dict:
    from jrvs.google.calendar_client import CalendarClient
    client = CalendarClient()
    return await _run_sync(
        client.create_event,
        summary=summary, start=start, end=end,
        description=description, location=location,
        calendar_id=calendar_id,
    )


@jarvis_tool(name="calendar_update", tier=NOTIFY, desc="Update an existing calendar event")
async def calendar_update(event_id: str, calendar_id: str = "primary", **fields) -> dict:
    from jrvs.google.calendar_client import CalendarClient
    client = CalendarClient()
    return await _run_sync(client.update_event, event_id=event_id, calendar_id=calendar_id, **fields)


# ── Gmail (CONFIRM sends) ─────────────────────────────────────────────────────

@jarvis_tool(name="gmail_send", tier=CONFIRM, desc="Send an email")
async def gmail_send(to: str, subject: str, body: str) -> dict:
    from jrvs.google.gmail_client import GmailClient
    client = GmailClient()
    return await _run_sync(client.send_message, to=to, subject=subject, body=body)


@jarvis_tool(name="gmail_reply", tier=CONFIRM, desc="Reply to an email thread")
async def gmail_reply(message_id: str, body: str) -> dict:
    from jrvs.google.gmail_client import GmailClient
    client = GmailClient()
    return await _run_sync(client.reply_to_message, message_id=message_id, body=body)


# ── Google Calendar (CONFIRM delete) ─────────────────────────────────────────

@jarvis_tool(name="calendar_delete", tier=CONFIRM, desc="Permanently delete a calendar event")
async def calendar_delete(event_id: str, calendar_id: str = "primary") -> dict:
    from jrvs.google.calendar_client import CalendarClient
    client = CalendarClient()
    return await _run_sync(client.delete_event, event_id=event_id, calendar_id=calendar_id)
