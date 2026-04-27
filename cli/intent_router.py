"""
intent_router.py — translate natural-language messages to /commands.

Returns a slash-command string (e.g. "/switch deepseek-r1:14b") when the
message clearly maps to one, or None to let the LLM handle it normally.

Design rules:
  • Only match when confidence is HIGH — false positives are more annoying
    than missing a shortcut.
  • Patterns are tried in order; first match wins.
  • Each entry is (compiled_regex, builder_fn).
    builder_fn(match, original_message) -> str  (the /command string)
"""
from __future__ import annotations

import re
from typing import Optional, Tuple, Callable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text)
    return m.group(0).rstrip(".,)>\"'") if m else None


def _rest_after(pattern: str, text: str) -> str:
    """Return everything after the first match of pattern (stripped)."""
    m = re.search(pattern, text, re.IGNORECASE)
    return text[m.end():].strip() if m else text.strip()


def _build_imagegen_intent(msg: str) -> str:
    """Extract image generation prompt from a natural-language request."""
    # Strip the trigger verb phrase and return the remainder as the prompt
    for pattern in (
        r"\b(generate|create|make|draw|render|paint)\b.{0,15}\b(an?\s+)?(image|picture|photo|illustration|artwork|drawing)\s+(of\s+)?",
        r"\b(imagine|visualize)\b.{0,10}\b(me\s+)?(a\s+)?",
    ):
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            prompt = msg[m.end():].strip().rstrip(".,!?")
            if prompt:
                return f"/imagegen generate {prompt}"
    return f"/imagegen generate {msg.strip()}"


def _build_marketing_intent(msg: str) -> str:
    """Extract brand, platform, and topic from a marketing request."""
    brand_m = re.search(r"\b(tensorlink|xthebuilder)\b", msg, re.IGNORECASE)
    brand = brand_m.group(0).lower() if brand_m else "xthebuilder"
    if re.search(r"\btweet\b", msg, re.IGNORECASE):
        platform = "twitter"
    else:
        plat_m = re.search(r"\b(linkedin|twitter|email)\b", msg, re.IGNORECASE)
        platform = plat_m.group(0).lower() if plat_m else "twitter"
    # Try topic-introducing keywords in priority order — "about" before "for"
    # so "write a post for TensorLink about X" correctly extracts X, not "TensorLink about X"
    topic = None
    for kw in (r"\babout\b", r"\bannouncing\b", r"\bregarding\b"):
        m_kw = re.search(kw, msg, re.IGNORECASE)
        if m_kw:
            candidate = msg[m_kw.end():].strip()
            if candidate:
                topic = candidate
                break
    if not topic:
        topic = msg.strip()
    return f"/marketing queue {brand} {platform} {topic}"


# ---------------------------------------------------------------------------
# Intent table
# Each tuple: (regex, builder)
# ---------------------------------------------------------------------------

_Route = Tuple[re.Pattern, Callable[[re.Match, str], str]]

