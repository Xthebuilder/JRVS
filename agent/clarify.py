"""
Ambiguity gate — know when not to act.

The agent resolved ambiguity by guessing confidently. "make it get macdonalds"
was read across runs as an event title, as a task to email McDonald's, and as a
logo image to generate. Three interpretations of one phrase, never a question,
even though a Slack channel to the user was open the whole time.

This gate runs before planning and asks one thing: would a reasonable person
need to check before doing this? If so the goal is parked and a single question
goes back to the user, rather than an irreversible guess.

Deliberately conservative. A gate that asks about everything is worse than one
that never asks, so it only fires when the answer would genuinely change what
gets done — not for detail a sensible default already covers.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

_CLARIFY_SYSTEM = """\
You screen requests for genuine ambiguity before an assistant acts on them.

Answer with valid JSON only — no markdown, no explanation:
{"is_ambiguous": true|false,
 "changes_outcome": true|false,
 "question": "one short question to the user, empty string if none"}

is_ambiguous — could a careful person reasonably read this request in two
different ways that lead to DIFFERENT actions?

changes_outcome — would the answer actually change what gets done? Missing
detail that a sensible default covers does NOT count. "Book lunch tomorrow"
with no time is not ambiguous — pick a sensible time. "Send it to Chris" when
two people are called Chris IS ambiguous. "Add an event and make it get
groceries" is ambiguous: "get groceries" could be the event's title or a
separate task.

Never ask about optional extras the request did not mention — inviting people,
reminders, notifications, locations, durations. Their absence is not ambiguity,
and the assistant has no tool for most of them. "Dinner with Sam" is the title;
it is not a question about whether to invite Sam.

A request that already states its title explicitly ("called X", "titled X",
"named X") together with a date or time has ONE reading. Answer false.

ALWAYS ask when the action is destructive or irreversible — delete, remove,
cancel, overwrite, send, pay — and the target is not precisely identified.
"Delete the old files" names no specific files, so it must be questioned. The
risks are not symmetric: an unnecessary question costs seconds, a wrong
deletion cannot be undone.

Both must be true to ask. Otherwise, asking needlessly is annoying and slow, so
when the request has one obvious reading, answer false.

The question must be ONE short sentence offering the likely readings.
"""


def _parse(raw: str) -> Optional[dict]:
    text = re.sub(r"```[^\n]*\n?|```", "", (raw or "")).strip()
    candidates = [text]
    match = re.search(r"(\{[\s\S]*\})", text)
    if match:
        candidates.append(match.group(1))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None


async def needs_clarification(
    request: str,
    backend,
    planner_kwargs: Optional[dict] = None,
) -> tuple[bool, str]:
    """
    Decide whether *request* should be questioned before acting.

    Returns (should_ask, question). Fails closed to acting: if the gate errors
    or returns nonsense the request proceeds, because a broken screener must
    never make the assistant unresponsive.
    """
    text = (request or "").strip()
    if len(text.split()) < 3:
        return False, ""

    try:
        raw = await backend.chat(
            messages=[
                {"role": "system", "content": _CLARIFY_SYSTEM},
                {"role": "user", "content": f"Request: {text}\n\nAnswer with the JSON object only."},
            ],
            **(planner_kwargs or {}),
        )
    except Exception as exc:
        log.warning("needs_clarification: gate failed (%s) — proceeding without asking", exc)
        return False, ""

    verdict = _parse(raw)
    if verdict is None:
        log.debug("needs_clarification: unparseable verdict %r", (raw or "")[:120])
        return False, ""

    ambiguous = bool(verdict.get("is_ambiguous"))
    changes = bool(verdict.get("changes_outcome"))
    question = str(verdict.get("question") or "").strip()

    if ambiguous and changes and question:
        return True, question
    return False, ""


# ── Pending questions ────────────────────────────────────────────────────────
# A parked request, keyed by conversation. Kept in memory: an unanswered
# question is only meaningful inside the conversation that raised it, and one
# that outlives a restart would arrive with no context for the user.

_PENDING: dict[str, str] = {}


def park(session_id: str, request: str) -> None:
    _PENDING[session_id] = request


def take_pending(session_id: str) -> Optional[str]:
    """Pop the parked request for this conversation, if any."""
    return _PENDING.pop(session_id, None)


def has_pending(session_id: str) -> bool:
    return session_id in _PENDING


def combine(original: str, answer: str) -> str:
    """Fold the user's answer back into the original request."""
    return f"{original.strip()}\n\n(clarification from the user: {answer.strip()})"
