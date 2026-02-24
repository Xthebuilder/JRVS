"""
JRVS Google Agent — LLM-powered router for Google Workspace APIs.

Flow for every user request
─────────────────────────────
1. The user's natural-language request is embedded (sentence-transformer).
2. The tool list is also embedded; cosine similarity gives a *semantic hint*.
3. The Ollama LLM is sent:
     • the full tool catalogue
     • the semantic hint (top-3 candidate tools)
     • the user request
   and is instructed to reply with a JSON tool call.
4. The JSON is parsed, the appropriate client is instantiated, and the
   API call is executed.
5. The raw result is fed back to the LLM with the original request for a
   polished natural-language answer.

This means even vague requests like "what did my boss send me?"
are correctly routed to gmail.search and the answer is human-readable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from jrvs.config import Config

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tool registry — what JRVS can do with Google APIs
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    # ── Gmail ────────────────────────────────────────────────────────────
    {
        "name": "gmail_list",
        "service": "gmail",
        "description": "List recent emails in the inbox. Returns sender, subject, date, snippet.",
        "params": {"max_results": "int (optional)", "label": "str (optional, default INBOX)", "query": "str (optional Gmail filter)"},
    },
    {
        "name": "gmail_read",
        "service": "gmail",
        "description": "Read the full body of a specific email by its message ID.",
        "params": {"message_id": "str (required)"},
    },
    {
        "name": "gmail_search",
        "service": "gmail",
        "description": "Search emails using Gmail query syntax (from:, subject:, after:, before:, has:attachment, etc.).",
        "params": {"query": "str (required)", "max_results": "int (optional)"},
    },
    {
        "name": "gmail_send",
        "service": "gmail",
        "description": "Compose and send a new email.",
        "params": {"to": "str (required)", "subject": "str (required)", "body": "str (required)"},
    },
    {
        "name": "gmail_reply",
        "service": "gmail",
        "description": "Reply to an existing email thread.",
        "params": {"message_id": "str (required)", "body": "str (required)"},
    },
    {
        "name": "gmail_labels",
        "service": "gmail",
        "description": "List all Gmail labels/folders.",
        "params": {},
    },
    # ── Google Docs ──────────────────────────────────────────────────────
    {
        "name": "docs_list",
        "service": "docs",
        "description": "List recent Google Docs documents.",
        "params": {"max_results": "int (optional)"},
    },
    {
        "name": "docs_read",
        "service": "docs",
        "description": "Read the full text content of a Google Doc by its ID.",
        "params": {"document_id": "str (required)"},
    },
    {
        "name": "docs_find",
        "service": "docs",
        "description": "Find a Google Doc by name (partial match) and read its content.",
        "params": {"name": "str (required)"},
    },
    {
        "name": "docs_create",
        "service": "docs",
        "description": "Create a new Google Doc with a title and optional initial content.",
        "params": {"title": "str (required)", "content": "str (optional)"},
    },
    {
        "name": "docs_append",
        "service": "docs",
        "description": "Append text to an existing Google Doc.",
        "params": {"document_id": "str (required)", "text": "str (required)"},
    },
    {
        "name": "docs_replace",
        "service": "docs",
        "description": "Find and replace text inside a Google Doc.",
        "params": {"document_id": "str (required)", "find": "str (required)", "replace_with": "str (required)"},
    },
    # ── Google Sheets ────────────────────────────────────────────────────
    {
        "name": "sheets_list",
        "service": "sheets",
        "description": "List recent Google Sheets spreadsheets.",
        "params": {"max_results": "int (optional)"},
    },
    {
        "name": "sheets_read",
        "service": "sheets",
        "description": "Read cell values from a spreadsheet range (e.g. 'Sheet1!A1:D10').",
        "params": {"spreadsheet_id": "str (required)", "range": "str (optional, default Sheet1)"},
    },
    {
        "name": "sheets_find",
        "service": "sheets",
        "description": "Find a spreadsheet by name (partial match).",
        "params": {"name": "str (required)"},
    },
    {
        "name": "sheets_write",
        "service": "sheets",
        "description": "Write a 2-D list of values to a specific range in a spreadsheet.",
        "params": {"spreadsheet_id": "str (required)", "range": "str (required)", "values": "list[list] (required)"},
    },
    {
        "name": "sheets_append",
        "service": "sheets",
        "description": "Append rows of data to the end of a sheet.",
        "params": {"spreadsheet_id": "str (required)", "range": "str (required)", "values": "list[list] (required)"},
    },
    {
        "name": "sheets_create",
        "service": "sheets",
        "description": "Create a new Google Sheets spreadsheet.",
        "params": {"title": "str (required)", "sheet_names": "list[str] (optional)"},
    },
    {
        "name": "sheets_info",
        "service": "sheets",
        "description": "Get metadata about a spreadsheet: title, sheet names, row/column counts.",
        "params": {"spreadsheet_id": "str (required)"},
    },
    {
        "name": "sheets_clear",
        "service": "sheets",
        "description": "Clear all values in a range of a spreadsheet.",
        "params": {"spreadsheet_id": "str (required)", "range": "str (required)"},
    },
    # ── Google Calendar ──────────────────────────────────────────────────
    {
        "name": "calendar_list_calendars",
        "service": "calendar",
        "description": "List all Google Calendars on this account (primary, work, birthdays, etc.).",
        "params": {},
    },
    {
        "name": "calendar_events",
        "service": "calendar",
        "description": "List upcoming calendar events. Can filter by date range.",
        "params": {
            "calendar_id":  "str (optional, default 'primary')",
            "max_results":  "int (optional)",
            "time_min":     "ISO datetime str (optional, default now)",
            "time_max":     "ISO datetime str (optional)",
        },
    },
    {
        "name": "calendar_find",
        "service": "calendar",
        "description": "Search calendar events by keyword (title, description, location, attendees).",
        "params": {"query": "str (required)", "calendar_id": "str (optional)", "max_results": "int (optional)"},
    },
    {
        "name": "calendar_create",
        "service": "calendar",
        "description": "Create a new calendar event with title, start/end times, optional description, location, and attendees.",
        "params": {
            "summary":     "str (required) — event title",
            "start":       "ISO datetime str (required) e.g. '2026-03-01T10:00:00'",
            "end":         "ISO datetime str (required)",
            "description": "str (optional)",
            "location":    "str (optional)",
            "attendees":   "list[str] of email addresses (optional)",
            "calendar_id": "str (optional)",
            "all_day":     "bool (optional) — use YYYY-MM-DD dates for all-day events",
        },
    },
    {
        "name": "calendar_delete",
        "service": "calendar",
        "description": "Delete a calendar event by its ID.",
        "params": {"event_id": "str (required)", "calendar_id": "str (optional)"},
    },
    {
        "name": "calendar_update",
        "service": "calendar",
        "description": "Update fields on an existing calendar event (summary, start, end, description, location).",
        "params": {
            "event_id":    "str (required)",
            "calendar_id": "str (optional)",
            "summary":     "str (optional)",
            "start":       "ISO datetime str (optional)",
            "end":         "ISO datetime str (optional)",
            "description": "str (optional)",
            "location":    "str (optional)",
        },
    },
]

_TOOL_INDEX: dict[str, dict] = {t["name"]: t for t in TOOLS}

_TOOL_CATALOGUE = "\n".join(
    f"{i+1}. {t['name']}: {t['description']}  params={t['params']}"
    for i, t in enumerate(TOOLS)
)

_ROUTING_SYSTEM = f"""You are JRVS, an AI assistant with access to Google Workspace APIs.

