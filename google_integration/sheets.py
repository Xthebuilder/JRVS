"""Google Sheets read + write client for JRVS Google Workspace integration."""
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build as google_build
    from googleapiclient.errors import HttpError
    _GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    _GOOGLE_CLIENT_AVAILABLE = False


class GoogleSheetsClient:
    """Thin wrapper around the Google Sheets REST API."""

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
            self._service = google_build("sheets", "v4", credentials=creds, cache_discovery=False)
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

    def get_values(self, spreadsheet_id: str, range_: str = "A1:Z1000") -> Dict[str, Any]:
        """Read a cell range from a Google Sheet.

        Returns:
            Dict with keys: spreadsheet_id, range, values (list of rows),
            csv (plain-text representation for ingestion).
        """
        svc = self._get_service()
        try:
            result = (
                svc.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_)
                .execute()
            )
        except HttpError as exc:
            log.error("Failed to read Sheet %s range %s: %s", spreadsheet_id, range_, exc)
            raise

        values = result.get("values", [])
        csv_lines = [",".join(str(c) for c in row) for row in values]
        return {
            "spreadsheet_id": spreadsheet_id,
            "range": result.get("range", range_),
            "values": values,
            "csv": "\n".join(csv_lines),
        }

    def get_spreadsheet_metadata(self, spreadsheet_id: str) -> Dict[str, Any]:
        """Return title + sheet names for a spreadsheet."""
        svc = self._get_service()
        try:
            meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        except HttpError as exc:
            log.error("Failed to fetch Sheet metadata %s: %s", spreadsheet_id, exc)
            raise
        sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
        return {
            "id": spreadsheet_id,
            "title": meta.get("properties", {}).get("title", "Untitled"),
            "sheets": sheets,
        }

    def find_by_title(self, title: str) -> Optional[str]:
        """Search Drive for a Google Sheet with the given title; return its ID or None."""
        drive = self._get_drive_service()
        safe_title = title.replace("'", "\\'")
        query = (
            f"name='{safe_title}' "
            "and mimeType='application/vnd.google-apps.spreadsheet' "
            "and trashed=false"
        )
        try:
            resp = drive.files().list(q=query, fields="files(id,name)", pageSize=5).execute()
        except HttpError as exc:
            log.error("Drive search for sheet '%s' failed: %s", title, exc)
            return None
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def format_for_ingestion(self, data: Dict[str, Any]) -> str:
        """Format sheet data as labelled CSV text for FAISS ingestion."""
        header = f"Spreadsheet: {data['spreadsheet_id']}  Range: {data['range']}\n"
        return header + data["csv"]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def update_values(
        self,
        spreadsheet_id: str,
        range_: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """Write values to a cell range.

        Args:
            spreadsheet_id: Target spreadsheet ID.
            range_:          A1 notation range (e.g. "Sheet1!A1:C3").
            values:          2-D list of cell values.
            value_input_option: "USER_ENTERED" or "RAW".

        Returns:
            Sheets API updateValues response dict.
        """
        svc = self._get_service()
        body = {"values": values}
        try:
            result = (
                svc.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_,
                    valueInputOption=value_input_option,
                    body=body,
                )
                .execute()
            )
            log.info(
                "Updated Sheet %s range %s: %d cells",
                spreadsheet_id,
                range_,
                result.get("updatedCells", 0),
            )
            return result
        except HttpError as exc:
            log.error("Failed to update Sheet %s: %s", spreadsheet_id, exc)
            raise
