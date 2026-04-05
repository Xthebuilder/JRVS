"""
JRVS voice client — full-duplex conversation loop.

Connects to the JRVS API server and provides:
  • Sentence-level streaming TTS (first word spoken before LLM finishes)
  • Thinking-phrase filler while JRVS generates a response
  • Barge-in interruption (speak over JRVS mid-sentence)
  • Command mode (say "command mode" to access system commands)
  • Auto-reconnect with exponential backoff on connection loss

Start the API server first:
  venv/bin/python api/server.py

Then run this client:
  venv/bin/python voice.py
"""
import asyncio
import itertools
import json
import logging
import sys

import aiohttp

sys.path.insert(0, ".")

from extensions.audio import AudioModule
from extensions.audio.intent_parser import intent_parser
from extensions.audio.command_executor import CommandExecutor
from extensions.audio.command_mode import CommandMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from config import JRVS_SERVER_HOST, JRVS_SERVER_PORT

_base = f"{JRVS_SERVER_HOST}:{JRVS_SERVER_PORT}"
JRVS_WS_URL       = f"ws://{_base}/ws/voice"
JRVS_HTTP_URL      = f"http://{_base}/api/chat"
JRVS_FEEDBACK_URL  = f"http://{_base}/api/feedback"
SESSION_ID = "voice"

# Tracks the last exchange so "that was wrong" can reference it
_last_qa: dict = {"question": "", "response": ""}

_THINKING_PHRASES = itertools.cycle([
    "Let me think.",
    "One moment.",
    "Sure.",
    "Hmm, let me check.",
    "Got it.",
    "Looking into that.",
])


async def _check_server_ready(url: str, timeout: float = 5.0) -> bool:
    """Return True if the JRVS API server is reachable."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url + "/health",
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as r:
                return r.status < 500
    except Exception:
        return False


async def main() -> None:
    # Verify the API server is running before entering the retry loop, so the
    # user gets a clear error instead of silent 30-second retry cycles.
    if not await _check_server_ready(JRVS_HTTP_URL.rsplit("/api/chat", 1)[0]):
        logger.error(
            "JRVS API server is not running at %s.\n"
            "Start it first:  python api/server.py\n"
            "Or use the combined launcher:  ./start_jrvs.sh --voice",
            JRVS_HTTP_URL,
        )
        return

    audio = AudioModule()
    await audio.initialize()

    # HTTP fallback for command-mode UNKNOWN intents (no streaming needed)
    async def ask_jrvs_http(text: str) -> str:
        try:
            async with aiohttp.ClientSession() as s:
                r = await s.post(
                    JRVS_HTTP_URL,
                    json={"message": text, "session_id": SESSION_ID, "voice": True},
                    timeout=aiohttp.ClientTimeout(total=60),
                )
                d = await r.json()
                return d.get("response", "Sorry, I had trouble with that.")
        except Exception as exc:
            logger.error("HTTP fallback error: %s", exc)
            return "I couldn't reach the server right now."

    # Build command mode machinery
    executor = CommandExecutor(on_input=ask_jrvs_http)
    cmd_mode = CommandMode(
        executor=executor,
        listen_fn=audio.listen,
        speak_fn=audio.speak,
        multi_command=audio._cfg.cmd_multi_command,
        command_timeout=audio._cfg.cmd_timeout,
    )

    await audio.speak("Ready. Go ahead.")

    retry_delay = 1.0
    max_retry_delay = 30.0

    while True:
        try:
            async with aiohttp.ClientSession() as http:
                async with http.ws_connect(
                    JRVS_WS_URL,
                    timeout=aiohttp.ClientTimeout(total=None, connect=10),
                    heartbeat=20,  # send pings every 20 s; keeps connection alive while listening
                ) as ws:
                    retry_delay = 1.0  # reset on successful connection
                    logger.info("Connected to JRVS voice stream.")

                    while True:
                        # ── Listen for user speech ────────────────────────────
                        user_text = await audio.listen()
                        if not user_text:
                            continue

                        logger.info("You: %s", user_text)

                        # ── Feedback intent — flag last response as bad ───────
                        intent = intent_parser.parse(user_text)
                        if intent and intent.name == "FEEDBACK_BAD":
                            if _last_qa["question"]:
                                try:
                                    async with aiohttp.ClientSession() as s:
                                        await s.post(JRVS_FEEDBACK_URL, json={
                                            "question": _last_qa["question"],
                                            "response": _last_qa["response"],
                                        })
                                except Exception:
                                    pass
                                await audio.speak("Got it, I'll learn from that.")
                                logger.info("Feedback logged for: %s", _last_qa["question"][:60])
                            else:
                                await audio.speak("No previous response to flag.")
                            continue

                        # ── Command mode trigger ──────────────────────────────
                        if intent_parser.is_command_mode_trigger(user_text):
                            await cmd_mode.run()
                            continue

                        # ── Track question for feedback ───────────────────────
                        _last_qa["question"] = user_text
                        _last_qa["response"] = ""

                        # ── Send to JRVS via streaming WS ────────────────────
                        await ws.send_json(
                            {"message": user_text, "session_id": SESSION_ID}
                        )

                        # Start a thinking-phrase task (fires after 1.2 s)
                        async def _thinking() -> None:
                            await asyncio.sleep(1.2)
                            await audio.speak(next(_THINKING_PHRASES))

                        thinking_task = asyncio.create_task(_thinking())
                        first_sentence = True

                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)

                                    if data.get("type") == "sentence":
                                        sentence = data["content"]

                                        # Cancel thinking phrase before first real sentence
                                        if first_sentence:
                                            first_sentence = False
                                            if not thinking_task.done():
                                                audio._tts.stop_speaking()
                                                thinking_task.cancel()
                                                try:
                                                    await thinking_task
                                                except (asyncio.CancelledError, Exception):
                                                    pass
                                                await asyncio.sleep(0.05)

                                        logger.info("JRVS: %s", sentence)
                                        _last_qa["response"] += sentence + " "
                                        await audio.speak(sentence)

                                    elif data.get("type") == "done":
                                        _last_qa["response"] = _last_qa["response"].strip()
                                        break

                                elif msg.type in (
                                    aiohttp.WSMsgType.CLOSED,
                                    aiohttp.WSMsgType.ERROR,
                                ):
                                    raise aiohttp.ClientConnectionError(
                                        "WebSocket closed unexpectedly"
                                    )
                        finally:
                            # Clean up thinking task if response arrived fast
                            if not thinking_task.done():
                                thinking_task.cancel()
                                try:
                                    await thinking_task
                                except (asyncio.CancelledError, Exception):
                                    pass

        except (
            aiohttp.ClientConnectorError,
            aiohttp.ClientConnectionError,
            aiohttp.ServerDisconnectedError,
            OSError,
        ) as exc:
            logger.warning(
                "Connection lost (%s). Retrying in %.0f s…", exc, retry_delay
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)

        except Exception as exc:
            logger.error("Unexpected error: %s", exc, exc_info=True)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)


asyncio.run(main())
