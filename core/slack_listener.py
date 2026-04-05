"""
JARVIS Slack Listener — two-way Socket Mode integration.

Receives messages from Slack and pipes them through the full JARVIS
chat pipeline (MCP tools, RAG memory, LLM). Sends responses back.

No public URL needed — Slack opens a WebSocket to this process.

Setup (one-time):
  1. api.slack.com/apps → your app → Socket Mode → Enable Socket Mode
  2. Generate an App-Level Token with scope: connections:write
     Name it anything (e.g. "jarvis-socket") → copy the xapp-... token
  3. Event Subscriptions → Enable Events → Subscribe to bot events:
       message.im        (DMs to @jarvis)
       app_mention       (@jarvis in any channel)
  4. Add SLACK_APP_TOKEN=xapp-... to .env
  5. Restart JARVIS
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Optional, Callable, Awaitable

log = logging.getLogger(__name__)

# Slack session ID prefix — keeps Slack conversations separate in JARVIS memory
_SLACK_SESSION_PREFIX = "slack-"


def _app_token() -> Optional[str]:
    return os.environ.get("SLACK_APP_TOKEN")


def _bot_token() -> Optional[str]:
    return os.environ.get("SLACK_BOT_TOKEN")


class SlackListener:
    """
    Socket Mode listener that bridges Slack ↔ JARVIS.

    Usage:
        listener = SlackListener()
        listener.set_handler(jarvis_cli.handle_chat_message_for_slack)
        asyncio.create_task(listener.start())
    """

    def __init__(self) -> None:
        self._handler: Optional[Callable[[str, str], Awaitable[str]]] = None
        self._bot_user_id: Optional[str] = None
        self._jarvis_channel_id: Optional[str] = None
        self._running = False
        self._client = None

    def set_handler(self, handler: Callable[[str, str], Awaitable[str]]) -> None:
        """
        Wire the async handler that processes a message and returns a reply.
        Signature: async def handler(message: str, session_id: str) -> str
        """
        self._handler = handler

    def is_configured(self) -> bool:
        token = _app_token()
        return bool(token and token.startswith("xapp-"))

    async def _get_bot_user_id(self) -> Optional[str]:
        """Fetch the bot's own user ID so we can ignore its own messages."""
        import urllib.request
        import json
        token = _bot_token()
        if not token:
            return None
        try:
            req = urllib.request.Request(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return data.get("user_id")
        except Exception as exc:
            log.warning("SlackListener: could not get bot user ID: %s", exc)
            return None

    async def _resolve_channel_id(self, channel_name: str) -> Optional[str]:
        """Resolve a channel name to its Slack channel ID."""
        if not channel_name:
            return None
        import urllib.request, json
        token = _bot_token()
        if not token:
            return None
        try:
            req = urllib.request.Request(
                f"https://slack.com/api/conversations.list?limit=200",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            for ch in data.get("channels", []):
                if ch.get("name") == channel_name:
                    return ch["id"]
        except Exception as exc:
            log.warning("SlackListener: could not resolve channel %r: %s", channel_name, exc)
        return None

    async def _send_reply(self, channel: str, thread_ts: Optional[str], text: str) -> None:
        """Post a reply back to Slack, threading into the original message."""
        import urllib.request
        import json
        token = _bot_token()
        if not token:
            return
        payload: dict = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = json.dumps(payload).encode()
        try:
            req = urllib.request.Request(
                "https://slack.com/api/chat.postMessage",
                data=data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            if not result.get("ok"):
                log.warning("SlackListener: reply failed: %s", result.get("error"))
        except Exception as exc:
            log.warning("SlackListener: could not send reply: %s", exc)

    async def _handle_event(self, payload: dict) -> None:
        """Process a Slack event payload."""
        event = payload.get("event", {})
        etype = event.get("type", "")

        # Ignore bot's own messages and other bots
        if event.get("bot_id") or event.get("subtype"):
            return
        if self._bot_user_id and event.get("user") == self._bot_user_id:
            return

        channel: str = event.get("channel", "")
        channel_type: str = event.get("channel_type", "")
        is_dm = channel_type == "im" or channel.startswith("D")

        # Dedicated no-mention channel (set SLACK_JARVIS_CHANNEL in .env)
        jarvis_channel = os.environ.get("SLACK_JARVIS_CHANNEL", "").lstrip("#")
        # We don't have the channel name here, only the ID — so we track it after first @mention
        is_jarvis_channel = bool(jarvis_channel and channel == self._jarvis_channel_id)

        # Accept: DMs, @mentions, and messages in the dedicated JARVIS channel
        if etype == "app_mention":
            # Learn the channel ID for the dedicated channel on first mention if names match
            pass
        elif etype == "message" and (is_dm or is_jarvis_channel):
            pass
        else:
            return

        raw_text: str = event.get("text", "").strip()
        if not raw_text:
            return

        # Strip the @mention prefix if present (e.g. "<@U0AQSLM1SPP> hello")
        import re
        text = re.sub(r"<@[A-Z0-9]+>\s*", "", raw_text).strip()
        if not text:
            return

        channel: str = event.get("channel", "")
        thread_ts: Optional[str] = event.get("thread_ts") or event.get("ts")
        user: str = event.get("user", "unknown")

        # Each Slack user gets their own persistent session in JARVIS memory
        session_id = f"{_SLACK_SESSION_PREFIX}{user}"

        log.info("SlackListener: message from %s in %s: %r", user, channel, text[:80])

        # Send a "thinking" reaction so the user knows JARVIS received it
        await self._add_reaction(channel, event.get("ts", ""), "thinking_face")

        try:
            if self._handler:
                response = await self._handler(text, session_id)
            else:
                response = "JARVIS handler not connected."
        except Exception as exc:
            log.error("SlackListener: handler error: %s", exc)
            response = f"Sorry, I ran into an error: {exc}"

        # Remove thinking reaction, send reply
        await self._remove_reaction(channel, event.get("ts", ""), "thinking_face")
        await self._send_reply(channel, thread_ts, response)

    async def _add_reaction(self, channel: str, ts: str, emoji: str) -> None:
        import urllib.request, json
        token = _bot_token()
        if not token or not ts:
            return
        try:
            data = json.dumps({"channel": channel, "timestamp": ts, "name": emoji}).encode()
            req = urllib.request.Request(
                "https://slack.com/api/reactions.add", data=data,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    async def _remove_reaction(self, channel: str, ts: str, emoji: str) -> None:
        import urllib.request, json
        token = _bot_token()
        if not token or not ts:
            return
        try:
            data = json.dumps({"channel": channel, "timestamp": ts, "name": emoji}).encode()
            req = urllib.request.Request(
                "https://slack.com/api/reactions.remove", data=data,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    async def start(self) -> None:
        """Connect via Socket Mode and listen forever. Safe to cancel."""
        if not self.is_configured():
            log.info(
                "SlackListener: SLACK_APP_TOKEN not set — two-way Slack disabled. "
                "See core/slack_listener.py for setup steps."
            )
            return

        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            log.error("SlackListener: slack_sdk not installed. Run: pip install slack_sdk aiohttp")
            return

        self._bot_user_id = await self._get_bot_user_id()
        log.info("SlackListener: bot user ID = %s", self._bot_user_id)
        self._jarvis_channel_id = await self._resolve_channel_id(
            os.environ.get("SLACK_JARVIS_CHANNEL", "").lstrip("#")
        )
        if self._jarvis_channel_id:
            log.info("SlackListener: dedicated channel ID = %s", self._jarvis_channel_id)

        web_client = AsyncWebClient(token=_bot_token())
        socket_client = SocketModeClient(
            app_token=_app_token(),
            web_client=web_client,
        )

        async def _process(client, req):
            """Acknowledge immediately, then handle async so Slack doesn't time out."""
            await client.send_socket_mode_response(
                __import__("slack_sdk.socket_mode.response", fromlist=["SocketModeResponse"])
                .SocketModeResponse(envelope_id=req.envelope_id)
            )
            if req.type == "events_api":
                asyncio.create_task(self._handle_event(req.payload))

        socket_client.socket_mode_request_listeners.append(_process)

        self._running = True
        log.info("SlackListener: connecting via Socket Mode…")
        await socket_client.connect()
        log.info("SlackListener: connected. JARVIS is now reachable on Slack.")

        try:
            while self._running:
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        finally:
            await socket_client.close()
            log.info("SlackListener: disconnected.")

    def stop(self) -> None:
        self._running = False


# Global singleton
slack_listener = SlackListener()
