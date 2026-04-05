"""
CommandExecutor — runs parsed intents against JRVS and returns plain-English results.

Imports JRVS modules directly (no HTTP overhead, works even when the API
server is not running).  Falls back to the on_input() callback for anything
not handled here — so unrecognized commands still get a JRVS response.

Each handler returns a human-readable string that CommandMode will speak aloud.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional

from extensions.audio.intent_parser import Intent

logger = logging.getLogger(__name__)

_JRVS_ROOT = str(Path(__file__).parent.parent.parent)


def _ensure_jrvs() -> bool:
    if _JRVS_ROOT not in sys.path:
        sys.path.insert(0, _JRVS_ROOT)
    try:
        import config  # noqa: F401
        return True
    except ImportError:
        return False


class CommandExecutor:
    """Executes voice intents and returns natural-language result strings."""

    def __init__(
        self,
        on_input: Optional[Callable[[str], Awaitable[str]]] = None,
        jrvs_api_url: str | None = None,
        vision_module=None,
    ) -> None:
        """
        Args:
            on_input:       Async fn(text)->str that calls JRVS chat (fallback)
            jrvs_api_url:   Base URL of the JRVS API server (if running)
            vision_module:  Optional VisionModule instance for vision commands
        """
        self._on_input = on_input
        if jrvs_api_url is None:
            from config import JRVS_SERVER_HOST, JRVS_SERVER_PORT
            jrvs_api_url = f"http://{JRVS_SERVER_HOST}:{JRVS_SERVER_PORT}"
        self._api_url = jrvs_api_url.rstrip("/")
        self._vision = vision_module
        self._jrvs_ok = _ensure_jrvs()

    async def execute(self, intent: Intent) -> str:
        """Dispatch an intent to the correct handler. Returns a spoken response."""
        name = intent.name
        arg = intent.args.get("arg", "").strip()

        handlers = {
            "SWITCH_MODEL":   self._switch_model,
            "LIST_MODELS":    self._list_models,
            "WEB_SEARCH":     self._web_search,
            "SCRAPE_URL":     self._scrape_url,
            "SHOW_CALENDAR":  self._show_calendar,
            "SHOW_TODAY":     self._show_today,
            "INGEST_ALL":     self._ingest_all,
            "INGEST_FILE":    self._ingest_file,
            "SHOW_STATS":     self._show_stats,
            "SHOW_HISTORY":   self._show_history,
            "SET_THEME":      self._set_theme,
            "VISION_SCREEN":  self._vision_screen,
            "VISION_CAMERA":  self._vision_camera,
            "VISION_STATUS":  self._vision_status,
            "MUTE":           self._mute,
            "UNMUTE":         self._unmute,
            "HELP":           self._help,
        }

        handler = handlers.get(name)
        if handler:
            try:
                return await handler(arg, intent)
            except Exception as exc:
                logger.error("Command handler %s failed: %s", name, exc, exc_info=True)
                return f"I ran into a problem with that command. {exc}"

        # Unknown intent — fall through to normal chat
        if self._on_input:
            return await self._on_input(intent.raw_text)
        return "I didn't recognise that as a command."

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    async def _switch_model(self, arg: str, intent: Intent) -> str:
        if not arg:
            return "Which model would you like me to switch to?"
        if not self._jrvs_ok:
            return "I can't reach the JRVS core right now."
        try:
            from llm.ollama_client import ollama_client
            success = await ollama_client.switch_model(arg)
            if success:
                readable = arg.replace(":", " at ").replace("-", " ").replace("_", " ")
                return f"Done. I'm now using {readable}."
            return (
                f"I couldn't switch to {arg}. "
                "Make sure it's installed — try running ollama pull in a terminal."
            )
        except Exception as exc:
            logger.error("switch_model error: %s", exc)
            return f"Model switch failed: {exc}"

    async def _list_models(self, arg: str, intent: Intent) -> str:
        if not self._jrvs_ok:
            return "Can't reach JRVS core."
        try:
            from llm.ollama_client import ollama_client
            models = await ollama_client.discover_models()
            if not models:
                return "No models found. Is Ollama running?"
            names = ", ".join(models[:8])
            suffix = f" and {len(models) - 8} more" if len(models) > 8 else ""
            return f"I have {len(models)} models available: {names}{suffix}."
        except Exception as exc:
            return f"Couldn't list models: {exc}"

    # ------------------------------------------------------------------
    # Web search / scrape
    # ------------------------------------------------------------------

    async def _web_search(self, arg: str, intent: Intent) -> str:
        if not arg:
            return "What should I search for?"
        if self._on_input:
            query = f"/websearch {arg}"
            result = await self._on_input(query)
            return result or f"I searched for {arg} and added results to your knowledge base."
        return f"Web search requires the JRVS chat function to be connected."

    async def _scrape_url(self, arg: str, intent: Intent) -> str:
        if not arg:
            return "I need a URL to scrape."
        if not self._jrvs_ok:
            return "Can't reach JRVS core for scraping."
        try:
            from scraper.web_scraper import web_scraper
            doc_id = await web_scraper.scrape_and_store(arg)
            if doc_id:
                return f"Done. I've scraped that page and added it to your knowledge base."
            return "That URL may already be in my knowledge base, or I couldn't reach it."
        except Exception as exc:
            return f"Scraping failed: {exc}"

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------

    async def _show_calendar(self, arg: str, intent: Intent) -> str:
        if not self._jrvs_ok:
            return "Can't reach JRVS calendar."
        try:
            from core.calendar import calendar as cal
            await cal.initialize()
            events = await cal.get_upcoming_events(days=7)
            if not events:
                return "Your calendar is clear for the next 7 days."
            lines = []
            for e in events[:5]:
                dt = e.get("event_date", "")[:10]
                lines.append(f"{e['title']} on {dt}")
            more = f" and {len(events) - 5} more" if len(events) > 5 else ""
            return f"You have {len(events)} events coming up: " + "; ".join(lines) + more + "."
        except Exception as exc:
            return f"Calendar error: {exc}"

    async def _show_today(self, arg: str, intent: Intent) -> str:
        if not self._jrvs_ok:
            return "Can't reach JRVS calendar."
        try:
            from core.calendar import calendar as cal
            await cal.initialize()
            events = await cal.get_upcoming_events(days=1)
            today = datetime.now().date()
            todays = [
                e for e in events
                if e.get("event_date", "")[:10] == str(today)
            ]
            if not todays:
                return "Nothing on your calendar today."
            lines = [e["title"] for e in todays]
            return f"Today you have: {'; '.join(lines)}."
        except Exception as exc:
            return f"Calendar error: {exc}"

    # ------------------------------------------------------------------
    # File ingestion
    # ------------------------------------------------------------------

    async def _ingest_all(self, arg: str, intent: Intent) -> str:
        if not self._jrvs_ok:
            return "Can't reach JRVS core."
        try:
            from core.file_handler import file_handler
            results = await file_handler.ingest_all()
            count = len(results) if results else 0
            if count == 0:
                return "No new files found in the uploads folder."
            return f"Done. I've ingested {count} file{'s' if count != 1 else ''} into your knowledge base."
        except Exception as exc:
            return f"Ingestion failed: {exc}"

    async def _ingest_file(self, arg: str, intent: Intent) -> str:
        if not arg:
            return "Which file should I ingest?"
        if not self._jrvs_ok:
            return "Can't reach JRVS core."
        try:
            from core.file_handler import file_handler
            result = await file_handler.ingest_file(arg)
            if result:
                return f"Done. {arg} has been added to your knowledge base."
            return f"I couldn't find or ingest {arg}. Make sure it's in the uploads folder."
        except Exception as exc:
            return f"Ingestion error: {exc}"

    # ------------------------------------------------------------------
    # Stats / history
    # ------------------------------------------------------------------

    async def _show_stats(self, arg: str, intent: Intent) -> str:
        if not self._jrvs_ok:
            return "Can't reach JRVS core."
        try:
            from core.database import db
            await db.initialize()
            conv_count = await db.get_conversation_count()
            doc_count = await db.get_document_count()
            return (
                f"I have {conv_count} conversations and {doc_count} documents "
                "stored in my memory."
            )
        except Exception as exc:
            return f"Stats unavailable: {exc}"

    async def _show_history(self, arg: str, intent: Intent) -> str:
        if not self._jrvs_ok:
            return "Can't reach JRVS core."
        try:
            from core.database import db
            await db.initialize()
            rows = await db.get_recent_conversations(limit=5)
            if not rows:
                return "No conversation history found."
            snippets = []
            for r in rows:
                user = (r.get("user_message") or "")[:40]
                snippets.append(f'You said "{user}"')
            return "Recent conversations: " + "; ".join(snippets) + "."
        except Exception as exc:
            return f"History unavailable: {exc}"

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    async def _set_theme(self, arg: str, intent: Intent) -> str:
        if not arg:
            return "Which theme? Options are matrix, cyberpunk, or minimal."
        if arg not in ("matrix", "cyberpunk", "minimal"):
            return f"I don't have a theme called {arg}. Try matrix, cyberpunk, or minimal."
        if self._on_input:
            await self._on_input(f"/theme {arg}")
        return f"Theme changed to {arg}."

    # ------------------------------------------------------------------
    # Vision control
    # ------------------------------------------------------------------

    async def _vision_screen(self, arg: str, intent: Intent) -> str:
        if self._vision is None:
            return "The vision module isn't connected."
        try:
            from extensions.vision.config import vision_config
            vision_config.camera_source = "screen"
            await self._vision.stop()
            self._vision._camera = self._vision._camera.__class__(
                "screen", fps_capture=vision_config.fps_capture
            )
            self._vision._camera.open()
            await self._vision.start()
            return "Switched to screen capture. I can now see your desktop."
        except Exception as exc:
            return f"Couldn't switch to screen capture: {exc}"

    async def _vision_camera(self, arg: str, intent: Intent) -> str:
        if self._vision is None:
            return "The vision module isn't connected."
        try:
            source = int(arg) if arg.isdigit() else 0
            await self._vision.stop()
            self._vision._camera = self._vision._camera.__class__(
                source, fps_capture=self._vision._cfg.fps_capture
            )
            self._vision._camera.open()
            await self._vision.start()
            return f"Switched to camera {source}."
        except Exception as exc:
            return f"Couldn't switch to camera: {exc}"

    async def _vision_status(self, arg: str, intent: Intent) -> str:
        if self._vision is None:
            return "The vision module isn't running."
        try:
            desc = await self._vision.describe_frame()
            return desc or "I don't have a clear view right now."
        except Exception as exc:
            return f"Vision status error: {exc}"

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    async def _mute(self, arg: str, intent: Intent) -> str:
        # Handled at the CommandMode level; just confirm
        return "Understood. I'll keep quiet until you ask again."

    async def _unmute(self, arg: str, intent: Intent) -> str:
        # Handled at the CommandMode level; just confirm
        return "I'm speaking again. How can I help?"

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    async def _help(self, arg: str, intent: Intent) -> str:
        return (
            "In command mode I can: "
            "switch models, list models, search the web, scrape URLs, "
            "show your calendar, ingest files, show stats, change theme, "
            "control vision between screen and camera, or describe what I'm seeing. "
            "Say 'exit command mode' when you're done."
        )