Available tools:
{_TOOL_CATALOGUE}

Rules:
- Reply with ONLY a JSON object: {{"tool": "<tool_name>", "args": {{...}}}}
- Fill in all required params from the user's request.
- For optional params, only include them if the user explicitly mentioned them.
- If you need to call multiple tools, return a JSON array.
- NEVER explain yourself. ONLY return JSON.
"""

_SYNTHESIS_SYSTEM = """You are JRVS, a helpful assistant.
You are given the user's original request and the raw data returned by Google APIs.
Summarise the data clearly and answer the user's question in natural language.
If the result is a list, present it as a clean formatted list.
If the result is document text, quote relevant parts.
Be concise and helpful.
"""


# ─────────────────────────────────────────────────────────────────────────────

class GoogleAgent:
    """LLM router + executor for Google Workspace operations."""

    def __init__(self, ollama=None, db=None) -> None:
        from jrvs.llm.ollama_client import OllamaClient
        self._llm = ollama or OllamaClient()
        self._encoder = None  # lazy-load

    # ── public API ────────────────────────────────────────────────────────

    def ask(self, request: str) -> tuple[str, list[dict[str, Any]]]:
        """Convenience: route → execute → synthesise in one call."""
        tool_calls = self.route(request)
        return self.execute_and_synthesise(request, tool_calls)

    def route(self, request: str) -> list[dict[str, Any]]:
        """Return the LLM-chosen tool calls (with args) WITHOUT executing them."""
        hint = self._semantic_hint(request, top_k=3)
        return self._route(request, hint)

    def execute_and_synthesise(
        self, request: str, tool_calls: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Execute a list of tool calls and produce a polished LLM answer."""
        executed: list[dict[str, Any]] = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            args      = call.get("args", {})
            result    = self._execute(tool_name, args)
            executed.append({"tool": tool_name, "args": args, "result": result})
        answer = self._synthesise(request, executed)
        return answer, executed

    def compose_email(self, request: str) -> dict[str, Any]:
        """Ask the LLM to draft a complete email (to/subject/body) from a request.

        Returns a dict with keys: to, subject, body.
        """
        system = (
            "You are an email drafting assistant. "
            "Given the user's instruction, produce a complete email draft as JSON with keys: "
            "\"to\" (str), \"subject\" (str), \"body\" (str). "
            "Write the body in a professional but friendly tone. "
            "ONLY return the JSON object — no explanation."
        )
        try:
            raw = self._llm.chat(messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": request},
            ])
            draft = _parse_json(raw)
            if isinstance(draft, dict) and "body" in draft:
                return draft
        except Exception as exc:  # noqa: BLE001
            log.warning("compose_email LLM call failed: %s", exc)
        # Fallback — pull args directly from route
        tool_calls = self.route(request)
        for tc in tool_calls:
            n = tc.get("tool", "")
            if isinstance(n, list): n = n[0]
            if n == "gmail_send":
                return tc.get("args", {})
        return {}

    def revise_email(
        self, original_request: str, draft: dict[str, Any], feedback: str
    ) -> dict[str, Any]:
        """Revise an email draft based on user feedback.

        Returns an updated dict with keys: to, subject, body.
        """
        system = (
            "You are an email drafting assistant. "
            "You are given an original request, an existing email draft, and user feedback. "
            "Revise the draft according to the feedback and return ONLY a JSON object "
            "with keys: \"to\", \"subject\", \"body\"."
        )
        user_msg = (
            f"Original request: {original_request}\n\n"
            f"Current draft:\nTo: {draft.get('to','')}\n"
            f"Subject: {draft.get('subject','')}\nBody:\n{draft.get('body','')}\n\n"
            f"Feedback: {feedback}\n\nRevise the email and return JSON."
        )
        try:
            raw = self._llm.chat(messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ])
            revised = _parse_json(raw)
            if isinstance(revised, dict) and "body" in revised:
                return revised
        except Exception as exc:  # noqa: BLE001
            log.warning("revise_email LLM call failed: %s", exc)
        return draft  # return unchanged if revision fails

    # ── LLM routing ──────────────────────────────────────────────────────

    def _route(self, request: str, hint: list[str]) -> list[dict[str, Any]]:
        """Ask the LLM to pick a tool and fill its arguments."""
        hint_str = f"\nSemantically closest tools (embedding hint): {', '.join(hint)}\n"
        user_msg = f"{hint_str}\nUser request: {request}"
        try:
            raw = self._llm.chat(
                messages=[
                    {"role": "system",  "content": _ROUTING_SYSTEM},
                    {"role": "user",    "content": user_msg},
                ]
            )
            parsed = _parse_json(raw)
            if isinstance(parsed, dict):
                parsed = [parsed]
            return parsed if isinstance(parsed, list) else []
        except Exception as exc:
            log.warning("LLM routing failed, falling back to semantic hint: %s", exc)
            # Fallback: pick the top semantic hint as an empty call
            if hint:
                return [{"tool": hint[0], "args": {}}]
            return []

    # ── Execution ─────────────────────────────────────────────────────────

    def _execute(self, tool_name: str | list, args: dict[str, Any]) -> Any:
        """Dispatch a tool call to the correct API client method."""
        # LLM sometimes wraps the tool name in a list — normalise it
        if isinstance(tool_name, list):
            tool_name = tool_name[0] if tool_name else ""
        log.info("Executing Google tool: %s  args=%s", tool_name, args)
        try:
            if tool_name == "gmail_list":
                from jrvs.google.gmail_client import GmailClient
                return GmailClient().list_messages(**_filter(args, ["max_results", "label", "query"]))

            elif tool_name == "gmail_read":
                from jrvs.google.gmail_client import GmailClient
                return GmailClient().read_message(args["message_id"])

            elif tool_name == "gmail_search":
                from jrvs.google.gmail_client import GmailClient
                return GmailClient().search_messages(args["query"], args.get("max_results"))

            elif tool_name == "gmail_send":
                from jrvs.google.gmail_client import GmailClient
                return GmailClient().send_message(args["to"], args["subject"], args["body"])

            elif tool_name == "gmail_reply":
                from jrvs.google.gmail_client import GmailClient
                return GmailClient().reply_to_message(args["message_id"], args["body"])

            elif tool_name == "gmail_labels":
                from jrvs.google.gmail_client import GmailClient
                return GmailClient().list_labels()

            elif tool_name == "docs_list":
                from jrvs.google.docs_client import DocsClient
                return DocsClient().list_documents(args.get("max_results"))

            elif tool_name == "docs_read":
                from jrvs.google.docs_client import DocsClient
                return DocsClient().read_document(args["document_id"])

            elif tool_name == "docs_find":
                from jrvs.google.docs_client import DocsClient
                return DocsClient().find_document_by_name(args["name"])

            elif tool_name == "docs_create":
                from jrvs.google.docs_client import DocsClient
                return DocsClient().create_document(args["title"], args.get("content", ""))

            elif tool_name == "docs_append":
                from jrvs.google.docs_client import DocsClient
                return DocsClient().append_to_document(args["document_id"], args["text"])

            elif tool_name == "docs_replace":
                from jrvs.google.docs_client import DocsClient
                return DocsClient().replace_in_document(
                    args["document_id"], args["find"], args["replace_with"]
                )

            elif tool_name == "sheets_list":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().list_spreadsheets(args.get("max_results"))

            elif tool_name == "sheets_read":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().read_range(
                    args["spreadsheet_id"], args.get("range", "Sheet1")
                )

            elif tool_name == "sheets_find":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().find_spreadsheet_by_name(args["name"])

            elif tool_name == "sheets_write":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().write_range(
                    args["spreadsheet_id"], args["range"], args["values"]
                )

            elif tool_name == "sheets_append":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().append_rows(
                    args["spreadsheet_id"], args["range"], args["values"]
                )

            elif tool_name == "sheets_create":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().create_spreadsheet(
                    args["title"], args.get("sheet_names")
                )

            elif tool_name == "sheets_info":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().get_spreadsheet_info(args["spreadsheet_id"])

            elif tool_name == "sheets_clear":
                from jrvs.google.sheets_client import SheetsClient
                return SheetsClient().clear_range(args["spreadsheet_id"], args["range"])

            elif tool_name == "calendar_list_calendars":
                from jrvs.google.calendar_client import CalendarClient
                return CalendarClient().list_calendars()

            elif tool_name == "calendar_events":
                from jrvs.google.calendar_client import CalendarClient
                return CalendarClient().list_events(**_filter(args, [
                    "calendar_id", "max_results", "time_min", "time_max",
                ]))

            elif tool_name == "calendar_find":
                from jrvs.google.calendar_client import CalendarClient
                return CalendarClient().find_events(
                    args["query"],
                    args.get("calendar_id", "primary"),
                    args.get("max_results"),
                )

            elif tool_name == "calendar_create":
                from jrvs.google.calendar_client import CalendarClient
                return CalendarClient().create_event(
                    summary=args["summary"],
                    start=args["start"],
                    end=args["end"],
                    description=args.get("description", ""),
                    location=args.get("location", ""),
                    attendees=args.get("attendees"),
                    calendar_id=args.get("calendar_id", "primary"),
                    all_day=args.get("all_day", False),
                )

            elif tool_name == "calendar_delete":
                from jrvs.google.calendar_client import CalendarClient
                return CalendarClient().delete_event(
                    args["event_id"], args.get("calendar_id", "primary")
                )

            elif tool_name == "calendar_update":
                from jrvs.google.calendar_client import CalendarClient
                extra = _filter(args, ["summary", "description", "location", "start", "end"])
                return CalendarClient().update_event(
                    args["event_id"],
                    args.get("calendar_id", "primary"),
                    **extra,
                )

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except Exception as exc:
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return {"error": str(exc)}

    # ── LLM synthesis ────────────────────────────────────────────────────

    def _synthesise(self, request: str, executed: list[dict]) -> str:
        """Ask the LLM to turn raw API results into a clean answer."""
        data_str = json.dumps(
            [{"tool": e["tool"], "result": e["result"]} for e in executed],
            indent=2,
            default=str,
        )
        user_msg = (
            f"Original request: {request}\n\n"
            f"API results:\n{data_str[:6000]}\n\n"  # cap at 6 k chars
            "Please give a clear, helpful answer based on the API results above."
        )
        try:
            return self._llm.chat(
                messages=[
                    {"role": "system", "content": _SYNTHESIS_SYSTEM},
                    {"role": "user",   "content": user_msg},
                ]
            )
        except Exception as exc:
            log.error("LLM synthesis failed: %s", exc)
            return f"API call succeeded. Raw result:\n{data_str[:2000]}"

    # ── Semantic hint ─────────────────────────────────────────────────────

    def _semantic_hint(self, request: str, top_k: int = 3) -> list[str]:
        """Return the names of the top-k most semantically similar tools."""
        try:
            import numpy as np
            if self._encoder is None:
                from jrvs.embeddings.encoder import EmbeddingEncoder
                self._encoder = EmbeddingEncoder.get()

            # Embed all tool descriptions once (cached in memory for the session)
            if not hasattr(self, "_tool_vecs"):
                descs = [t["description"] for t in TOOLS]
                self._tool_vecs = self._encoder.encode(descs)  # (N, dim)
                self._tool_names = [t["name"] for t in TOOLS]

            q_vec = self._encoder.encode_single(request)
            scores = self._tool_vecs @ q_vec  # cosine (vectors are normalised)
            top_idxs = np.argsort(scores)[::-1][:top_k]
            return [self._tool_names[i] for i in top_idxs]
        except Exception as exc:
            log.debug("Semantic hint failed: %s", exc)
            return []


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> Any:
    """Extract and parse the first JSON object/array from *text*."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to extract from markdown code fence
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Grab first { } or [ ] block
    m = re.search(r"(\{[\s\S]+\}|\[[\s\S]+\])", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON found in LLM response:\n{text[:300]}")


def _filter(d: dict, keys: list[str]) -> dict:
    """Return only the *keys* that are present in *d* and not None."""
    return {k: v for k, v in d.items() if k in keys and v is not None}
