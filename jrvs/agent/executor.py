"""
JRVS Agent — Tier-aware action executor.

Each plan step is dispatched here.  The tier determines whether the
action runs immediately (AUTO/NOTIFY) or is queued for human approval
(CONFIRM) or rejected outright (BLOCKED).

Tool dispatch is split into two backends:
  • Google tools  → GoogleAgent._execute()
  • YouTube / NLP → local analytics wrappers
  • web_search    → BraveSearchClient / YouTubeSearchClient (if available)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Tier constants ────────────────────────────────────────────────────────────
AUTO    = "auto"
NOTIFY  = "notify"
CONFIRM = "confirm"
BLOCKED = "blocked"

# Canonical tier for every known tool (executor is the source of truth)
TIER_MAP: dict[str, str] = {
    # ── AUTO ─────────────────────────────────────────────────────────────
    "gmail_list":              AUTO,
    "gmail_search":            AUTO,
    "gmail_read":              AUTO,
    "gmail_labels":            AUTO,
    "docs_list":               AUTO,
    "docs_read":               AUTO,
    "docs_find":               AUTO,
    "sheets_list":             AUTO,
    "sheets_read":             AUTO,
    "sheets_find":             AUTO,
    "sheets_info":             AUTO,
    "calendar_list_calendars": AUTO,
    "calendar_events":         AUTO,
    "calendar_find":           AUTO,
    "youtube_analyze":         AUTO,
    "youtube_outliers":        AUTO,
    "youtube_growth":          AUTO,
    "web_search":              AUTO,
    # ── NOTIFY ───────────────────────────────────────────────────────────
    "docs_create":             NOTIFY,
    "docs_append":             NOTIFY,
    "docs_replace":            NOTIFY,
    "sheets_write":            NOTIFY,
    "sheets_append":           NOTIFY,
    "sheets_create":           NOTIFY,
    "sheets_clear":            NOTIFY,
    "calendar_create":         NOTIFY,
    "calendar_update":         NOTIFY,
    # ── CONFIRM ───────────────────────────────────────────────────────────
    "gmail_send":              CONFIRM,
    "gmail_reply":             CONFIRM,
    "calendar_delete":         CONFIRM,
}


class Executor:
    """Execute a single plan step according to its security tier."""

    def __init__(self, db=None, google_agent=None, dry_run: bool = False) -> None:
        from jrvs.storage.database import Database
        self._db = db or Database()
        self._ga = google_agent  # lazy-loaded on first Google call
        self._dry_run = dry_run
        self._google_tools = {k for k, v in TIER_MAP.items()
                              if k.startswith(("gmail_", "docs_", "sheets_", "calendar_"))}

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_step(
        self,
        step: dict[str, Any],
        run_id: str,
        goal_tier_override: str | None = None,
        *,
        step_results: dict[int, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one plan step and return a result dict.

        Parameters
        ----------
        step               : Plan step dict from Planner.plan().
        run_id             : Parent run UUID.
        goal_tier_override : If the goal specifies a more restrictive tier
                             (e.g. "notify"), that caps execution.
        step_results       : Map of step_number → result from earlier steps,
                             used by _resolve_args() to fill placeholders.
        """
        tool  = step.get("tool", "")
        args  = step.get("args", {})
        step_n = step.get("step", 0)
        reason = step.get("reason", "")

        # Resolve placeholder references like "<result_from_step_1>"
        if step_results:
            args = _resolve_args(args, step_results)

        # Determine effective tier
        tool_tier    = TIER_MAP.get(tool, CONFIRM)
        goal_tier    = goal_tier_override or tool_tier
        eff_tier     = _max_tier(tool_tier, goal_tier)

        import json as _json

        action_id = str(uuid.uuid4())
        action_row = {
            "action_id":   action_id,
            "run_id":      run_id,
            "step":        step_n,
            "tool":        tool,
            "args_json":   _json.dumps(args),
            "tier":        eff_tier,
            "reason":      reason,
            "status":      "pending",
            "result_json": None,
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }

        if eff_tier == BLOCKED:
            log.warning("Step %d blocked: tool '%s' is blocked by policy", step_n, tool)
            action_row["status"] = "blocked"
            self._db.upsert_agent_action(action_row)
            return {"action_id": action_id, "status": "blocked", "result": None}

        if self._dry_run:
            action_row["status"] = "dry_run"
            self._db.upsert_agent_action(action_row)
            return {"action_id": action_id, "status": "dry_run", "result": None,
                    "tier": eff_tier, "tool": tool, "args": args}

        if eff_tier == CONFIRM:
            # Queue and send approval email
            action_row["status"] = "awaiting_approval"
            self._db.upsert_agent_action(action_row)
            self._send_approval_request(action_row)
            return {"action_id": action_id, "status": "awaiting_approval", "result": None}

        # AUTO or NOTIFY — execute immediately
        try:
            result = self._dispatch(tool, args)
            action_row["status"] = "success"
            action_row["result_json"] = _truncate(str(result), 2000)
            self._db.upsert_agent_action(action_row)
            log.info("Step %d [%s] %s — OK", step_n, eff_tier.upper(), tool)
            return {"action_id": action_id, "status": "success", "result": result,
                    "tier": eff_tier, "tool": tool}
        except Exception as exc:
            action_row["status"] = "error"
            action_row["result_json"] = str(exc)[:500]
            self._db.upsert_agent_action(action_row)
            log.error("Step %d [%s] %s failed: %s", step_n, eff_tier.upper(), tool, exc)
            return {"action_id": action_id, "status": "error", "error": str(exc)}

    def execute_approved(self, action_id: str) -> dict[str, Any]:
        """Execute a CONFIRM-tier action that has been approved by the user."""
        row = self._db.get_action(action_id)
        if not row:
            return {"error": "action not found"}
        if row["status"] not in ("awaiting_approval", "approved"):
            return {"error": f"cannot execute action in status '{row['status']}'"}

        import json as _json
        args = _json.loads(row["args_json"]) if row["args_json"] else {}
        tool = row["tool"]
        try:
            result = self._dispatch(tool, args)
            self._db.approve_action(action_id)
            self._db.upsert_agent_action({**row, "status": "success",
                                          "result_json": _truncate(str(result), 2000)})
            return {"action_id": action_id, "status": "success", "result": result}
        except Exception as exc:
            self._db.upsert_agent_action({**row, "status": "error",
                                          "result_json": str(exc)[:500]})
            return {"action_id": action_id, "status": "error", "error": str(exc)}

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, tool: str, args: dict[str, Any]) -> Any:
        if tool in self._google_tools:
            return self._google_execute(tool, args)
        if tool.startswith("youtube_"):
            return self._youtube_execute(tool, args)
        if tool == "web_search":
            return self._web_search_execute(args)
        raise ValueError(f"Unknown tool: {tool}")

    def _google_execute(self, tool: str, args: dict[str, Any]) -> Any:
        """Delegate to GoogleAgent._execute()."""
        ga = self._get_google_agent()
        return ga._execute([{"name": tool, "args": args}])

    def _youtube_execute(self, tool: str, args: dict[str, Any]) -> Any:
        """Direct calls into JRVS analytics layer."""
        channel_id = args.get("channel_id", "")
        if tool == "youtube_analyze":
            from jrvs.analytics.channel import ChannelAnalytics
            ca = ChannelAnalytics()
            return ca.analyse(channel_id)
        if tool == "youtube_outliers":
            from jrvs.analytics.outliers import OutlierDetector
            od = OutlierDetector()
            return od.detect(channel_id)
        if tool == "youtube_growth":
            from jrvs.analytics.timeseries import TimeSeriesAnalyzer
            ts = TimeSeriesAnalyzer()
            return ts.growth(channel_id)
        raise ValueError(f"Unknown youtube tool: {tool}")

    def _web_search_execute(self, args: dict[str, Any]) -> Any:
        query = args.get("query", "")
        try:
            from jrvs.ingestion.brave_client import BraveSearchClient
            client = BraveSearchClient()
            return client.search(query)
        except ImportError:
            pass
        return {"error": "web_search not available — install brave_client"}

    def _get_google_agent(self):
        if self._ga is None:
            from jrvs.google.google_agent import GoogleAgent
            self._ga = GoogleAgent()
        return self._ga

    # ── Approval notification ─────────────────────────────────────────────────

    def _send_approval_request(self, action: dict[str, Any]) -> None:
        from jrvs.config import Config
        notify_email = Config.AGENT_NOTIFY_EMAIL
        if not notify_email:
            log.info("CONFIRM action queued (%s) — no AGENT_NOTIFY_EMAIL set",
                     action["action_id"])
            return
        subject = f"[JRVS] Approval needed: {action['tool']} (run {action['run_id'][:8]})"
        body = (
            f"A JRVS agent action requires your approval.\n\n"
            f"Tool  : {action['tool']}\n"
            f"Args  : {action['args_json']}\n"
            f"Reason: {action['reason']}\n"
            f"ID    : {action['action_id']}\n\n"
            f"To approve:\n  jrvs agent approve {action['action_id']}\n"
            f"To deny:\n  jrvs agent deny {action['action_id']}\n"
        )
        try:
            ga = self._get_google_agent()
            ga._execute([{
                "name": "gmail_send",
                "args": {"to": notify_email, "subject": subject, "body": body},
            }])
        except Exception as exc:
            log.warning("Could not send approval email: %s", exc)


# ── Utilities ─────────────────────────────────────────────────────────────────

_TIER_ORDER = {AUTO: 0, NOTIFY: 1, CONFIRM: 2, BLOCKED: 3}


def _max_tier(a: str, b: str) -> str:
    """Return the more restrictive of two tier strings."""
    return a if _TIER_ORDER.get(a, 2) >= _TIER_ORDER.get(b, 2) else b


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _resolve_args(args: dict[str, Any], step_results: dict[int, Any]) -> dict[str, Any]:
    """Replace '<result_from_step_N>' placeholders with actual step results."""
    import re
    resolved = {}
    for k, v in args.items():
        if isinstance(v, str):
            m = re.fullmatch(r"<result_from_step_(\d+)>", v.strip())
            if m:
                n = int(m.group(1))
                v = step_results.get(n, v)
        resolved[k] = v
    return resolved
