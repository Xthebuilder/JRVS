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


# ── Retry / backoff constants ────────────────────────────────────────────────
INIT_RETRY_BASE = 5        # first retry after 5s
INIT_RETRY_MAX  = 120      # cap at 2 minutes between retries
INIT_RETRY_LIMIT = None    # None = retry forever (systemd is the real watchdog)


async def _init_with_backoff(cli, max_attempts=INIT_RETRY_LIMIT) -> None:
    """Try cli.initialize() with exponential backoff until it succeeds.

    Ollama or the network may not be ready when systemd starts the unit,
    so we retry instead of dying on the first failure.
    """
    attempt = 0
    delay = INIT_RETRY_BASE
    while True:
        attempt += 1
        try:
            ok = await cli.initialize()
            if ok:
                return
            # initialize() returned False — component not ready
            raise RuntimeError("cli.initialize() returned False")
        except Exception as exc:
            if max_attempts and attempt >= max_attempts:
                log.error("Giving up after %d attempts: %s", attempt, exc)
                raise
            log.warning(
                "Initialization attempt %d failed (%s) — retrying in %ds…",
                attempt, exc, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, INIT_RETRY_MAX)


async def _supervise(name: str, coro_factory, *, max_backoff: int = 120):
    """Run coro_factory() in a loop, restarting on crash with backoff.

    coro_factory is a zero-arg callable that returns a fresh coroutine
    each time (we can't re-await a spent coroutine).
    """
    delay = 5
    while True:
        try:
            log.info("supervisor: starting %s", name)
            await coro_factory()
            # If the coroutine returns normally, it shut down cleanly
            log.info("supervisor: %s exited cleanly", name)
            return
        except asyncio.CancelledError:
            log.info("supervisor: %s cancelled", name)
            return
        except (Exception, SystemExit) as exc:
            # SystemExit is caught too: uvicorn calls sys.exit(1) directly on
            # a bind failure instead of raising a normal Exception. Left
            # uncaught, that propagates out of asyncio.run(main()) entirely,
            # which force-closes every other MCP stdio connection from the
            # wrong asyncio task during interpreter shutdown — the actual
            # source of the "cancel scope in a different task" errors.
            log.error(
                "supervisor: %s crashed (%s) — restarting in %ds…",
                name, exc, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_backoff)


async def main() -> None:
    log.info("JARVIS daemon starting…")

    # Initialize the CLI — this runs the exact same startup as the terminal
    from cli.interface import cli
    from llm.ollama_client import ollama_client

    cli.llm_client = ollama_client
    cli.llm_provider = "ollama"

    try:
        await _init_with_backoff(cli)
    except Exception:
        log.critical("JARVIS daemon could not initialize — exiting.")
        sys.exit(1)

    log.info("JARVIS CLI stack ready.")

    # ── Supervised background tasks ──────────────────────────────────────
    #
    # If uvicorn or the Slack listener crash, the supervisor restarts them
    # with exponential backoff rather than letting them die silently.

    # --- API server (uvicorn) ---
    import uvicorn
    from api.server import app
    from config import JRVS_SERVER_HOST, JRVS_SERVER_PORT

    def _make_uvicorn_coro():
        cfg = uvicorn.Config(
            app, host=JRVS_SERVER_HOST, port=JRVS_SERVER_PORT,
            log_level="warning", lifespan="off",
        )
        return uvicorn.Server(cfg).serve()

    supervised_tasks = []
    supervised_tasks.append(
        asyncio.create_task(
            _supervise("uvicorn", _make_uvicorn_coro),
            name="supervise-uvicorn",
        )
    )
    log.info("API server running on %s:%d (supervised)", JRVS_SERVER_HOST, JRVS_SERVER_PORT)

    # --- Slack listener ---
    # Slack is already started inside cli.initialize() via asyncio.create_task().
    # We replace that fire-and-forget task with a supervised one.
    from core.slack_listener import slack_listener
    if slack_listener.is_configured():
        # Stop the un-supervised task that cli.initialize() launched, then
        # re-launch under supervision. slack_listener.start() is idempotent —
        # it checks self._running and returns quickly if already connected.
        slack_listener.stop()
        await asyncio.sleep(0.5)   # let the old task notice _running=False

        supervised_tasks.append(
            asyncio.create_task(
                _supervise("slack-listener", slack_listener.start),
                name="supervise-slack",
            )
        )
        log.info("Slack two-way listener running (supervised)")
    else:
        log.info("Slack listener inactive — SLACK_APP_TOKEN not set.")

    # --- Autonomous Research (ResearchOS bridge) ---
    from autonomous_research import autonomous_researcher
    supervised_tasks.append(
        asyncio.create_task(
            _supervise("autonomous-research", autonomous_researcher.start),
            name="supervise-autonomous-research",
        )
    )
    log.info("Autonomous Research module running (supervised)")

    # --- Marketing Module ---
    from marketing_module import marketing_module
    supervised_tasks.append(
        asyncio.create_task(
            _supervise("marketing", marketing_module.start),
            name="supervise-marketing",
        )
    )
    log.info("Marketing module running (supervised)")

    # --- Image Generation Module (ComfyUI) ---
    from image_gen_module import image_gen_module
    supervised_tasks.append(
        asyncio.create_task(
            _supervise("image-gen", image_gen_module.start),
            name="supervise-image-gen",
        )
    )
    log.info("Image generation module running (supervised, ComfyUI at %s)", "http://127.0.0.1:8188")

    # Run forever — SIGTERM/SIGINT trigger graceful shutdown
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    log.info("JARVIS daemon ready.")
    await stop

    log.info("JARVIS daemon shutting down…")

    # Cancel supervised tasks so they don't restart during shutdown
    for t in supervised_tasks:
        t.cancel()
    await asyncio.gather(*supervised_tasks, return_exceptions=True)

    slack_listener.stop()
    await cli.cleanup()
    log.info("JARVIS daemon stopped.")


if __name__ == "__main__":
    asyncio.run(main())
