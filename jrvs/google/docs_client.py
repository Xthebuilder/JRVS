"""
Google Docs API client for JRVS.

Supported operations:
  - list    : list recent Docs files via Drive
  - read    : read a document's full text by ID or name search
  - create  : create a new document with optional initial content
  - append  : append text to an existing document
  - replace : perform find-and-replace in a document
"""

from __future__ import annotations

import logging
from typing import Any

from jrvs.config import Config

log = logging.getLogger(__name__)


class DocsClient:
    """Thin wrapper around the Google Docs API v1 + Drive API v3 for listing."""

    def __init__(self) -> None:
        from jrvs.google.auth import build_service
        self._docs = build_service("docs", "v1")
        self._drive = build_service("drive", "v3")

    # ── List ─────────────────────────────────────────────────────────────

    def list_documents(self, max_results: int | None = None) -> list[dict[str, Any]]:
        """List recent Google Docs files."""
        max_results = max_results or Config.GOOGLE_LIST_LIMIT
        resp = (
            self._drive.files()
            .list(
                q="mimeType='application/vnd.google-apps.document'",
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

    def read_document(self, document_id: str) -> dict[str, Any]:
        """Return full plain-text content of a document by its ID."""
        doc = self._docs.documents().get(documentId=document_id).execute()
        title = doc.get("title", "")
        text = _extract_doc_text(doc)
        return {
            "id":    document_id,
            "title": title,
            "text":  text,
            "url":   f"https://docs.google.com/document/d/{document_id}/edit",
        }

    def find_document_by_name(self, name: str) -> dict[str, Any] | None:
        """Find the first document whose name contains *name*."""
        safe_name = name.replace("\\", "\\\\").replace("'", "\\'")
        resp = (
            self._drive.files()
            .list(
                q=f"mimeType='application/vnd.google-apps.document' and name contains '{safe_name}'",
                pageSize=1,
                fields="files(id,name,modifiedTime,webViewLink)",
            )
            .execute()
        )
        files = resp.get("files", [])
        if not files:
            return None
        return self.read_document(files[0]["id"])

    # ── Create ───────────────────────────────────────────────────────────

    def create_document(self, title: str, content: str = "") -> dict[str, Any]:
        """Create a new Google Doc, automatically inserting a title + date header."""
        from datetime import date
        doc = self._docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        # Build header: Title / Date / separator / body content
        today = date.today().strftime("%B %d, %Y")
        separator = "─" * 48
        header = f"{title}\n{today}\n{separator}\n\n"
        full_text = header + content if content else header

        self._insert_text(doc_id, full_text, index=1)
        log.info("Created doc '%s' (id=%s)", title, doc_id)
        return {
            "id":    doc_id,
            "title": title,
            "url":   f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    # ── Append ───────────────────────────────────────────────────────────

    def append_to_document(self, document_id: str, text: str) -> dict[str, Any]:
        """Append *text* to the end of a document."""
        doc = self._docs.documents().get(documentId=document_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1
        self._insert_text(document_id, "\n" + text, index=end_index)
        log.info("Appended %d chars to doc %s", len(text), document_id)
        return {"id": document_id, "appended_chars": len(text)}

    # ── Replace ──────────────────────────────────────────────────────────

    def replace_in_document(
        self, document_id: str, find: str, replace_with: str
    ) -> dict[str, Any]:
        """Perform a find-and-replace in a document."""
        requests = [
            {
                "replaceAllText": {
                    "containsText": {"text": find, "matchCase": True},
                    "replaceText": replace_with,
                }
            }
        ]
        result = (
            self._docs.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )
        count = (
            result.get("replies", [{}])[0]
            .get("replaceAllText", {})
            .get("occurrencesChanged", 0)
        )
        return {"id": document_id, "replacements": count}

    # ── Internal helpers ─────────────────────────────────────────────────

    def _insert_text(self, document_id: str, text: str, index: int) -> None:
        requests = [{"insertText": {"location": {"index": index}, "text": text}}]
        self._docs.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()


# ── Utility ───────────────────────────────────────────────────────────────────

def _extract_doc_text(doc: dict) -> str:
    """Walk the structural elements and extract plain text."""
    parts: list[str] = []
    for element in doc.get("body", {}).get("content", []):
        para = element.get("paragraph")
        if not para:
            continue
        for elem in para.get("elements", []):
            text_run = elem.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts)
