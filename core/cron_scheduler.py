"""
JRVS Cron Scheduler — natural language scheduling with approve/deny workflow.

Flow:
  1. User says: /schedule every weekday at 9am check my emails
  2. LLM parses → cron expression + action description
  3. Job stored as status=pending in scheduled_jobs table
  4. User sees: "Pending: <description> — /approve <id> or /deny <id>"
  5. /approve <id>  → status=active, fires on cron schedule
  6. /deny <id>     → status=denied, archived
  7. Every execution is logged to schedule_log table

Cron expressions use standard 5-field format: min hour dom mon dow
Examples:
  0 9 * * 1-5   = weekdays at 9am
  0 8 * * *     = every day at 8am
  0 * * * *     = every hour
  30 17 * * 5   = Fridays at 5:30pm
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import textwrap
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiosqlite
from croniter import croniter

from config import DATABASE_PATH

log = logging.getLogger(__name__)

_DB = str(DATABASE_PATH)

# ── LLM prompt for parsing natural language into a scheduled job ──────────────
_PARSE_SYSTEM = textwrap.dedent("""\
    You are a scheduling assistant for JARVIS.
    Parse the user's scheduling request into a structured JSON job definition.

    Respond ONLY with valid JSON — no markdown, no explanation:
    {
      "description": "plain English description of what will happen and when",
      "action":      "imperative instruction JARVIS will execute each time",
      "cron":        "5-field cron expression (min hour dom mon dow)",
      "human_schedule": "human-readable schedule, e.g. 'every weekday at 9:00 AM'"
    }

    Cron format reference:
      0 9 * * 1-5   = weekdays at 9am
      0 8 * * *     = every day at 8am
      0 * * * *     = every hour on the hour
      0 12 * * *    = every day at noon
      30 17 * * 5   = every Friday at 5:30pm
      0 8 * * 1     = every Monday at 8am
      0 9,17 * * *  = every day at 9am and 5pm
      */30 * * * *  = every 30 minutes

    Rules:
    - action must be a clear, executable instruction starting with a verb.
    - If no time is specified, default to 9:00 AM.
    - If no day is specified, default to every day.
    - description should be friendly and readable, mentioning both what and when.
""")


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_tables() -> None:
    async with aiosqlite.connect(_DB) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id           TEXT PRIMARY KEY,
                description  TEXT NOT NULL,
                action       TEXT NOT NULL,
                cron         TEXT NOT NULL,
                human_schedule TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                created_at   INTEGER NOT NULL,
                approved_at  INTEGER,
                denied_at    INTEGER,
                last_run     INTEGER,
                next_run     INTEGER,
                run_count    INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id    TEXT NOT NULL,
                ran_at    INTEGER NOT NULL,
                result    TEXT,
                success   INTEGER NOT NULL DEFAULT 1,
                duration_ms INTEGER
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedule_log_job ON schedule_log(job_id)"
        )
        await db.commit()


async def _insert_job(job: Dict[str, Any]) -> None:
    async with aiosqlite.connect(_DB) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute(
            """INSERT INTO scheduled_jobs
               (id, description, action, cron, human_schedule, status, created_at, next_run)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                job["id"], job["description"], job["action"],
                job["cron"], job.get("human_schedule", ""),
                int(datetime.now().timestamp()),
                int(_next_run(job["cron"])),
            ),
        )
        await db.commit()


