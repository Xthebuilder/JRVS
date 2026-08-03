"""
JARVIS Terminal Client — thin client that connects to the daemon.

Sends every message to the daemon's /api/chat/full endpoint.
The daemon owns all resources (GPU, MCP, RAG) — this process is just UI.

Usage: python cli/terminal_client.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from core.logging_setup import setup_logging
setup_logging()

from cli.themes import theme
import os
from config import JRVS_SERVER_HOST, JRVS_SERVER_PORT


DAEMON_URL = os.environ.get("JRVS_DAEMON_URL", f"http://{JRVS_SERVER_HOST}:{JRVS_SERVER_PORT}")
SESSION_ID = str(uuid.uuid4())

# Commands this thin client knows how to send. "/help" is handled locally
# (see main()) rather than being forwarded — forwarding it used to send the
# literal string "/help" to the LLM chat pipeline, which isn't a real command
# there and made the model improvise a fake back-and-forth instead of answering.
_HELP_COMMANDS = {
    "/help": "Show this help message",
    "/exit, /quit, /q": "Exit JARVIS",
    "/google-auth": "Authenticate with Google (OAuth2)",
    "<anything else>": "Chat normally — JARVIS handles calendar, search, "
                        "email, and other requests in plain language",
}


async def _wait_for_daemon(timeout: int = 30) -> bool:
    """Wait until the daemon's API is ready."""
    import aiohttp
    for i in range(timeout):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{DAEMON_URL}/api/google/status", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status in (200, 503):
                        return True
        except Exception:
            pass
        if i == 0:
            theme.print_status("Waiting for JARVIS daemon…", "info")
        await asyncio.sleep(1)
    return False


async def send_message(message: str) -> str:
    """POST a message to the daemon and return the response."""
    import aiohttp
    payload = {"message": message, "session_id": SESSION_ID}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{DAEMON_URL}/api/chat/full",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 503:
                    return "JARVIS is still starting up — try again in a moment."
                if resp.status != 200:
                    text = await resp.text()
                    return f"Error {resp.status}: {text[:200]}"
                data = await resp.json()
                return data.get("response", "No response.")
    except asyncio.TimeoutError:
        return "Request timed out — JARVIS may be busy."
    except Exception as exc:
        return f"Connection error: {exc}"


async def forward_command(cmd: str) -> None:
    """
    Some commands need the daemon process (e.g. /google-auth opens a browser).
    Send them as special messages so the daemon handles them.
    """
    import aiohttp
    payload = {"message": f"/{cmd}", "session_id": SESSION_ID}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{DAEMON_URL}/api/chat/full",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
                theme.print_response(data.get("response", ""))
    except Exception as exc:
        theme.print_error(f"Command error: {exc}")


async def handle_google_auth() -> None:
    """Interactive Google OAuth2 flow via the daemon API."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{DAEMON_URL}/api/google/auth-url", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 503:
                    theme.print_error("Google credentials not configured in .env")
                    return
                data = await resp.json()
                url = data.get("url")

        theme.print_status("Google OAuth2 Authorization", "info")
        theme.console.print("\nVisit this URL in your browser:")
        theme.console.print(f"\n  [bright_cyan]{url}[/]\n")
        theme.console.print("After authorizing, paste the code shown and press Enter:")

        code = input("  Authorization code: ").strip()
        if not code:
            theme.print_warning("No code entered — cancelled.")
            return

        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{DAEMON_URL}/api/google/auth",
                json={"code": code},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                if resp.status == 200:
                    theme.print_success("Authenticated with Google!")
                else:
                    theme.print_error(f"Auth failed: {data.get('detail', 'unknown error')}")

    except Exception as exc:
        theme.print_error(f"Google auth error: {exc}")


async def main() -> None:
    import signal

    theme.clear_screen()
    theme.print_banner()

    # Make sure daemon is up
    ready = await _wait_for_daemon()
    if not ready:
        theme.print_error("JARVIS daemon is not running. Start it with: jrvs-start")
        sys.exit(1)

    theme.print_success("Connected to JARVIS daemon.")
    theme.print_separator()
    theme.print_info("Type '/help' for commands or start chatting!")
    theme.print_separator()

    running = True

    def _handle_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while running:
        try:
            user_input = theme.print_prompt("jarvis")
            if not user_input or not user_input.strip():
                continue

            text = user_input.strip()

            if text.lower() in ("/exit", "/quit", "/q"):
                break

            # Handle /help locally — don't forward it, the daemon has no such
            # command and would otherwise hand the literal text to the LLM.
            if text.lower() == "/help":
                theme.print_help(_HELP_COMMANDS)
                continue

            # Handle /google-auth interactively — needs URL + code input
            if text.lower() == "/google-auth":
                await handle_google_auth()
                continue

            with theme.show_progress("Thinking…") as progress:
                task = progress.add_task("", total=None)
                response = await send_message(text)

            theme.print_response(response)

        except KeyboardInterrupt:
            if theme.confirm("Exit?"):
                break
        except EOFError:
            break
        except Exception as exc:
            theme.print_error(f"Error: {exc}")

    theme.print_status("Goodbye.", "info")


if __name__ == "__main__":
    asyncio.run(main())
