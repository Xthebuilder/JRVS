"""
Slack notification helper for JRVS.

Sends messages to dedicated Slack channels based on domain.
When confidence in channel routing is below SLACK_ROUTE_CONFIDENCE (default 0.65),
messages fall back to #jarvis-general.

Channels (configure in .env):
  SLACK_CHANNEL_INBOX     — Gmail, email, drafts
  SLACK_CHANNEL_CALENDAR  — Calendar, daily brief, end-of-day
  SLACK_CHANNEL_RESEARCH  — Web search, trends, YouTube reports
  SLACK_CHANNEL_SCHEDULE  — Cron job completions
  SLACK_CHANNEL_ALERTS    — Errors and failures
  SLACK_CHANNEL_GENERAL   — Low-confidence / catch-all
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

_API_URL = "https://slack.com/api/chat.postMessage"

# Maps channel keys → env var names
CHANNEL_KEYS = {
    "inbox":    "SLACK_CHANNEL_INBOX",
    "calendar": "SLACK_CHANNEL_CALENDAR",
    "research": "SLACK_CHANNEL_RESEARCH",
    "schedule": "SLACK_CHANNEL_SCHEDULE",
    "alerts":   "SLACK_CHANNEL_ALERTS",
    "general":  "SLACK_CHANNEL_GENERAL",
}

# Keywords used to score which channel a piece of text belongs to
_CHANNEL_KEYWORDS: dict[str, list[str]] = {
    "inbox": [
        "gmail", "email", "inbox", "unread", "reply", "draft",
        "sender", "message", "mail", "urgent", "flagged", "subject",
    ],
    "calendar": [
        "calendar", "event", "meeting", "schedule", "today", "tomorrow",
        "brief", "end of day", "appointment", "conflict", "block", "daily",
    ],
    "research": [
        "research", "trend", "youtube", "web search", "article", "ai tools",
        "content strategy", "report", "findings", "search", "study", "weekly",
    ],
    "schedule": [
        "cron", "scheduled job", "job ran", "task ran", "job completed",
        "ran at", "next run", "recurring",
    ],
    "alerts": [
        "error", "failed", "exception", "traceback", "crash", "timeout",
        "unauthorized", "forbidden", "not found",
    ],
}


# Keywords are matched on a leading word boundary but no trailing one, so
# "email" matches "emails" and "meeting" matches "meetings", while "mail"
# still does NOT match inside "gmail" or "email" (no boundary mid-word).
# Each entry is (pattern, weight). A multi-word phrase ("end of day", "job
# completed") is far more specific than a bare word ("today", "report"), so a
# single phrase match is worth full evidence on its own.
_KEYWORD_PATTERNS: dict[str, list[tuple[re.Pattern, int]]] = {
    channel: [
        (re.compile(r"\b" + re.escape(kw)), 2 if " " in kw else 1)
        for kw in keywords
    ]
    for channel, keywords in _CHANNEL_KEYWORDS.items()
}

# Distinct keyword hits needed before a channel is credited with full
# confidence. One stray word ("today", "report") should not win a channel on
# its own; two independent terms from the same domain is real evidence.
_FULL_EVIDENCE_HITS = 2


def _confidence_route(text: str) -> tuple[str, float]:
    """
    Score *text* against each channel's keywords.
    Returns (channel_key, confidence) where confidence is in [0, 1].
    Falls back to 'general' if the best score is below the threshold.

    Confidence combines two independent signals rather than one overloaded
    score. A channel wins only if it satisfies both:

      dominance — how decisively it beat the runner-up, best/(best+second).
                  Ties give 0.5; an uncontested match gives 1.0.
      evidence  — the weight of the keywords it matched, capped at
                  _FULL_EVIDENCE_HITS. Guards against a single common word.

    The earlier version scored hits/len(keywords), i.e. the fraction of a
    channel's whole vocabulary present in the message. With ~12 keywords per
    channel and a 0.65 threshold that demanded 8 distinct keywords in one
    message, so realistic notifications always fell through to 'general'.
    """
    threshold = float(os.environ.get("SLACK_ROUTE_CONFIDENCE", "0.65"))
    lower = text.lower()

    hits: dict[str, int] = {
        channel: sum(weight for pat, weight in patterns if pat.search(lower))
        for channel, patterns in _KEYWORD_PATTERNS.items()
    }

    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    best_channel, best_hits = ranked[0]
    runner_up_hits = ranked[1][1] if len(ranked) > 1 else 0

    if best_hits == 0:
        return "general", 0.0

    dominance = best_hits / (best_hits + runner_up_hits)
    evidence = min(1.0, best_hits / _FULL_EVIDENCE_HITS)
    confidence = dominance * evidence

    if confidence < threshold:
        return "general", confidence

    return best_channel, confidence


def get_channel(key: str) -> str:
    """Return the Slack channel name for a given key (e.g. 'inbox')."""
    env_var = CHANNEL_KEYS.get(key, "SLACK_CHANNEL_GENERAL")
    return os.environ.get(env_var, f"#jarvis-{key}")


def notify(text: str, channel_key: Optional[str] = None) -> bool:
    """
    Send *text* to the appropriate Slack channel.

    If *channel_key* is provided and is a known key, use it directly.
    Otherwise, auto-route based on content confidence. If confidence < threshold,
    sends to #jarvis-general.

    Returns True on success, False on any error (never raises).
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token or token.startswith("xoxb-YOUR"):
        log.debug("slack_notifier: no token configured, skipping.")
        return False

    if channel_key and channel_key in CHANNEL_KEYS:
        resolved_key = channel_key
        confidence = 1.0
    else:
        resolved_key, confidence = _confidence_route(text)

    channel = get_channel(resolved_key)
    log.debug("slack_notifier: routing to '%s' (confidence=%.2f)", channel, confidence)

    payload = json.dumps({"channel": channel, "text": text}).encode()

    try:
        req = urllib.request.Request(
            _API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())

        if not result.get("ok"):
            log.warning(
                "slack_notifier: Slack API error on channel '%s': %s",
                channel, result.get("error"),
            )
            return False

        return True

    except Exception as exc:
        log.warning("slack_notifier: failed to send message: %s", exc)
        return False


