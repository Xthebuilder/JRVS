"""Google Drive browse + content-download client for JRVS."""
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build as google_build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload
    _GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    _GOOGLE_CLIENT_AVAILABLE = False

# MIME types we can ingest
_EXPORTABLE_DOCS = "application/vnd.google-apps.document"
_EXPORTABLE_SHEETS = "application/vnd.google-apps.spreadsheet"
_SUPPORTED_TYPES = {_EXPORTABLE_DOCS, _EXPORTABLE_SHEETS}

# Export MIME for each Google native type
_EXPORT_MIME = {
    _EXPORTABLE_DOCS: "text/plain",
    _EXPORTABLE_SHEETS: "text/csv",
}


class GoogleDriveClient:
    """Thin wrapper around the Google Drive REST API (read-only)."""

    def __init__(self, auth):
        self._auth = auth
        self._service = None

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
            self._service = google_build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    # ------------------------------------------------------------------
    # List / search
    # ------------------------------------------------------------------

    def list_files(
        self,
        max_results: int = 20,
        modified_after: Optional[datetime] = None,
        mime_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List Drive files, optionally filtered by modification time and MIME type.

        Returns:
            List of dicts: {id, name, mimeType, modifiedTime}.
        """
        svc = self._get_service()

        type_filter = mime_types or list(_SUPPORTED_TYPES)
        mime_clause = " or ".join(f"mimeType='{m}'" for m in type_filter)
        query = f"({mime_clause}) and trashed=false"

        if modified_after:
            ts = modified_after.strftime("%Y-%m-%dT%H:%M:%S")
            query += f" and modifiedTime > '{ts}'"

        try:
            resp = self._get_service().files().list(
                q=query,
                pageSize=max_results,
                fields="files(id,name,mimeType,modifiedTime)",
                orderBy="modifiedTime desc",
            ).execute()
        except HttpError as exc:
            log.error("Drive list_files failed: %s", exc)
            return []

        return resp.get("files", [])

    # ------------------------------------------------------------------
    # Download / export
    # ------------------------------------------------------------------

    def export_file(self, file_id: str, mime_type: str) -> Optional[str]:
        """Export a Google Workspace file (Doc → txt, Sheet → csv).

        Args:
            file_id:   Drive file ID.
            mime_type: Source MIME type (used to pick export format).

        Returns:
            Plain-text content string, or None on failure.
        """
        svc = self._get_service()
        export_mime = _EXPORT_MIME.get(mime_type, "text/plain")
        buf = io.BytesIO()
        try:
            request = svc.files().export_media(fileId=file_id, mimeType=export_mime)
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except HttpError as exc:
            log.error("Failed to export Drive file %s: %s", file_id, exc)
            return None
        return buf.getvalue().decode("utf-8", errors="replace")

    def download_file(self, file_id: str) -> Optional[bytes]:
        """Download raw bytes of a non-Google-native file."""
        svc = self._get_service()
        buf = io.BytesIO()
        try:
            request = svc.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except HttpError as exc:
            log.error("Failed to download Drive file %s: %s", file_id, exc)
            return None
        return buf.getvalue()

    def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Return metadata dict for a single Drive file."""
        svc = self._get_service()
        try:
            return svc.files().get(
                fileId=file_id,
                fields="id,name,mimeType,modifiedTime,size",
            ).execute()
        except HttpError as exc:
            log.error("Failed to get Drive metadata for %s: %s", file_id, exc)
            return None

    def get_ingestible_content(self, file_meta: Dict[str, Any]) -> Optional[str]:
        """Given file metadata, return plain-text content for FAISS ingestion (or None)."""
        mime_type = file_meta.get("mimeType", "")
        file_id = file_meta["id"]

        if mime_type in _EXPORT_MIME:
            return self.export_file(file_id, mime_type)

        # For plain text files we can download directly
        if mime_type in ("text/plain", "text/markdown", "application/json"):
            raw = self.download_file(file_id)
            return raw.decode("utf-8", errors="replace") if raw else None

        return None  # unsupported type — skip
