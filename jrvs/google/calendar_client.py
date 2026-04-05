"""
JRVS Google Calendar client.

Wraps the Google Calendar API v3 for common operations:
  list_calendars()      — all calendars on this account
  list_events()         — upcoming events (default: next 20)
  get_event()           — single event by ID
  find_events()         — keyword/text search across events
  create_event()        — create a new event
  update_event()        — patch fields on an existing event
  delete_event()        — delete an event
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from jrvs.config import Config
from jrvs.google.auth import build_service

log = logging.getLogger(__name__)

_DEFAULT_CAL = "primary"


def _iso(dt_str: str) -> str:
    """Ensure a datetime string ends with Z / has timezone info."""
    if not dt_str:
        return dt_str
    if dt_str.endswith("Z") or "+" in dt_str or (dt_str.count("-") > 2):
        return dt_str
    return dt_str + "Z"


def _fmt_event(ev: dict) -> dict:
    """Flatten a raw calendar event into a clean dict."""
    start = ev.get("start", {})
    end   = ev.get("end",   {})
    return {
        "id":          ev.get("id", ""),
        "summary":     ev.get("summary", "(no title)"),
        "description": ev.get("description", ""),
        "location":    ev.get("location", ""),
        "start":       start.get("dateTime", start.get("date", "")),
        "end":         end.get("dateTime",   end.get("date",   "")),
        "status":      ev.get("status", ""),
        "html_link":   ev.get("htmlLink", ""),
        "attendees":   [
            {"email": a.get("email", ""), "response": a.get("responseStatus", "")}
            for a in ev.get("attendees", [])
        ],
        "organizer":   ev.get("organizer", {}).get("email", ""),
        "created":     ev.get("created", ""),
        "updated":     ev.get("updated", ""),
    }


class CalendarClient:
    """Google Calendar API v3 wrapper."""

    def __init__(self) -> None:
        self._svc = build_service("calendar", "v3")

    # ── Calendars ────────────────────────────────────────────────────────

    def list_calendars(self) -> list[dict]:
        """Return all calendars accessible by this account."""
        result = self._svc.calendarList().list().execute()
        return [
            {
                "id":       c["id"],
                "summary":  c.get("summary", ""),
                "primary":  c.get("primary", False),
                "access":   c.get("accessRole", ""),
                "color":    c.get("colorId", ""),
            }
            for c in result.get("items", [])
        ]

    # ── Events ───────────────────────────────────────────────────────────

    def list_events(
        self,
        calendar_id: str = _DEFAULT_CAL,
        max_results: int | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        order_by: str = "startTime",
    ) -> list[dict]:
        """List upcoming events, defaulting to now → future."""
        if time_min is None:
            time_min = datetime.now(timezone.utc).isoformat()
        params: dict[str, Any] = {
            "calendarId":   calendar_id,
            "maxResults":   max_results or Config.GOOGLE_LIST_LIMIT,
            "timeMin":      time_min,
            "singleEvents": True,
            "orderBy":      order_by,
        }
        if time_max:
            params["timeMax"] = _iso(time_max)
        result = self._svc.events().list(**params).execute()
        return [_fmt_event(ev) for ev in result.get("items", [])]

    def get_event(self, event_id: str, calendar_id: str = _DEFAULT_CAL) -> dict:
        """Fetch a single event by ID."""
        ev = self._svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        return _fmt_event(ev)

    def find_events(
        self,
        query: str,
        calendar_id: str = _DEFAULT_CAL,
        max_results: int | None = None,
    ) -> list[dict]:
        """Full-text search across event title, description, location, attendees."""
        result = self._svc.events().list(
            calendarId=calendar_id,
            q=query,
            maxResults=max_results or Config.GOOGLE_LIST_LIMIT,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return [_fmt_event(ev) for ev in result.get("items", [])]

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        calendar_id: str = _DEFAULT_CAL,
        all_day: bool = False,
    ) -> dict:
        """Create a new calendar event.

        Parameters
        ----------
        summary     : event title
        start / end : ISO 8601 datetime strings e.g. "2026-03-01T10:00:00"
                      For all-day events use "YYYY-MM-DD" and all_day=True
        attendees   : list of email addresses
        """
        if all_day:
            start_body = {"date": start[:10]}
            end_body   = {"date": end[:10]}
        else:
            tz = "America/New_York"
            start_body = {"dateTime": _iso(start), "timeZone": tz}
            end_body   = {"dateTime": _iso(end),   "timeZone": tz}

        body: dict[str, Any] = {
            "summary":   summary,
            "start":     start_body,
            "end":       end_body,
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]

        ev = self._svc.events().insert(calendarId=calendar_id, body=body).execute()
        return _fmt_event(ev)

    def update_event(
        self,
        event_id: str,
        calendar_id: str = _DEFAULT_CAL,
        **kwargs,
    ) -> dict:
        """Patch fields on an existing event.  Pass any of:
        summary, description, location, start, end (ISO strings).
        """
        existing = self._svc.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()

        for key, val in kwargs.items():
            if key in ("start", "end") and val:
                existing[key] = {"dateTime": _iso(val)}
            elif val is not None:
                existing[key] = val

        updated = self._svc.events().update(
            calendarId=calendar_id, eventId=event_id, body=existing
        ).execute()
        return _fmt_event(updated)

    def delete_event(self, event_id: str, calendar_id: str = _DEFAULT_CAL) -> dict:
        """Delete an event. Returns confirmation dict."""
        self._svc.events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute()
        return {"deleted": True, "event_id": event_id}
