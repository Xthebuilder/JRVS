"""
Gmail API client for JRVS.

Supported operations:
  - list      : list inbox messages (subject, from, date, snippet)
  - read      : read a message by ID or subject search
  - search    : search messages with Gmail query syntax
  - send      : compose and send an email
  - reply     : reply to an existing thread
  - label     : list all labels
"""

from __future__ import annotations

import base64
import email as _email_lib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from jrvs.config import Config

log = logging.getLogger(__name__)


class GmailClient:
    """Thin wrapper around the Gmail Data API v1."""

    def __init__(self) -> None:
        from jrvs.google.auth import build_service
        self._svc = build_service("gmail", "v1")
        self._user = "me"

    # ── List ─────────────────────────────────────────────────────────────

    def list_messages(
        self,
        max_results: int | None = None,
        label: str = "INBOX",
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Return a summary list of recent messages."""
        max_results = max_results or Config.GOOGLE_LIST_LIMIT
        params: dict[str, Any] = {
            "userId": self._user,
            "maxResults": max_results,
            "labelIds": [label],
        }
        if query:
            params["q"] = query

        resp = self._svc.users().messages().list(**params).execute()
        msgs = resp.get("messages", [])

        results = []
        for m in msgs:
            meta = self._get_message_meta(m["id"])
            results.append(meta)
        return results

    # ── Read ─────────────────────────────────────────────────────────────

    def read_message(self, message_id: str) -> dict[str, Any]:
        """Return full decoded body of a message by ID."""
        msg = (
            self._svc.users()
            .messages()
            .get(userId=self._user, id=message_id, format="full")
            .execute()
        )
        return self._decode_full(msg)

    def search_messages(
        self, query: str, max_results: int | None = None
    ) -> list[dict[str, Any]]:
        """Search messages using Gmail query syntax (e.g. 'from:boss@example.com')."""
        max_results = max_results or Config.GOOGLE_LIST_LIMIT
        resp = (
            self._svc.users()
            .messages()
            .list(userId=self._user, q=query, maxResults=max_results)
            .execute()
        )
        return [self._get_message_meta(m["id"]) for m in resp.get("messages", [])]

    # ── Send ─────────────────────────────────────────────────────────────

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        body_type: str = "plain",
    ) -> dict[str, Any]:
        """Send a new email."""
        mime = MIMEText(body, body_type)
        mime["to"] = to
        mime["subject"] = subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        result = (
            self._svc.users()
            .messages()
            .send(userId=self._user, body={"raw": raw})
            .execute()
        )
        log.info("Email sent to %s (id=%s)", to, result.get("id"))
        return result

    def reply_to_message(
        self,
        message_id: str,
        body: str,
        body_type: str = "plain",
    ) -> dict[str, Any]:
        """Reply to an existing message thread."""
        orig = self.read_message(message_id)
        mime = MIMEText(body, body_type)
        mime["to"] = orig.get("from", "")
        mime["subject"] = "Re: " + orig.get("subject", "")
        mime["In-Reply-To"] = message_id
        mime["References"] = message_id
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        result = (
            self._svc.users()
            .messages()
            .send(
                userId=self._user,
                body={"raw": raw, "threadId": orig.get("thread_id", "")},
            )
            .execute()
        )
        log.info("Reply sent (thread %s)", orig.get("thread_id"))
        return result

    # ── Labels ───────────────────────────────────────────────────────────

    def list_labels(self) -> list[dict[str, Any]]:
        """Return all Gmail labels."""
        resp = self._svc.users().labels().list(userId=self._user).execute()
        return [
            {"id": lb["id"], "name": lb["name"], "type": lb.get("type", "")}
            for lb in resp.get("labels", [])
        ]

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_message_meta(self, msg_id: str) -> dict[str, Any]:
        msg = (
            self._svc.users()
            .messages()
            .get(userId=self._user, id=msg_id, format="metadata",
                 metadataHeaders=["From", "To", "Subject", "Date"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return {
            "id":       msg_id,
            "thread_id": msg.get("threadId", ""),
            "from":     headers.get("From", ""),
            "to":       headers.get("To", ""),
            "subject":  headers.get("Subject", ""),
            "date":     headers.get("Date", ""),
            "snippet":  msg.get("snippet", ""),
            "labels":   msg.get("labelIds", []),
        }

    def _decode_full(self, msg: dict) -> dict[str, Any]:
        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        body = self._extract_body(msg.get("payload", {}))
        return {
            "id":        msg["id"],
            "thread_id": msg.get("threadId", ""),
            "from":      headers.get("From", ""),
            "to":        headers.get("To", ""),
            "subject":   headers.get("Subject", ""),
            "date":      headers.get("Date", ""),
            "body":      body,
            "snippet":   msg.get("snippet", ""),
            "labels":    msg.get("labelIds", []),
        }

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract text/plain body from MIME payload."""
        mime_type = payload.get("mimeType", "")
        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if mime_type in ("multipart/alternative", "multipart/mixed"):
            for part in payload.get("parts", []):
                result = self._extract_body(part)
                if result:
                    return result
        return ""
