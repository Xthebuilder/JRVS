"""Unified Google Workspace client + background sync loop."""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import config
from .auth import GoogleAuth
from .gmail import GmailClient
from .docs import GoogleDocsClient
from .sheets import GoogleSheetsClient
from .drive import GoogleDriveClient
from .audit_log import AuditLog, init_audit_log

log = logging.getLogger(__name__)


class GoogleWorkspaceClient:
    """Central coordinator for all Google Workspace services.

    Responsibilities:
    - Holds one ``GoogleAuth`` instance shared across all service clients.
    - Provides high-level read methods used by CLI commands.
    - Provides write methods guarded by the audit log.
    - Runs a background asyncio task that periodically syncs new emails /
      documents into FAISS (read-only).

    All heavy Google API calls are synchronous; they run inside
    ``asyncio.to_thread()`` so they don't block the event loop.
    """

    def __init__(self):
        self.auth = GoogleAuth(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            token_path=config.GOOGLE_TOKEN_PATH,
        )
        self.gmail = GmailClient(self.auth)
        self.docs = GoogleDocsClient(self.auth)
        self.sheets = GoogleSheetsClient(self.auth)
        self.drive = GoogleDriveClient(self.auth)

        self.audit_log: AuditLog = init_audit_log(config.DATA_DIR / "logs")

        self._sync_task: Optional[asyncio.Task] = None
        self._last_sync: Dict[str, Optional[datetime]] = {
            "gmail": None,
            "drive": None,
        }
        # Cumulative ingestion counters
        self._ingested: Dict[str, int] = {"emails": 0, "docs": 0}

    # ------------------------------------------------------------------
    # Background sync
    # ------------------------------------------------------------------

    async def start_background_sync(self) -> None:
        """Launch the periodic background sync task (idempotent)."""
        if self._sync_task and not self._sync_task.done():
            log.debug("Background sync already running.")
            return
        self._sync_task = asyncio.create_task(self._sync_loop())
        log.info("Google Workspace background sync started (interval=%d min).",
                 config.GOOGLE_SYNC_INTERVAL_MINUTES)

    async def stop_background_sync(self) -> None:
        """Cancel the background sync task."""
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            log.info("Google Workspace background sync stopped.")

    async def _sync_loop(self) -> None:
        """Infinite loop: sync, sleep, repeat."""
        while True:
            try:
                summary = await self.sync_now()
                log.info("Google sync complete: %s", summary)
            except Exception as exc:
                log.error("Google sync error: %s", exc)
            await asyncio.sleep(config.GOOGLE_SYNC_INTERVAL_MINUTES * 60)

    async def sync_now(self) -> Dict[str, Any]:
        """Run a full sync immediately and return a summary dict."""
        if not self.auth.is_authenticated():
            return {"error": "Not authenticated", "emails_ingested": 0, "docs_ingested": 0}

        emails_ingested = await self._sync_gmail()
        docs_ingested = await self._sync_drive()

        now = datetime.now(timezone.utc)
        self._last_sync["gmail"] = now
        self._last_sync["drive"] = now
        self._ingested["emails"] += emails_ingested
        self._ingested["docs"] += docs_ingested

        return {
            "emails_ingested": emails_ingested,
            "docs_ingested": docs_ingested,
            "synced_at": now.isoformat(),
        }

    async def _sync_gmail(self) -> int:
        """Fetch new emails and ingest into FAISS. Returns count ingested."""
        from rag.retriever import rag_retriever
        from core.database import db

        after = self._last_sync.get("gmail")
        ingested = 0
        try:
            messages = await asyncio.to_thread(
                self.gmail.list_messages,
                query="",
                max_results=config.GOOGLE_GMAIL_MAX_EMAILS,
                after=after,
            )
        except Exception as exc:
            log.error("Gmail sync failed: %s", exc)
            return 0

        for msg in messages:
            url = f"gmail:{msg['id']}"
            exists = await db.check_document_exists(url)
            if exists:
                continue
            content = self.gmail.format_for_ingestion(msg)
            if not content.strip():
                continue
            try:
                await rag_retriever.add_document(
                    content=content,
                    title=msg["subject"],
                    url=url,
                    metadata={
                        "source": "gmail",
                        "from": msg["from_"],
                        "date": msg["date"],
                        "thread_id": msg["thread_id"],
                    },
                )
                ingested += 1
            except Exception as exc:
                log.warning("Failed to ingest email %s: %s", msg["id"], exc)

        return ingested

    async def _sync_drive(self) -> int:
        """Fetch new/modified Drive files and ingest into FAISS. Returns count ingested."""
        from rag.retriever import rag_retriever
        from core.database import db

        after = self._last_sync.get("drive")
        ingested = 0
        try:
            files = await asyncio.to_thread(
                self.drive.list_files,
                max_results=config.GOOGLE_DRIVE_MAX_FILES,
                modified_after=after,
            )
        except Exception as exc:
            log.error("Drive list failed: %s", exc)
            return 0

        for file_meta in files:
            url = f"gdrive:{file_meta['id']}"
            exists = await db.check_document_exists(url)
            if exists:
                continue
            try:
                content = await asyncio.to_thread(self.drive.get_ingestible_content, file_meta)
            except Exception as exc:
                log.warning("Could not export Drive file %s: %s", file_meta["id"], exc)
                continue
            if not content or not content.strip():
                continue
            try:
                await rag_retriever.add_document(
                    content=content,
                    title=file_meta.get("name", "Untitled"),
                    url=url,
                    metadata={
                        "source": "gdrive",
                        "mime_type": file_meta.get("mimeType", ""),
                        "modified": file_meta.get("modifiedTime", ""),
                    },
                )
                ingested += 1
            except Exception as exc:
                log.warning("Failed to ingest Drive file %s: %s", file_meta["id"], exc)

        return ingested

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict for /google-status and API endpoint."""
        return {
            "configured": self.auth.is_configured(),
            "authenticated": self.auth.is_authenticated(),
            "sync_running": self._sync_task is not None and not self._sync_task.done(),
            "sync_interval_minutes": config.GOOGLE_SYNC_INTERVAL_MINUTES,
            "last_sync_gmail": self._last_sync["gmail"].isoformat() if self._last_sync["gmail"] else None,
            "last_sync_drive": self._last_sync["drive"].isoformat() if self._last_sync["drive"] else None,
            "total_emails_ingested": self._ingested["emails"],
            "total_docs_ingested": self._ingested["docs"],
        }

    # ------------------------------------------------------------------
    # Write operations (audit-gated)
    # ------------------------------------------------------------------

    async def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send an email via Gmail (audit-logged)."""
        audit_id = self.audit_log.log_write_intent(
            "send_email", to, f"Subject: {subject}\n{body}"
        )
        try:
            result = await asyncio.to_thread(self.gmail.send, to, subject, body)
            self.audit_log.log_write_result(audit_id, success=True)
            return result
        except Exception as exc:
            self.audit_log.log_write_result(audit_id, success=False, error=str(exc))
            raise

    async def create_doc(self, title: str, content: str) -> Dict[str, Any]:
        """Create a Google Doc (audit-logged)."""
        audit_id = self.audit_log.log_write_intent("create_doc", title, content)
        try:
            result = await asyncio.to_thread(self.docs.create_document, title, content)
            self.audit_log.log_write_result(audit_id, success=True)
            return result
        except Exception as exc:
            self.audit_log.log_write_result(audit_id, success=False, error=str(exc))
            raise

    async def update_sheet(
        self,
        spreadsheet_id: str,
        range_: str,
        values: list,
    ) -> Dict[str, Any]:
        """Update a Google Sheet range (audit-logged)."""
        target = f"{spreadsheet_id}!{range_}"
        audit_id = self.audit_log.log_write_intent(
            "update_sheet", target, str(values)
        )
        try:
            result = await asyncio.to_thread(
                self.sheets.update_values, spreadsheet_id, range_, values
            )
            self.audit_log.log_write_result(audit_id, success=True)
            return result
        except Exception as exc:
            self.audit_log.log_write_result(audit_id, success=False, error=str(exc))
            raise

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """Stop background sync on shutdown."""
        await self.stop_background_sync()


# Module-level singleton
google_workspace = GoogleWorkspaceClient()