_INTENTS: list[_Route] = [

    # ── models ──────────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(list|show|what|which|available)\b.{0,30}\bmodels?\b"
            r"|\bmodels?\b.{0,20}\b(available|do you have|loaded)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/models",
    ),

    # ── switch model ─────────────────────────────────────────────────────────
    # Require explicit "model/llm" keyword OR a bare model:tag token.
    # Plain "use X to do Y" must NOT fire — "to" alone is too ambiguous.
    (
        re.compile(
            r"\b(switch|change|swap)\b.{0,20}\b(model|llm)\b"           # switch/change/swap … model
            r"|\b(switch|change|use|load|swap)\b\s+(to\s+)?[a-z0-9._-]+:[a-z0-9._-]+"  # verb [to] model:tag
            r"|\buse\b.{0,10}\bmodel\b",                                 # "use [the] model X"
            re.IGNORECASE,
        ),
        lambda m, msg: (
            # Prefer the explicit model:tag token if present; fall back to
            # whatever follows "model [to]" for plain-English phrasing.
            "/switch " + (
                re.search(r"[a-z0-9._-]+:[a-z0-9._-]+", msg, re.IGNORECASE).group(0)
                if re.search(r"[a-z0-9._-]+:[a-z0-9._-]+", msg, re.IGNORECASE)
                else _rest_after(r"\b(model|llm)\s+(to\s+)?", msg)
            )
        ),
    ),

    # ── ytdl download ────────────────────────────────────────────────────────
    # Catch confirmation phrases like "go ahead and download", "download them now",
    # "send to the booth". URL downloads go through the MCP agent directly.
    (
        re.compile(
            r"\b(go\s+ahead|proceed|yes|do\s+it)\b.{0,40}\bdownload\b"
            r"|\bdownload\b.{0,25}\b(them|it|those|now|please|tracks?|songs?)\b"
            r"|\bsend.{0,20}\b(booth|ytdl)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/download",
    ),

    # ── calendar (upcoming / this week) ─────────────────────────────────────
    (
        re.compile(
            r"\b(show|open|check|view|what('s| is) on)\b.{0,25}\bcalendar\b"
            r"|\b(upcoming|next)\b.{0,15}\b(events?|appointments?|schedule)\b"
            r"|\bwhat do i have (this week|coming up|planned)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/calendar",
    ),

    # ── today's events ───────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(today'?s?|this morning|tonight)\b.{0,20}\b(events?|schedule|appointments?|plans?)\b"
            r"|\bwhat (do i have |is (on |scheduled )?)today\b"
            r"|\bam i (busy|free) today\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/today",
    ),

    # ── history ──────────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(show|view|see|display)\b.{0,20}\b(conversation|chat|message)\b.{0,10}\bhistory\b"
            r"|\bwhat (did|have) (i|we) (say|talk(ed)?|discuss(ed)?)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/history",
    ),

    # ── stats ────────────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(show|view|display|get)\b.{0,20}\b(session\s+)?stats?\b"
            r"|\bhow (much|many).{0,20}\b(tokens?|requests?|message)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/stats",
    ),

    # ── sources ──────────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(show|view|list|what|where)\b.{0,20}\b(sources?|urls?|links?|sites?)\b.{0,20}\b(from|used|searched|found)?\b"
            r"|\bwhere did you (search|find|get|look)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/sources",
    ),

    # ── scrape URL ───────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(scrape|ingest|add|fetch|read|import)\b.{0,30}https?://",
            re.IGNORECASE,
        ),
        lambda m, msg: "/scrape " + (_extract_url(msg) or ""),
    ),

    # ── search knowledge base ────────────────────────────────────────────────
    (
        re.compile(
            r"\b(search|look\s+in|find\s+in|query)\b.{0,30}"
            r"\b(my\s+)?(documents?|knowledge(\s+base)?|files?|notes?|database|memory)\b"
            r"|\b(what (do you know|have you stored|did i tell you))\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/search " + _rest_after(
            r"\b(search|look\s+in|find\s+in|query)\b.{0,30}"
            r"\b(my\s+)?(documents?|knowledge(\s+base)?|files?|notes?|database|memory)\b\s*(for\s+)?",
            msg,
        ),
    ),

    # ── agent / MCP report ───────────────────────────────────────────────────
    (
        re.compile(
            r"\b(show|view|display|get)\b.{0,20}\b(agent|mcp|tool)\b.{0,10}\breport\b"
            r"|\bwhat (tools|mcp).{0,20}\b(used|called|ran|executed)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/report",
    ),

    # ── MCP servers ──────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(list|show|what)\b.{0,20}\bmcp\b.{0,15}\b(servers?|connected|available)\b"
            r"|\bwhat (mcp servers?|servers? are connected)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/mcp-servers",
    ),

    # ── MCP tools ────────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(list|show|what)\b.{0,20}\bmcp\b.{0,15}\btools?\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/mcp-tools",
    ),

    # ── upload list ──────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(list|show|what|view)\b.{0,20}\b(upload(ed|s)?|files? (i('ve)?|you) (upload|have))\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/upload list",
    ),

    # ── clear screen ─────────────────────────────────────────────────────────
    (
        re.compile(
            r"^(clear|cls|clear (the )?(screen|chat|terminal))$",
            re.IGNORECASE,
        ),
        lambda m, msg: "/clear",
    ),

    # ── help ─────────────────────────────────────────────────────────────────
    (
        re.compile(
            r"^(help|commands?|what can you do)$"
            r"|\b(show|list)\b.{0,15}\b(commands?|help)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/help",
    ),

    # ── gmail search ─────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(search|find|look\s+(through|in))\b.{0,20}\b(my\s+)?(emails?|gmail|inbox)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/gmail search " + _rest_after(
            r"\b(search|find|look\s+(through|in))\b.{0,20}\b(my\s+)?(emails?|gmail|inbox)\b\s*(for\s+)?",
            msg,
        ),
    ),

    # ── code generate ────────────────────────────────────────────────────────
    (
        re.compile(
            r"\b(generate|write|create)\b.{0,20}\b(python|javascript|typescript|bash|go|rust|java|c\+\+|sql)\b.{0,40}\bcode\b"
            r"|\bcode\b.{0,10}\b(generate|for)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: (
            "/code generate "
            + (m.group(0).strip() if m.lastindex and m.group(0) else "python")
            + " "
            + msg
        ),
    ),

    # ── brave search status ──────────────────────────────────────────────────
    (
        re.compile(
            r"\b(brave|search)\b.{0,15}\b(status|quota|remaining|budget|limit)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: "/brave-status",
    ),

    # ── image generation ─────────────────────────────────────────────────────
    # Fires on clear image-gen requests. Placed before marketing so that
    # "generate an image of the tensorlink logo" goes here, not marketing.
    # Does NOT fire on "generate python code" — code-generate pattern is earlier.
    (
        re.compile(
            r"\b(generate|create|make|draw|render|paint)\b.{0,15}"
            r"\b(an?\s+)?(image|picture|photo|illustration|artwork|drawing)\b"
            r"|\b(imagine|visualize)\b.{0,20}\b(of|showing|with|a\b)",
            re.IGNORECASE,
        ),
        lambda m, msg: _build_imagegen_intent(msg),
    ),

    # ── marketing draft ──────────────────────────────────────────────────────
    # Only fires when both a known brand and a known platform are mentioned.
    (
        re.compile(
            r"\b(write|generate|draft|create)\b.{0,20}"
            r"\b(linkedin\s+post|tweet|twitter\s+post|email)\b"
            r".{0,40}\b(tensorlink|xthebuilder)\b"
            r"|\b(tensorlink|xthebuilder)\b.{0,30}"
            r"\b(linkedin|twitter|tweet|email)\b.{0,20}"
            r"\b(post|copy|draft|content|campaign)\b",
            re.IGNORECASE,
        ),
        lambda m, msg: _build_marketing_intent(msg),
    ),

]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_command_intent(message: str) -> Optional[str]:
    """
    Return a /command string if the message clearly maps to one, else None.

    Skips detection if the message is very short (likely a follow-up) or
    already starts with '/'.
    """
    stripped = message.strip()

    # Already a command or too short to meaningfully parse
    if stripped.startswith("/") or len(stripped) < 3:
        return None

    for pattern, builder in _INTENTS:
        m = pattern.search(stripped)
        if m:
            cmd = builder(m, stripped).strip()
            # Don't return a command with an empty required argument
            parts = cmd.split(None, 1)
            if len(parts) == 1:
                return cmd  # no-arg command — always valid
            if parts[1]:
                return cmd  # has argument — valid
            # Argument expected but empty: skip (fall through to LLM)

    return None