async def notify_async(text: str, channel_key: Optional[str] = None) -> bool:
    """Async wrapper — runs notify() in a thread so it doesn't block the event loop."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: notify(text, channel_key)
    )


def send_approval_request(
    action_id: str,
    tool: str,
    args: dict,
    reason: str,
    goal_id: str,
    channel_key: Optional[str] = None,
) -> dict:
    """
    Post an interactive Slack Block Kit message with Approve / Deny buttons.

    Returns {"ts": message_timestamp, "channel": channel_id} on success,
    or {"ts": "", "channel": ""} on failure.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token or token.startswith("xoxb-YOUR"):
        log.debug("slack_notifier: no token configured, skipping approval request.")
        return {"ts": "", "channel": ""}

    resolved_key = channel_key or "alerts"
    channel = get_channel(resolved_key)

    args_text = json.dumps(args, indent=2) if args else "{}"
    if len(args_text) > 400:
        args_text = args_text[:400] + "\n…"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":bell: JARVIS Approval Needed", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Tool:*\n`{tool}`"},
                {"type": "mrkdwn", "text": f"*Goal:*\n`{goal_id}`"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reason:*\n{reason or 'No reason provided'}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Arguments:*\n```{args_text}```"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                    "style": "primary",
                    "action_id": f"approve_{action_id}",
                    "value": action_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Deny", "emoji": True},
                    "style": "danger",
                    "action_id": f"deny_{action_id}",
                    "value": action_id,
                },
            ],
        },
    ]

    payload = json.dumps({"channel": channel, "blocks": blocks}).encode()
    try:
        req = urllib.request.Request(
            _API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())

        if not result.get("ok"):
            log.warning("slack_notifier: approval post failed: %s", result.get("error"))
            return {"ts": "", "channel": ""}

        return {"ts": result.get("ts", ""), "channel": result.get("channel", "")}
    except Exception as exc:
        log.warning("slack_notifier: failed to send approval request: %s", exc)
        return {"ts": "", "channel": ""}


async def send_approval_request_async(
    action_id: str,
    tool: str,
    args: dict,
    reason: str,
    goal_id: str,
    channel_key: Optional[str] = None,
) -> dict:
    """Async wrapper for send_approval_request."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: send_approval_request(action_id, tool, args, reason, goal_id, channel_key),
    )
