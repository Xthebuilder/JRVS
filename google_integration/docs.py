"""Google Docs read + write client for JRVS Google Workspace integration."""
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build as google_build
    from googleapiclient.errors import HttpError
    _GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    _GOOGLE_CLIENT_AVAILABLE = False


class GoogleDocsClient:
    """Thin wrapper around the Google Docs REST API."""

    def __init__(self, auth):
        self._auth = auth
        self._service = None
        self._drive_service = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_service(self):
        if not _GOOGLE_CLIENT_AVAILABLE:
            raise RuntimeError("google-api-python-client is not installed.")
        creds = self._auth.get_credentials()
        if creds is None:
            raise RuntimeError("Not authenticated with Google. Run /google-auth first.")
        if self._service is None:
            self._service = google_build("docs", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def _get_drive_service(self):
        if not _GOOGLE_CLIENT_AVAILABLE:
            raise RuntimeError("google-api-python-client is not installed.")
        creds = self._auth.get_credentials()
        if creds is None:
            raise RuntimeError("Not authenticated with Google. Run /google-auth first.")
        if self._drive_service is None:
            self._drive_service = google_build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._drive_service

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a Google Doc by its ID.

        Returns:
            Dict with keys: id, title, content (plain text), revision_id.
        """
        svc = self._get_service()
        try:
            raw = svc.documents().get(documentId=doc_id).execute()
        except HttpError as exc:
            log.error("Failed to fetch Google Doc %s: %s", doc_id, exc)
            raise

        title = raw.get("title", "Untitled")
        content = self._extract_text(raw.get("body", {}).get("content", []))
        return {
            "id": doc_id,
            "title": title,
            "content": content,
            "revision_id": raw.get("revisionId", ""),
        }

    def find_by_title(self, title: str) -> Optional[str]:
        """Search Drive for a Google Doc with the given title; return its ID or None."""
        drive = self._get_drive_service()
        safe_title = title.replace("'", "\\'")
        query = (
            f"name='{safe_title}' "
            "and mimeType='application/vnd.google-apps.document' "
            "and trashed=false"
        )
        try:
            resp = drive.files().list(q=query, fields="files(id,name)", pageSize=5).execute()
        except HttpError as exc:
            log.error("Drive search for doc '%s' failed: %s", title, exc)
            return None
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def _extract_text(self, content_elements: List[Dict]) -> str:
        """Convert Docs API structural elements to plain text."""
        lines = []
        for elem in content_elements:
            para = elem.get("paragraph")
            if para:
                for el in para.get("elements", []):
                    text_run = el.get("textRun")
                    if text_run:
                        lines.append(text_run.get("content", ""))
            table = elem.get("table")
            if table:
                for row in table.get("tableRows", []):
                    row_texts = []
                    for cell in row.get("tableCells", []):
                        cell_text = self._extract_text(cell.get("content", []))
                        row_texts.append(cell_text.strip())
                    lines.append(" | ".join(row_texts))
        return "".join(lines)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_document(self, title: str, content: str) -> Dict[str, Any]:
        """Create a new Google Doc with plain-text content.

        Returns:
            Dict with keys: id, title, url.
        """
        svc = self._get_service()
        try:
            doc = svc.documents().create(body={"title": title}).execute()
        except HttpError as exc:
            log.error("Failed to create Google Doc '%s': %s", title, exc)
            raise

        doc_id = doc["documentId"]
        # Insert content as a single text block
        if content:
            requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
            try:
                svc.documents().batchUpdate(
                    documentId=doc_id, body={"requests": requests}
                ).execute()
            except HttpError as exc:
                log.error("Failed to insert content into Doc %s: %s", doc_id, exc)
                raise

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        log.info("Created Google Doc '%s' (%s)", title, doc_id)
        return {"id": doc_id, "title": title, "url": url}

    def append_to_document(self, doc_id: str, content: str) -> None:
        """Append plain-text content to an existing Google Doc."""
        svc = self._get_service()
        # We need the current end index
        try:
            raw = svc.documents().get(documentId=doc_id).execute()
        except HttpError as exc:
            log.error("Failed to fetch Doc %s for append: %s", doc_id, exc)
            raise

        body_content = raw.get("body", {}).get("content", [])
        # Last element gives us the end index
        end_index = 1
        if body_content:
            last = body_content[-1]
            end_index = last.get("endIndex", 1) - 1  # insert before the final \n

        requests = [{"insertText": {"location": {"index": end_index}, "text": "\n" + content}}]
        try:
            svc.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()
        except HttpError as exc:
            log.error("Failed to append to Doc %s: %s", doc_id, exc)
            raise
