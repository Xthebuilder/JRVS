"""
JRVS Nextcloud CalDAV client.

Wraps a CalDAV connection (tested against Nextcloud, works with any
RFC4791-compliant server) for common operations, mirroring the shape
of jrvs.google.calendar_client.CalendarClient:
  list_calendars()      — all calendars on this account
  list_events()         — upcoming events (default: next 20)
  get_event()           — single event by UID
  find_events()         — keyword/text search across events
  create_event()        — create a new event
  update_event()        — patch fields on an existing event
  delete_event()        — delete an event
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import caldav

from jrvs.config import Config

log = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 365


def _normalize_dav_url(url: str) -> str:
    """If NEXTCLOUD_URL is just the bare server address, append the standard
    Nextcloud CalDAV path so users don't have to know it lives at /remote.php/dav/."""
    url = url.rstrip("/")
    if "/dav" not in url.lower():
        url += "/remote.php/dav"
    return url + "/"


def _parse_dt(dt_str: str) -> datetime:
    """Parse an ISO 8601 date or datetime string."""
    if len(dt_str) == 10:  # YYYY-MM-DD
        return datetime.fromisoformat(dt_str)
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def _fmt_event(obj: Any) -> dict:
    """Flatten a caldav Event into a clean dict, mirroring the Google client's shape."""
    comp = obj.icalendar_component
    dtstart = comp.get("dtstart")
    dtend = comp.get("dtend")
    return {
        "id":          obj.id or "",
        "summary":     str(comp.get("summary", "(no title)")),
        "description": str(comp.get("description", "") or ""),
        "location":    str(comp.get("location", "") or ""),
        "start":       dtstart.dt.isoformat() if dtstart else "",
        "end":         dtend.dt.isoformat() if dtend else "",
        "status":      str(comp.get("status", "") or ""),
        "html_link":   str(obj.url) if obj.url else "",
        "created":     str(comp.get("created", "") or ""),
        "updated":     str(comp.get("last-modified", "") or ""),
    }


class CalDAVClient:
    """CalDAV client (Nextcloud, or any RFC4791-compliant server)."""

    def __init__(self) -> None:
        if not Config.NEXTCLOUD_URL:
            raise RuntimeError(
                "NEXTCLOUD_URL is not set. Add NEXTCLOUD_URL, NEXTCLOUD_USER "
                "and NEXTCLOUD_APP_PASSWORD to your .env file. "
                "(Generate an app password under Nextcloud Settings → Security.)"
            )
        self._client = caldav.DAVClient(
            url=_normalize_dav_url(Config.NEXTCLOUD_URL),
            username=Config.NEXTCLOUD_USERNAME,
            password=Config.NEXTCLOUD_APP_PASSWORD,
        )
        self._principal = None
        self._calendars_cache: dict[str, Any] = {}

    # ── Internal helpers ─────────────────────────────────────────────────

    def _get_principal(self):
        if self._principal is None:
            self._principal = self._client.principal()
        return self._principal

    def _get_calendar(self, calendar_name: str | None = None):
        """Resolve a calendar by display name (default: NEXTCLOUD_CALENDAR env
        var, falling back to the first calendar on the account)."""
        name = calendar_name or Config.NEXTCLOUD_CALENDAR
        cache_key = name or "__default__"
        if cache_key in self._calendars_cache:
            return self._calendars_cache[cache_key]

        cals = self._get_principal().calendars()
        if not cals:
            raise RuntimeError("No calendars found on this Nextcloud account.")

        target = None
        if name:
            for c in cals:
                if c.name == name or c.id == name:
                    target = c
                    break
        if target is None:
            target = cals[0]

        self._calendars_cache[cache_key] = target
        return target

    # ── Calendars ────────────────────────────────────────────────────────

    def list_calendars(self) -> list[dict]:
        """Return all calendars accessible by this account."""
        cals = self._get_principal().calendars()
        return [{"id": c.id, "name": c.name or c.id, "url": str(c.url)} for c in cals]

    # ── Events ───────────────────────────────────────────────────────────

    def list_events(
        self,
        calendar_name: str | None = None,
        max_results: int | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
    ) -> list[dict]:
        """List upcoming events, defaulting to now → +365 days."""
        cal = self._get_calendar(calendar_name)
        start = _parse_dt(time_min) if time_min else datetime.now()
        end = _parse_dt(time_max) if time_max else start + timedelta(days=_DEFAULT_WINDOW_DAYS)

        results = cal.search(start=start, end=end, event=True, expand=True)
        events = [_fmt_event(ev) for ev in results]
        events.sort(key=lambda e: e["start"])
        limit = max_results or Config.NEXTCLOUD_LIST_LIMIT
        return events[:limit]

    def get_event(self, event_id: str, calendar_name: str | None = None) -> dict:
        """Fetch a single event by UID."""
        cal = self._get_calendar(calendar_name)
        ev = cal.event_by_uid(event_id)
        return _fmt_event(ev)

    def find_events(
        self,
        query: str,
        calendar_name: str | None = None,
        max_results: int | None = None,
    ) -> list[dict]:
        """Substring search across event summaries."""
        cal = self._get_calendar(calendar_name)
        results = cal.search(summary=query, event=True)
        events = [_fmt_event(ev) for ev in results]
        limit = max_results or Config.NEXTCLOUD_LIST_LIMIT
        return events[:limit]

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        calendar_name: str | None = None,
        all_day: bool = False,
    ) -> dict:
        """Create a new calendar event.

        Parameters
        ----------
        summary     : event title
        start / end : ISO 8601 datetime strings e.g. "2026-03-01T10:00:00"
                      For all-day events use "YYYY-MM-DD" and all_day=True
        """
        if all_day:
            dtstart: Any = _parse_dt(start[:10]).date()
            dtend: Any = _parse_dt(end[:10]).date()
        else:
            dtstart = _parse_dt(start)
            dtend = _parse_dt(end)

        cal = self._get_calendar(calendar_name)
        kwargs: dict[str, Any] = {"summary": summary, "dtstart": dtstart, "dtend": dtend}
        if description:
            kwargs["description"] = description
        if location:
            kwargs["location"] = location

        ev = cal.save_event(**kwargs)
        return _fmt_event(ev)

    def update_event(
        self,
        event_id: str,
        calendar_name: str | None = None,
        **kwargs,
    ) -> dict:
        """Patch fields on an existing event. Pass any of:
        summary, description, location, start, end (ISO strings).
        """
        cal = self._get_calendar(calendar_name)
        ev = cal.event_by_uid(event_id)
        comp = ev.icalendar_component

        field_map = {"start": "dtstart", "end": "dtend"}
        for key, val in kwargs.items():
            if val is None:
                continue
            ical_key = field_map.get(key, key)
            if ical_key in comp:
                del comp[ical_key]
            comp.add(ical_key, _parse_dt(val) if ical_key in ("dtstart", "dtend") else val)

        ev.save()
        return _fmt_event(ev)

    def delete_event(self, event_id: str, calendar_name: str | None = None) -> dict:
        """Delete an event. Returns confirmation dict."""
        cal = self._get_calendar(calendar_name)
        ev = cal.event_by_uid(event_id)
        ev.delete()
        return {"deleted": True, "event_id": event_id}
