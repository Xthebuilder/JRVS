"""
CommandMode — the state machine that runs when the user enters command mode.

Flow:
  1. User says wake word → speaks "command mode" (or configured trigger)
  2. CommandMode.acknowledge() → speaks one of several rotating phrases
  3. User speaks a command → IntentParser classifies it
  4. CommandExecutor runs the intent → returns a natural-language result
  5. AudioModule speaks the result
  6. Stays in command mode for another command (configurable)
  7. Exits when user says "exit", "cancel", "never mind", or after timeout

Acknowledgment phrases rotate so the interaction never feels robotic.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Awaitable, Callable, List, Optional

from extensions.audio.intent_parser import Intent, IntentParser, intent_parser
from extensions.audio.command_executor import CommandExecutor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rotating acknowledgment phrases — cycles so it never repeats consecutively
# ---------------------------------------------------------------------------
_ACK_PHRASES = itertools.cycle([
    "Waiting for your command, sir.",
    "Ready. What shall I do?",
    "Command mode active. Go ahead.",
    "At your service. What do you need?",
    "Standing by for your instruction.",
    "Yes? State your command.",
    "Listening. What would you like me to do?",
])

_MULTI_ACK_PHRASES = itertools.cycle([
    "Anything else?",
    "What else can I do for you?",
    "Next command?",
    "Go ahead.",
    "Ready for the next one.",
])

_EXIT_PHRASES = itertools.cycle([
    "Exiting command mode. Back to normal.",
    "Understood. I'll stand by.",
    "Command mode off.",
    "Returning to standby.",
])


class CommandMode:
    """
    Manages command mode: acknowledgment, intent parsing, execution, and exit.
    """

    def __init__(
        self,
        executor: CommandExecutor,
        listen_fn: Callable[[], Awaitable[Optional[str]]],
        speak_fn: Callable[[str], Awaitable[None]],
        multi_command: bool = True,
        command_timeout: float = 10.0,
    ) -> None:
        """
        Args:
            executor:        CommandExecutor instance
            listen_fn:       Coroutine that records one utterance → str | None
            speak_fn:        Coroutine that speaks a string
            multi_command:   Stay in command mode for multiple commands
            command_timeout: Seconds to wait for a command before auto-exiting
        """
        self._executor = executor
        self._listen = listen_fn
        self._speak = speak_fn
        self._multi = multi_command
        self._timeout = command_timeout
        self._in_mode = False
        self._muted = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Enter command mode: acknowledge, then process commands until exit.
        Called by AudioModule when it detects the command mode trigger phrase.
        """
        self._in_mode = True
        logger.info("Command mode entered.")

        # First acknowledgment
        await self._speak(next(_ACK_PHRASES))

        while self._in_mode:
            # Listen for the next command (with timeout)
            text = await self._listen_with_timeout()

            if text is None:
                # Timeout — auto-exit
                await self._speak("No command received. Returning to standby.")
                break

            text = text.strip()
            logger.info("Command mode heard: %s", text)

            # Check for exit request
            intent = intent_parser.parse(text)
            if intent and intent.name == "EXIT_MODE":
                await self._speak(next(_EXIT_PHRASES))
                break

            # Check for mute/unmute
            if intent and intent.name == "MUTE":
                self._muted = True
                await self._speak("Muted. Say 'unmute' when you want me to speak again.")
                continue

            if intent and intent.name == "UNMUTE":
                self._muted = False
                await self._speak("I'm speaking again. Go ahead.")
                continue

            # Execute the intent (or fall through to chat if unrecognised)
            if intent:
                result = await self._executor.execute(intent)
            else:
                # No regex match — ask JRVS via normal chat fallback
                result = await self._executor.execute(
                    Intent(name="UNKNOWN", raw_text=text)
                )

            if result and not self._muted:
                await self._speak(result)

            # Multi-command: ask for next unless we just exited
            if not self._multi or not self._in_mode:
                break

            await self._speak(next(_MULTI_ACK_PHRASES))

        self._in_mode = False
        logger.info("Command mode exited.")

    @property
    def active(self) -> bool:
        return self._in_mode

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _listen_with_timeout(self) -> Optional[str]:
        """Listen for an utterance; return None on timeout."""
        try:
            return await asyncio.wait_for(self._listen(), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.debug("Command mode listen timed out after %.1fs", self._timeout)
            return None
