"""Gmail read + write client for JRVS Google Workspace integration."""
import base64
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build as google_build
    from googleapiclient.errors import HttpError
    _GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    _GOOGLE_CLIENT_AVAILABLE = False


class GmailClient:
    """Thin async-friendly wrapper around the Gmail REST API.

    All network calls are synchronous (google-api-python-client is sync) but kept
    lightweight so they don't block the event loop for long.  Callers should wrap
    heavy batch operations in asyncio.to_thread() if needed.
    """

    def __init__(self, auth):
        """
        Args:
            auth: GoogleAuth instance (provides get_credentials())
        """
        self._auth = auth
        self._service = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_service(self):
        """Build (or reuse) the Gmail service object."""
        if not _GOOGLE_CLIENT_AVAILABLE:
            raise RuntimeError(
                "google-api-python-client is not installed. "
                "Run: pip install google-api-python-client"
            )
        creds = self._auth.get_credentials()
        if creds is None:
            raise RuntimeError("Not authenticated with Google. Run /google-auth first.")
        if self._service is None:
            self._service = google_build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_messages(
        self,
        query: str = "",
        max_results: int = 10,
        after: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List Gmail messages matching *query*.

        Args:
            query:      Gmail search query string (e.g. "from:alice@example.com")
            max_results: Maximum number of messages to return.
            after:      If set, restrict to messages after this UTC datetime.

        Returns:
            List of message dicts with keys: id, thread_id, subject, from_,
            date, snippet, body.
        """
        svc = self._get_service()
        q = query
        if after:
            epoch = int(after.timestamp())
            q = f"{q} after:{epoch}".strip()

        try:
            resp = svc.users().messages().list(
                userId="me", q=q, maxResults=max_results
            ).execute()
        except HttpError as exc:
            log.error("Gmail list error: %s", exc)
            return []

        message_stubs = resp.get("messages", [])
        messages = []
        for stub in message_stubs:
            msg = self._fetch_message(svc, stub["id"])
            if msg:
                messages.append(msg)
        return messages

    def _fetch_message(self, svc, message_id: str) -> Optional[Dict[str, Any]]:
        """Fetch full message details and extract useful fields."""
        try:
            raw = svc.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        except HttpError as exc:
            log.warning("Failed to fetch message %s: %s", message_id, exc)
            return None

        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        body = self._extract_body(raw.get("payload", {}))

        return {
            "id": message_id,
            "thread_id": raw.get("threadId", ""),
            "subject": headers.get("subject", "(no subject)"),
            "from_": headers.get("from", ""),
            "date": headers.get("date", ""),
            "snippet": raw.get("snippet", ""),
            "body": body,
        }

    def _extract_body(self, payload: Dict) -> str:
        """Recursively extract plain-text body from a Gmail payload."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime_type == "text/plain" and body_data:
            return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

        # Recurse into parts
        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text
        return ""

    def format_for_ingestion(self, msg: Dict[str, Any]) -> str:
        """Format a message dict as plain text suitable for FAISS ingestion."""
        return (
            f"From: {msg['from_']}\n"
            f"Subject: {msg['subject']}\n"
            f"Date: {msg['date']}\n\n"
            f"{msg['body'] or msg['snippet']}"
        ).strip()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def send(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send an email.

        Returns:
            Dict with keys: id, thread_id, label_ids.
        """
        svc = self._get_service()
        mime_msg = MIMEText(body)
        mime_msg["to"] = to
        mime_msg["subject"] = subject
        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        try:
            result = svc.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            log.info("Email sent to %s, message_id=%s", to, result.get("id"))
            return result
        except HttpError as exc:
            log.error("Failed to send email to %s: %s", to, exc)
            raise

    def apply_label(self, message_id: str, label_name: str) -> None:
        """Apply a label to a message (creates the label if it doesn't exist)."""
        svc = self._get_service()
        label_id = self._get_or_create_label(svc, label_name)
        try:
            svc.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except HttpError as exc:
            log.error("Failed to label message %s: %s", message_id, exc)
            raise

    def _get_or_create_label(self, svc, label_name: str) -> str:
        """Return label ID, creating the label if it doesn't already exist."""
        labels_resp = svc.users().labels().list(userId="me").execute()
        for lbl in labels_resp.get("labels", []):
            if lbl["name"].lower() == label_name.lower():
                return lbl["id"]
        created = svc.users().labels().create(
            userId="me", body={"name": label_name}
        ).execute()
        return created["id"]
