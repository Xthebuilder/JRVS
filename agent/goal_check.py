"""
Goal-level satisfaction check — the outer half of the agent loop.

agent/verification.py answers "did this tool do what it was told". That is the
inner loop, and it passes happily when the planner was told the wrong thing:
asked for an event at 6pm, a planner that decided on an all-day event produces
an all-day event, and per-step verification confirms it matches the arguments
it was given. The user still did not get what they asked for.

This module asks the other question — "did the user get what they asked for" —
against the user's original words and the evidence of what actually happened.

The verdict is several narrow yes/no fields that must all agree, never one
overloaded confidence score. A single score does not survive a model swap: a
threshold tuned on one local model reads completely differently on another,
which has already bitten this codebase once (see the sense-proposal gate).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

SATISFIED   = "satisfied"
GAP         = "gap"          # demonstrably did not do what was asked
INDETERMINATE = "indeterminate"  # could not tell; treated as not satisfied

_CHECK_SYSTEM = """\
You audit whether an assistant actually did what the user asked.

You are given the user's original request and the evidence of what was really
done — the tools that ran, the arguments they ran with, and whether each was
independently verified against the live system.

Judge ONLY from the evidence. The assistant's own claim of success is not
evidence. A step marked "unverified" was never confirmed to have happened.

Answer with valid JSON only — no markdown, no explanation:
{"action_performed": true|false,
 "matches_request": true|false,
 "missing": "what is still wrong or absent, empty string if nothing"}

action_performed — did a tool actually carry out the requested action (not just
read, search, or list)? Reading the calendar is not creating an event.

matches_request — do the specifics match what the user asked for? Check every
concrete detail the user gave: the exact date, the exact time, the title, the
recipient, the content. An event on the right day at the wrong time does NOT
match. An all-day event when a clock time was requested does NOT match.

Both must be true for the request to be satisfied. When unsure, answer false —
wrongly claiming success is far worse than running one more step.
"""


def _parse_verdict(raw: str) -> Optional[dict]:
    text = re.sub(r"```[^\n]*\n?|```", "", (raw or "")).strip()
    for candidate in (text, (re.search(r"(\{[\s\S]*\})", text) or [None, None])[0] if re.search(r"(\{[\s\S]*\})", text) else None):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def format_evidence(step_results: dict, plan: list) -> str:
    """Render what actually happened, including verification status per step.

    Deliberately terse and factual — this is the only thing the auditor sees,
    so anything omitted here cannot be judged.
    """
    by_step = {s.step: s for s in plan}
    lines = []
    for step_no in sorted(step_results):
        outcome = step_results[step_no] or {}
        spec = by_step.get(step_no)
        tool = getattr(spec, "tool", "?")
        args = getattr(spec, "args", {}) or {}
        status = outcome.get("status", "?")
        verif = outcome.get("verification", "n/a")
        args_text = json.dumps(args, default=str)
        if len(args_text) > 300:
            args_text = args_text[:300] + "…"
        lines.append(
            f"- {tool} args={args_text} -> status={status}, verification={verif}"
        )
    return "\n".join(lines) or "(no steps ran)"


async def check_goal_satisfied(
    request: str,
    evidence: str,
    backend,
    planner_kwargs: Optional[dict] = None,
) -> tuple[str, str]:
    """
    Decide whether *request* was actually fulfilled. Returns (status, missing).

    status is SATISFIED, GAP, or INDETERMINATE. Anything other than SATISFIED
    means the goal is not done — an unreadable or failed audit is never
    upgraded to success.
    """
    user_msg = (
        f"User's original request:\n{request.strip()}\n\n"
        f"Evidence of what was actually done:\n{evidence}\n\n"
        "Was the user's request fulfilled? Answer with the JSON object only."
    )
    try:
        raw = await backend.chat(
            messages=[
                {"role": "system", "content": _CHECK_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            **(planner_kwargs or {}),
        )
    except Exception as exc:
        log.warning("check_goal_satisfied: audit call failed: %s", exc)
        return INDETERMINATE, f"could not audit the outcome: {exc}"

    verdict = _parse_verdict(raw)
    if verdict is None:
        log.warning("check_goal_satisfied: unparseable verdict %r", (raw or "")[:160])
        return INDETERMINATE, "the outcome audit could not be parsed"

    performed = bool(verdict.get("action_performed"))
    matches = bool(verdict.get("matches_request"))
    missing = str(verdict.get("missing") or "").strip()

    if performed and matches:
        return SATISFIED, ""

    if not missing:
        missing = (
            "the requested action was not carried out"
            if not performed
            else "the result does not match the details of the request"
        )
    return GAP, missing
