#!/usr/bin/env python3
"""
JARVIS Daemon — headless background service.

Initializes the exact same CLI stack as the terminal, then wires
Slack messages directly into it. No separate pipeline — whatever
works in the terminal works in Slack.

Start via systemd:  systemctl --user start jarvis
Or directly:        python jarvis_daemon.py
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from core.logging_setup import setup_logging
setup_logging()
log = logging.getLogger("jarvis.daemon")


async def main() -> None:
    log.info("JARVIS daemon starting…")

    # Initialize the CLI — this runs the exact same startup as the terminal
    from cli.interface import cli
    from llm.ollama_client import ollama_client

    cli.llm_client = ollama_client
    cli.llm_provider = "ollama"

    ok = await cli.initialize()
    if not ok:
        log.error("CLI initialization failed — check Ollama is running")
        sys.exit(1)

    log.info("JARVIS CLI stack ready.")

    # Start API server (non-blocking)
    import uvicorn
    from api.server import app
    uv_config = uvicorn.Config(
        app, host="127.0.0.1", port=8000,
        log_level="warning", lifespan="off",
    )
    uv_server = uvicorn.Server(uv_config)
    asyncio.create_task(uv_server.serve())
    log.info("API server running on :8000")

    # Wire Slack listener directly to the CLI's chat handler
    from core.slack_listener import slack_listener
    if slack_listener.is_configured():
        slack_listener.set_handler(cli.handle_chat_message_for_slack)
        asyncio.create_task(slack_listener.start())
        log.info("Slack two-way listener started.")
    else:
        log.info("Slack listener inactive — SLACK_APP_TOKEN not set.")

    # Run forever — SIGTERM/SIGINT trigger graceful shutdown
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    log.info("JARVIS daemon ready.")
    await stop

    log.info("JARVIS daemon shutting down…")
    slack_listener.stop()
    await cli.cleanup()
    log.info("JARVIS daemon stopped.")


if __name__ == "__main__":
    asyncio.run(main())