async def _insert_job_direct(
    *,
    job_id: str,
    description: str,
    action: str,
    cron: str,
    human_schedule: str = "",
    status: str = "pending",
) -> None:
    async with aiosqlite.connect(_DB) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute(
            """INSERT INTO scheduled_jobs
               (id, description, action, cron, human_schedule, status, created_at, next_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                description,
                action,
                cron,
                human_schedule,
                status,
                int(datetime.now().timestamp()),
                int(_next_run(cron)),
            ),
        )
        await db.commit()


async def _set_status(job_id: str, status: str) -> bool:
    col = "approved_at" if status == "active" else "denied_at"
    async with aiosqlite.connect(_DB) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        cur = await db.execute(
            f"UPDATE scheduled_jobs SET status=?, {col}=? WHERE id=?",
            (status, int(datetime.now().timestamp()), job_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def _get_job(job_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(_DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def _get_all_jobs(status: Optional[str] = None) -> List[Dict]:
    async with aiosqlite.connect(_DB) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cur = await db.execute(
                "SELECT * FROM scheduled_jobs WHERE status=? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM scheduled_jobs ORDER BY created_at DESC"
            )
        return [dict(r) for r in await cur.fetchall()]


async def _get_due_jobs() -> List[Dict]:
    now = int(datetime.now().timestamp())
    async with aiosqlite.connect(_DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM scheduled_jobs WHERE status='active' AND next_run <= ?",
            (now,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def _mark_ran(job_id: str, result: str, success: bool, duration_ms: float) -> None:
    now = int(datetime.now().timestamp())
    async with aiosqlite.connect(_DB) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        # Get cron to compute next run
        cur = await db.execute(
            "SELECT cron FROM scheduled_jobs WHERE id=?", (job_id,)
        )
        row = await cur.fetchone()
        cron_expr = row[0] if row else "0 9 * * *"
        nxt = int(_next_run(cron_expr))
        await db.execute(
            """UPDATE scheduled_jobs
               SET last_run=?, next_run=?, run_count=run_count+1
               WHERE id=?""",
            (now, nxt, job_id),
        )
        await db.execute(
            """INSERT INTO schedule_log (job_id, ran_at, result, success, duration_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (job_id, now, result[:2000], int(success), int(duration_ms)),
        )
        await db.commit()


async def _get_log(job_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
    async with aiosqlite.connect(_DB) as db:
        db.row_factory = aiosqlite.Row
        if job_id:
            cur = await db.execute(
                "SELECT * FROM schedule_log WHERE job_id=? ORDER BY ran_at DESC LIMIT ?",
                (job_id, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM schedule_log ORDER BY ran_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cur.fetchall()]


def _next_run(cron_expr: str) -> float:
    try:
        it = croniter(cron_expr, datetime.now())
        return it.get_next(float)
    except Exception:
        return datetime.now().timestamp() + 86400


# ── Scheduler class ───────────────────────────────────────────────────────────

class CronScheduler:
    """DB-backed cron scheduler with approve/deny workflow."""

    def __init__(self) -> None:
        self._llm_client = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._notify: Optional[Callable[[str], None]] = None
        self._active_jobs = set()

    def set_llm_client(self, client) -> None:
        self._llm_client = client

    def set_notify(self, callback: Callable[[str], None]) -> None:
        """Wire a callback so the scheduler can print to the CLI."""
        self._notify = callback

    def _print(self, msg: str) -> None:
        if self._notify:
            self._notify(msg)
        else:
            log.info(msg)

    # ── Parse natural language ────────────────────────────────────────────────

    async def parse_schedule(self, text: str) -> Optional[Dict[str, Any]]:
        """Use LLM to parse natural language into a job definition."""
        if self._llm_client is None:
            return None
        try:
            raw = await self._llm_client.generate(
                prompt=f"Scheduling request: {text.strip()[:500]}",
                context="",
                stream=False,
                system_prompt=_PARSE_SYSTEM,
            )
        except Exception as exc:
            log.error("CronScheduler.parse_schedule: LLM error: %s", exc)
            return None

        if not raw:
            return None

        json_text = re.sub(r"```[^\n]*\n?|```", "", raw).strip()
        try:
            parsed = json.loads(json_text)
        except (ValueError, TypeError):
            log.warning("CronScheduler: JSON parse failed: %r", raw[:200])
            return None

        required = ("description", "action", "cron")
        if not all(parsed.get(k) for k in required):
            return None

        # Validate cron expression
        try:
            croniter(parsed["cron"])
        except Exception:
            log.warning("CronScheduler: invalid cron %r", parsed.get("cron"))
            return None

        parsed["id"] = str(uuid.uuid4())[:8]
        return parsed

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_pending(self, text: str) -> Optional[Dict]:
        """Parse text and store as pending job. Returns job dict or None."""
        await _ensure_tables()
        job = await self.parse_schedule(text)
        if not job:
            return None
        await _insert_job(job)
        log.info("CronScheduler: created pending job %s: %s", job["id"], job["description"])
        return job

    async def create_pending_job(
        self,
        *,
        description: str,
        action: str,
        cron: str,
        human_schedule: str = "",
    ) -> Dict[str, Any]:
        """Create a pending schedule directly without LLM parsing."""
        await _ensure_tables()
        try:
            croniter(cron)
        except Exception as exc:
            raise ValueError(f"Invalid cron expression: {cron}") from exc

        job = {
            "id": str(uuid.uuid4())[:8],
            "description": description,
            "action": action,
            "cron": cron,
            "human_schedule": human_schedule,
            "status": "pending",
        }
        await _insert_job_direct(
            job_id=job["id"],
            description=description,
            action=action,
            cron=cron,
            human_schedule=human_schedule,
            status="pending",
        )
        return job

    async def approve(self, job_id: str) -> bool:
        await _ensure_tables()
        ok = await _set_status(job_id, "active")
        if ok:
            log.info("CronScheduler: job %s approved", job_id)
        return ok

    async def deny(self, job_id: str) -> bool:
        await _ensure_tables()
        ok = await _set_status(job_id, "denied")
        if ok:
            log.info("CronScheduler: job %s denied", job_id)
        return ok

    async def pause(self, job_id: str) -> bool:
        await _ensure_tables()
        return await _set_status(job_id, "paused")

    async def resume(self, job_id: str) -> bool:
        await _ensure_tables()
        return await _set_status(job_id, "active")

    async def delete(self, job_id: str) -> bool:
        await _ensure_tables()
        async with aiosqlite.connect(_DB) as db:
            await db.execute("PRAGMA journal_mode = WAL")
            cur = await db.execute(
                "DELETE FROM scheduled_jobs WHERE id=?", (job_id,)
            )
            await db.commit()
            return cur.rowcount > 0

    async def list_jobs(self, status: Optional[str] = None) -> List[Dict]:
        await _ensure_tables()
        return await _get_all_jobs(status)

    async def get_log(self, job_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
        await _ensure_tables()
        return await _get_log(job_id, limit)

    async def get_pending(self) -> List[Dict]:
        await _ensure_tables()
        return await _get_all_jobs("pending")

    # ── Background loop ───────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        await _ensure_tables()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="cron-scheduler")
        log.info("CronScheduler started.")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                due = await _get_due_jobs()
                for job in due:
                    if job["id"] in self._active_jobs:
                        continue
                    self._active_jobs.add(job["id"])
                    asyncio.create_task(self._run_job(job))
            except Exception as exc:
                log.error("CronScheduler loop error: %s", exc)
            await asyncio.sleep(30)  # check every 30s

    async def _run_job(self, job: Dict) -> None:
        await _ensure_tables()
        job_id = job["id"]
        action = job["action"]
        start = datetime.now()
        log.info("CronScheduler: running job %s: %s", job_id, action[:80])

        try:
            if action.startswith("guardian_brief_report:"):
                payload = json.loads(action.split(":", 1)[1])
                days = int(payload.get("days", 1))
                topic = str(payload.get("topic", ""))
                limit = int(payload.get("limit", 150))

                from guardian_module import guardian_module
                report = await guardian_module.generate_and_save_report(
                    days=days,
                    topic=topic,
                    limit=limit,
                )
                result = (
                    f"Guardian brief generated ({report.get('articles_analyzed', 0)} articles). "
                    f"Report: {report.get('report_url', '')}"
                )
                duration_ms = (datetime.now() - start).total_seconds() * 1000
                await _mark_ran(job_id, result, True, duration_ms)

                summary = (
                    f"\n[Scheduled job '{job_id}' ran] {job['description']}\n"
                    f"Report saved: {report.get('report_path', '')}"
                )
                self._print(summary)

                from core.slack_notifier import notify_async
                md_url = report.get('report_url', '')
                html_url = report.get('html_report_url', '')
                links = f"📄 <{md_url}|Markdown> | 🌐 <{html_url}|HTML>"
                await notify_async(
                    f":newspaper: *Guardian brief generated* — _{job['description']}_\n"
                    f"{links}",
                    channel_key="research",
                )
                return

            if self._llm_client is None:
                raise RuntimeError("LLM client not configured for generic scheduled action")

            from mcp_gateway.agent import mcp_agent
            agent_result = await mcp_agent.process_request(action)

            context_parts = []
            for tr in agent_result.get("tool_results", []):
                if tr.get("success") and tr.get("result"):
                    context_parts.append(
                        f"Tool {tr['server']}/{tr['tool']}:\n{str(tr['result'])[:2000]}"
                    )

            response = await self._llm_client.generate(
                prompt=action,
                context="\n\n".join(context_parts),
                stream=False,
                system_prompt=(
                    "You are JARVIS executing a scheduled action. "
                    "Be concise. Return a 1-3 sentence summary of what was done."
                ),
            )

            duration_ms = (datetime.now() - start).total_seconds() * 1000
            result = response or "Completed (no output)."
            await _mark_ran(job_id, result, True, duration_ms)

            summary = (
                f"\n[Scheduled job '{job_id}' ran] {job['description']}\n"
                f"Result: {result[:300]}"
            )
            self._print(summary)

            from core.slack_notifier import notify_async
            await notify_async(
                f":white_check_mark: *Scheduled job ran* — _{job['description']}_\n{result[:300]}",
                channel_key="schedule",
            )

        except Exception as exc:
            duration_ms = (datetime.now() - start).total_seconds() * 1000
            await _mark_ran(job_id, str(exc), False, duration_ms)
            log.error("CronScheduler: job %s failed: %s", job_id, exc)

            from core.slack_notifier import notify_async
            await notify_async(
                f":x: *Scheduled job failed* — _{job['description']}_\nError: {exc}",
                channel_key="alerts",
            )
        finally:
            self._active_jobs.discard(job_id)


# Global singleton
cron_scheduler = CronScheduler()
