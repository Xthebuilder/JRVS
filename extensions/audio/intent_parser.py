"""
IntentParser — maps natural language commands to structured intents.

Uses compiled regex patterns as the primary matching strategy (zero latency,
no extra model call).  Falls back to a simple LLM prompt for anything
ambiguous, returning a structured result that CommandExecutor can act on.

Supported intents and example phrasings:
  SWITCH_MODEL      "change model to gemma3:12b", "use llama3", "load mistral"
  LIST_MODELS       "show me what models you have", "list models"
  WEB_SEARCH        "search online for quantum computing", "look up rust ownership"
  SCRAPE_URL        "scrape https://...", "ingest this page https://..."
  SHOW_CALENDAR     "show my calendar", "what's on my schedule"
  SHOW_TODAY        "what's on today", "today's agenda"
  INGEST_ALL        "ingest all files", "process everything in uploads"
  INGEST_FILE       "ingest notes.txt"
  SHOW_STATS        "show stats", "system status"
  SHOW_HISTORY      "show conversation history"
  SET_THEME         "switch theme to cyberpunk"
  VISION_SCREEN     "switch to screen capture", "use desktop"
  VISION_CAMERA     "switch to camera", "use webcam"
  VISION_STATUS     "what are you seeing", "vision status"
  MUTE              "stop talking", "be quiet", "mute"
  HELP              "what commands can I use", "help"
  EXIT_MODE         "exit command mode", "cancel", "never mind"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Intent:
    name: str
    args: Dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Regex pattern registry
# Each entry: (intent_name, compiled_pattern)
# Patterns use named group (?P<arg>...) for the primary argument.
# ---------------------------------------------------------------------------

_RAW_PATTERNS: List[Tuple[str, str]] = [
    # ── Exit command mode (check FIRST so "cancel" doesn't match other things)
    ("EXIT_MODE",
     r"\b(exit|leave|cancel|never\s*mind|stop\s*command|quit\s*command)\b"),

    # ── Model management
    ("SWITCH_MODEL",
     r"\b(switch|change|use|load|set|run|activate|pick|select)\b.{0,20}"
     r"(model\s+(to|as|=)\s*|to\s+model\s+|to\s+)?(?P<arg>[\w./:-]{2,40})\b"),

    ("LIST_MODELS",
     r"\b(list|show|what|display)\b.{0,15}\b(models?|llms?|available)\b"),

    # ── Web search
    ("WEB_SEARCH",
     r"\b(search|websearch|look\s+up|google|find\s+online|search\s+the\s+web"
     r"|search\s+online|look\s+for\s+online)\b.{0,10}(?P<arg>.{3,})"),

    # ── Scrape URL
    ("SCRAPE_URL",
     r"\b(scrape|ingest|add|fetch|import|index)\b.{0,20}"
     r"(?P<arg>https?://\S+)"),

    # ── Calendar
    ("SHOW_TODAY",
     r"\b(today|what.{0,5}(on\s+today|today.{0,5}(schedule|agenda|events?|plan)))\b"),

    ("SHOW_CALENDAR",
     r"\b(calendar|schedule|events?|agenda|upcoming|what.{0,10}(this week|next|coming up))\b"),

    # ── File ingestion
    ("INGEST_ALL",
     r"\b(ingest|process|import|add)\b.{0,10}\b(all|everything)\b"),

    ("INGEST_FILE",
     r"\b(ingest|process|import|add|index)\b.{0,20}(?P<arg>[\w.-]+\.\w{2,5})\b"),

    # ── Stats / history
    ("SHOW_STATS",
     r"\b(stats?|statistics|system\s+status|how\s+are\s+you\s+doing|status)\b"),

    ("SHOW_HISTORY",
     r"\b(history|conversation\s+history|what\s+(did\s+we|have\s+we)\s+(talk|discuss|say))\b"),

    # ── Theme
    ("SET_THEME",
     r"\b(theme|appearance|look)\b.{0,15}(?P<arg>matrix|cyberpunk|minimal)\b"),

    # ── Vision
    ("VISION_SCREEN",
     r"\b(screen\s+capture|screen|desktop|display)\b.{0,30}"
     r"(vision|camera|capture|watch|see|view|look)?"
     r"|(switch|use|enable|activate).{0,15}(screen|desktop)"),

    ("VISION_CAMERA",
     r"\b(camera|webcam|droidcam|physical\s+camera)\b.{0,30}"
     r"(vision|capture|watch|see|view|look)?"
     r"|(switch|use|enable|activate).{0,15}(camera|webcam)"),

    ("VISION_STATUS",
     r"\b(what\s+(are|do)\s+you\s+see|what.{0,5}seeing|vision\s+status"
     r"|camera\s+status|show\s+me\s+what.{0,10}see)\b"),

    # ── Audio
    ("MUTE",
     r"\b(mute|stop\s+(talking|speaking)|be\s+quiet|silence\s+yourself|shut\s+up)\b"),

    # ── Help
    ("HELP",
     r"\b(help|what\s+commands?|what\s+can\s+you\s+do|command\s+list"
     r"|what\s+do\s+you\s+support)\b"),
]

_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (name, re.compile(pat, re.IGNORECASE | re.DOTALL))
    for name, pat in _RAW_PATTERNS
]

# Trigger phrases that activate command mode
_COMMAND_MODE_TRIGGERS = re.compile(
    r"\b(command\s+mode|enter\s+command\s+mode|jrvs\s+command\s+mode"
    r"|switch\s+to\s+command\s+mode|commands?)\b",
    re.IGNORECASE,
)


class IntentParser:
    """Classify free-form speech into structured intents via regex."""

    def parse(self, text: str) -> Optional[Intent]:
        """
        Return the best-matching Intent for the given text, or None if
        nothing matches (caller should treat as normal chat).
        """
        t = text.strip()
        for intent_name, pattern in _PATTERNS:
            m = pattern.search(t)
            if m:
                arg = ""
                try:
                    arg = m.group("arg").strip()
                except IndexError:
                    pass
                return Intent(
                    name=intent_name,
                    args={"arg": arg} if arg else {},
                    raw_text=t,
                )
        return None

    @staticmethod
    def is_command_mode_trigger(text: str) -> bool:
        """Return True if the utterance is asking to enter command mode."""
        return bool(_COMMAND_MODE_TRIGGERS.search(text.strip()))


# Module-level singleton
intent_parser = IntentParser()
