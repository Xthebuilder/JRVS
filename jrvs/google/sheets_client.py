"""
Google Sheets API client for JRVS.

Supported operations:
  - list        : list recent Sheets files via Drive
  - read_sheet  : read all values from a sheet range
  - write_range : write a 2-D list of values to a range
  - append_rows : append rows to the end of a sheet
  - create      : create a new spreadsheet
  - clear_range : clear a named range
  - get_info    : return sheet names and row counts for a spreadsheet
"""

from __future__ import annotations

import logging
from typing import Any

from jrvs.config import Config

log = logging.getLogger(__name__)


class SheetsClient:
    """Thin wrapper around the Google Sheets API v4."""

    def __init__(self) -> None:
        from jrvs.google.auth import build_service
        self._sheets = build_service("sheets", "v4").spreadsheets()
        self._drive  = build_service("drive", "v3")

    # ── List ─────────────────────────────────────────────────────────────

    def list_spreadsheets(self, max_results: int | None = None) -> list[dict[str, Any]]:
        """List recent Google Sheets files."""
        max_results = max_results or Config.GOOGLE_LIST_LIMIT
        resp = (
            self._drive.files()
            .list(
                q="mimeType='application/vnd.google-apps.spreadsheet'",
                pageSize=max_results,
                fields="files(id,name,modifiedTime,webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )
        return [
            {
                "id":       f["id"],
                "name":     f["name"],
                "modified": f.get("modifiedTime", ""),
                "url":      f.get("webViewLink", ""),
            }
            for f in resp.get("files", [])
        ]

    # ── Read ─────────────────────────────────────────────────────────────

    def read_range(
        self, spreadsheet_id: str, range_: str = "Sheet1"
    ) -> dict[str, Any]:
        """Read all cell values from *range_* (e.g. 'Sheet1!A1:Z100')."""
        resp = (
            self._sheets.values()
            .get(spreadsheetId=spreadsheet_id, range=range_)
            .execute()
        )
        values = resp.get("values", [])
        return {
            "spreadsheet_id": spreadsheet_id,
            "range":          resp.get("range", range_),
            "rows":           len(values),
            "cols":           max((len(r) for r in values), default=0),
            "values":         values,
        }

    def find_spreadsheet_by_name(self, name: str) -> dict[str, Any] | None:
        """Find the first spreadsheet whose name contains *name*."""
        safe_name = name.replace("\\", "\\\\").replace("'", "\\'")
        resp = (
            self._drive.files()
            .list(
                q=f"mimeType='application/vnd.google-apps.spreadsheet' and name contains '{safe_name}'",
                pageSize=1,
                fields="files(id,name,webViewLink)",
            )
            .execute()
        )
        files = resp.get("files", [])
        if not files:
            return None
        f = files[0]
        return {
            "id":  f["id"],
            "name": f["name"],
            "url":  f.get("webViewLink", ""),
        }

    # ── Write ─────────────────────────────────────────────────────────────

    def write_range(
        self,
        spreadsheet_id: str,
        range_: str,
        values: list[list[Any]],
        value_input: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Write *values* (2-D list) to *range_*."""
        body = {"values": values}
        resp = (
            self._sheets.values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption=value_input,
                body=body,
            )
            .execute()
        )
        log.info(
            "Wrote %d cells to %s!%s",
            resp.get("updatedCells", 0),
            spreadsheet_id,
            range_,
        )
        return {
            "spreadsheet_id":  spreadsheet_id,
            "updated_range":   resp.get("updatedRange", range_),
            "updated_rows":    resp.get("updatedRows", 0),
            "updated_cols":    resp.get("updatedColumns", 0),
            "updated_cells":   resp.get("updatedCells", 0),
        }

    def append_rows(
        self,
        spreadsheet_id: str,
        range_: str,
        values: list[list[Any]],
        value_input: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Append *values* after the last row with data in *range_*."""
        body = {"values": values}
        resp = (
            self._sheets.values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption=value_input,
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
        updates = resp.get("updates", {})
        log.info(
            "Appended %d rows to %s", updates.get("updatedRows", 0), spreadsheet_id
        )
        return {
            "spreadsheet_id": spreadsheet_id,
            "appended_range": updates.get("updatedRange", ""),
            "appended_rows":  updates.get("updatedRows", 0),
        }

    # ── Create ───────────────────────────────────────────────────────────

    def create_spreadsheet(
        self, title: str, sheet_names: list[str] | None = None
    ) -> dict[str, Any]:
        """Create a new spreadsheet with optional named sheets."""
        body: dict[str, Any] = {"properties": {"title": title}}
        if sheet_names:
            body["sheets"] = [
                {"properties": {"title": n}} for n in sheet_names
            ]
        resp = self._sheets.create(body=body).execute()
        ss_id = resp["spreadsheetId"]
        log.info("Created spreadsheet '%s' (id=%s)", title, ss_id)
        return {
            "id":    ss_id,
            "title": title,
            "url":   f"https://docs.google.com/spreadsheets/d/{ss_id}/edit",
        }

    # ── Clear ────────────────────────────────────────────────────────────

    def clear_range(self, spreadsheet_id: str, range_: str) -> dict[str, Any]:
        """Clear all values in *range_*."""
        resp = (
            self._sheets.values()
            .clear(spreadsheetId=spreadsheet_id, range=range_)
            .execute()
        )
        return {"spreadsheet_id": spreadsheet_id, "cleared_range": resp.get("clearedRange", range_)}

    # ── Info ─────────────────────────────────────────────────────────────

    def get_spreadsheet_info(self, spreadsheet_id: str) -> dict[str, Any]:
        """Return metadata: title, list of sheet names and row counts."""
        meta = self._sheets.get(
            spreadsheetId=spreadsheet_id,
            fields="properties,sheets.properties",
        ).execute()
        sheets = [
            {
                "name":     s["properties"]["title"],
                "sheet_id": s["properties"]["sheetId"],
                "rows":     s["properties"]["gridProperties"].get("rowCount", 0),
                "cols":     s["properties"]["gridProperties"].get("columnCount", 0),
            }
            for s in meta.get("sheets", [])
        ]
        return {
            "id":     spreadsheet_id,
            "title":  meta["properties"]["title"],
            "url":    f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
            "sheets": sheets,
        }
