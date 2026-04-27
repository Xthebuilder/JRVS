"""
Autonomous Research Module — bridges JRVS ↔ ResearchOS.

Flow:
    1. Gap detection (LLM) → structured topic + reason + ETA
    2. Slack approval gate (Block Kit buttons, 4-hour timeout)
    3. Headless ResearchOS dispatch (asyncio subprocess, stdout streamed to Slack)
    4. Strategic compilation (LLM extracts Leverage / Opportunity Cost / Synergy)
    5. RAG ingestion (tagged type:strategic_insight)
    6. Final Slack summary (threaded reply to the approval message)

Hooked into jarvis_daemon.py as a _supervise()d task. Triggered by:
    - queue_topic(topic, ...)  — called from Slack commands or chat analysis
    - evaluate_knowledge_gap(text) — detects gaps in any text input
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.autonomous_research")


# ── Configuration ────────────────────────────────────────────────────────────
RESEARCH_OS_DIR = Path(
    os.environ.get("RESEARCH_OS_DIR", "/home/xavier/Desktop/reddit-research")
)
HEADLESS_SCRIPT = RESEARCH_OS_DIR / "headless.py"
RESEARCH_OS_PYTHON = Path(
    os.environ.get("RESEARCH_OS_PYTHON", RESEARCH_OS_DIR / ".venv" / "bin" / "python")
)

# Slack approval timeout — 4 hours
APPROVAL_TIMEOUT_S = int(os.environ.get("RESEARCH_APPROVAL_TIMEOUT", str(4 * 60 * 60)))
# ResearchOS subprocess hard timeout — 20 minutes (gap analysis + summaries can be long)
RESEARCH_SUBPROCESS_TIMEOUT_S = int(os.environ.get("RESEARCH_SUBPROCESS_TIMEOUT", "1200"))
# Don't post every stdout line to Slack — throttle status updates
SLACK_STATUS_INTERVAL_S = 15

# ── Prompts ──────────────────────────────────────────────────────────────────
_GAP_DETECTION_PROMPT = """\
You are a Knowledge Gap Analyst for a personal AI system belonging to a \
Linux sysadmin / AI hobbyist who runs a self-hosted homelab (Ollama, ZFS, \
Proxmox, Docker, Slack bots, FAISS-based RAG).

Given the text below, decide whether it references a specific technical \
concept, tool, technique, or workflow that would be strategically valuable \
to research in depth for the operator's knowledge base.

Output ONLY a valid JSON object with one of these two forms:

If a gap exists:
{
  "gap": true,
  "topic": "<specific researchable topic, 3-8 words>",
  "reason": "<1 sentence: why this is strategically useful for the operator>",
  "estimated_time": "<e.g. 'approx. 3-5 minutes' or 'approx. 8-12 minutes'>",
  "suggested_subreddits": ["sub1", "sub2", "sub3"]
}

If no gap:
{
  "gap": false
}

Return NO markdown fences, NO commentary — only the JSON object."""


_STRATEGIC_COMPILER_PROMPT = """\
You are a Strategic Intelligence Analyst embedded in a personal AI system.

You have been given a research report compiled from Reddit, web sources, \
and AI-driven analysis. Distill it into actionable Strategic Utility for \
the operator — a Linux sysadmin and AI hobbyist with a self-hosted homelab.

Output ONLY a valid JSON object with these keys:

{
  "topic": "<research topic>",
  "leverage_points": "<The 1% workflow win — specific tool, flag, config, or mental model>",
  "opportunity_cost": "<What the operator gives up by adopting this — time, lock-in, complexity, alternatives>",
  "cross_project_synergy": "<How this connects to existing stack: Ollama, JRVS, FAISS, Docker, ZFS, systemd, Proxmox>",
  "one_line_summary": "<Single sentence capturing the key leverage point>"
}

Return NO markdown fences, NO commentary — only the JSON object."""


# ── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class ResearchJob:
    topic: str
    reason: str = ""
    estimated_time: str = "approx. 5 minutes"
    subreddits: list[str] = field(default_factory=list)
    source: str = "manual"  # "manual" | "chat_analysis" | "cron"
    session_id: Optional[str] = None  # Slack session for threading
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Main class ───────────────────────────────────────────────────────────────
class AutonomousResearcher:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[ResearchJob] = asyncio.Queue()
        self._ollama = None
        self._rag = None
        self._initialized = False

        # Approval state: action_id -> (Event, verdict_slot)
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_verdicts: dict[str, bool] = {}
        # action_id -> {"channel": ..., "ts": ...} for progress updates
        self._approval_slack_refs: dict[str, dict] = {}
        # action_id -> topic (for logging)
        self._approval_topics: dict[str, str] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Main loop — consumes the queue. Designed for _supervise()."""
        from llm.ollama_client import ollama_client
        from rag.retriever import rag_retriever

        self._ollama = ollama_client
        self._rag = rag_retriever
        await self._rag.initialize()

        if not HEADLESS_SCRIPT.exists():
            log.warning(
                "Headless script not found at %s — queued jobs will fail",
                HEADLESS_SCRIPT,
            )
        if not RESEARCH_OS_PYTHON.exists():
            log.warning(
                "ResearchOS python not found at %s — falling back to sys.executable",
                RESEARCH_OS_PYTHON,
            )

        self._initialized = True
        log.info(
            "AutonomousResearcher ready — queue size=%d, approval_timeout=%ds",
            self._queue.qsize(), APPROVAL_TIMEOUT_S,
        )

        while True:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                raise
            try:
                log.info("Processing job: %r (source=%s)", job.topic, job.source)
                await self._process_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("Research job %s failed: %s", job.job_id[:8], exc)
                await self._notify_error(job, str(exc))
            finally:
                self._queue.task_done()

    # ── Public API — callable from outside ───────────────────────────────

    async def queue_topic(
        self,
        topic: str,
        reason: str = "",
        estimated_time: str = "approx. 5 minutes",
        subreddits: Optional[list[str]] = None,
        source: str = "manual",
    ) -> str:
        """Queue a research job. Returns job_id."""
        job = ResearchJob(
            topic=topic.strip(),
            reason=reason,
            estimated_time=estimated_time,
            subreddits=subreddits or [],
            source=source,
        )
        await self._queue.put(job)
        log.info("Queued job %s: %r", job.job_id[:8], job.topic)
        return job.job_id

    async def evaluate_knowledge_gap(self, text_input: str) -> Optional[dict]:
        """
        Analyze arbitrary text for a research-worthy knowledge gap.
        Returns structured dict or None.
        """
        if not text_input or len(text_input.strip()) < 20:
            return None

        if self._ollama is None:
            from llm.ollama_client import ollama_client
            self._ollama = ollama_client

        messages = [
            {"role": "system", "content": _GAP_DETECTION_PROMPT},
            {"role": "user", "content": text_input.strip()[:4000]},
        ]
        try:
            raw = await self._ollama.chat(messages, stream=False)
        except Exception as exc:
            log.warning("Gap detection LLM call failed: %s", exc)
            return None

        if not raw:
            return None

        parsed = self._parse_json(raw)
        if not parsed or not isinstance(parsed, dict):
            return None

        if not parsed.get("gap"):
            return None

        topic = (parsed.get("topic") or "").strip()
        if not topic:
            return None

        return {
            "topic": topic,
            "reason": parsed.get("reason", "").strip(),
            "estimated_time": parsed.get("estimated_time", "approx. 5 minutes"),
            "suggested_subreddits": parsed.get("suggested_subreddits") or [],
        }

    async def handle_approval(self, action_id: str, approved: bool) -> None:
        """Called by slack_listener when an approval button is clicked."""
        if action_id not in self._approval_events:
            return  # Not one of ours — AgentLoop or stale
        self._approval_verdicts[action_id] = approved
        event = self._approval_events.get(action_id)
        if event:
            event.set()
        topic = self._approval_topics.get(action_id, "?")
        log.info(
            "Research approval %s: action_id=%s topic=%r",
            "APPROVED" if approved else "DENIED", action_id[:8], topic,
        )

    def owns_approval(self, action_id: str) -> bool:
        """Lets slack_listener ask: is this action_id one of ours?"""
        return action_id in self._approval_events

    # ── Job processing ───────────────────────────────────────────────────

    async def _process_job(self, job: ResearchJob) -> None:
        """Run the full approval → dispatch → compile → ingest pipeline."""
        # Step 1: Request approval
        approved, slack_ref = await self._request_approval(job)
        if not approved:
            return

        # Step 2: Dispatch headless ResearchOS
        await self._post_progress(slack_ref, "🔄 Booting Research Module...")
        try:
            report_path = await self._dispatch_research(job, slack_ref)
        except asyncio.TimeoutError:
            await self._post_progress(
                slack_ref,
                f"⏱️ Research subprocess timed out after {RESEARCH_SUBPROCESS_TIMEOUT_S}s",
            )
            return
        except Exception as exc:
            await self._post_progress(slack_ref, f"❌ Research failed: {exc}")
            return

        if not report_path or not report_path.exists():
            await self._post_progress(slack_ref, "❌ Report file not found after research")
            return

        # Step 3: Strategic compilation
        await self._post_progress(slack_ref, "🧠 Compiling Strategic Intelligence...")
        insight = await self._compile_strategic_insight(report_path, job.topic)
        if not insight:
            await self._post_progress(slack_ref, "❌ Could not extract strategic insight")
            return

        # Step 4: RAG ingestion
        await self._ingest_insight(insight, report_path, job.topic)

        # Step 5: Final Slack summary
        await self._post_final_summary(slack_ref, insight)

    # ── Approval flow ────────────────────────────────────────────────────

    async def _request_approval(self, job: ResearchJob) -> tuple[bool, dict]:
        """
        Post Slack approval request with Block Kit buttons. Wait for verdict
        or timeout. Returns (approved, slack_ref).
        """
        from core.slack_notifier import send_approval_request_async

        action_id = job.job_id

        # Build the "reason" text for the approval card
        reason_text = (
            f"{job.reason}\n\n"
            f"*ETA:* {job.estimated_time}\n"
            f"*Source:* {job.source}"
        )

        # Register event BEFORE posting to Slack so we don't miss a fast click
        event = asyncio.Event()
        self._approval_events[action_id] = event
        self._approval_topics[action_id] = job.topic

        try:
            slack_info = await send_approval_request_async(
                action_id=action_id,
                tool="autonomous_research",
                args={"topic": job.topic, "subreddits": job.subreddits},
                reason=reason_text,
                goal_id=f"research-{action_id[:8]}",
                channel_key="research",
            )
        except Exception as exc:
            log.error("Failed to post approval request: %s", exc)
            self._approval_events.pop(action_id, None)
            self._approval_topics.pop(action_id, None)
            return False, {"channel": "", "ts": ""}

        slack_ref = {
            "channel": slack_info.get("channel", ""),
            "ts": slack_info.get("ts", ""),
        }
        self._approval_slack_refs[action_id] = slack_ref

        if not slack_ref["ts"]:
            log.warning(
                "Slack approval post returned no ts — cannot receive buttons. "
                "Job %s auto-denied.", action_id[:8],
            )
            self._cleanup_approval(action_id)
            return False, slack_ref

        # Also send a plain-text follow-up for readability
        from core.slack_notifier import notify_async
        await notify_async(
            f"💡 *Knowledge Gap Detected:* {job.topic}\n"
            f"*Reason:* {job.reason or 'Gap detected in conversation.'}\n"
            f"*ETA:* {job.estimated_time}\n"
            f"_Click ✅ Approve above to authorize research._",
            channel_key="research",
        )

        # Wait for button click or timeout
        try:
            await asyncio.wait_for(event.wait(), timeout=APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning(
                "Research approval timed out after %ds for job %s (%r)",
                APPROVAL_TIMEOUT_S, action_id[:8], job.topic,
            )
            await self._post_progress(
                slack_ref,
                f"⏱️ Approval expired after {APPROVAL_TIMEOUT_S // 3600}h — research cancelled.",
            )
            self._cleanup_approval(action_id)
            return False, slack_ref

        approved = self._approval_verdicts.get(action_id, False)
        self._cleanup_approval(action_id)

        if not approved:
            await self._post_progress(slack_ref, "❌ Research skipped by user.")
            return False, slack_ref

        return True, slack_ref

    def _cleanup_approval(self, action_id: str) -> None:
        self._approval_events.pop(action_id, None)
        self._approval_verdicts.pop(action_id, None)
        self._approval_slack_refs.pop(action_id, None)
        self._approval_topics.pop(action_id, None)

    # ── Headless dispatch ────────────────────────────────────────────────

    async def _dispatch_research(self, job: ResearchJob, slack_ref: dict) -> Optional[Path]:
        """
        Run headless.py as a subprocess, stream stdout to Slack (throttled),
        parse the final REPORT_PATH: line.
        """
        python_bin = str(RESEARCH_OS_PYTHON) if RESEARCH_OS_PYTHON.exists() else sys.executable
        args = [python_bin, str(HEADLESS_SCRIPT), "--topic", job.topic]
        if job.subreddits:
            args += ["--subreddits", ",".join(job.subreddits)]

        log.info("Dispatching: %s", " ".join(args))
        await self._post_progress(slack_ref, f"🔎 Launching headless researcher for *{job.topic}*")

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(RESEARCH_OS_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        report_path: Optional[Path] = None
        last_status_post = 0.0
        stderr_tail: list[str] = []

        async def drain_stdout():
            nonlocal report_path, last_status_post
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                log.debug("headless> %s", line)

                # Parse the final REPORT_PATH line
                if line.startswith("REPORT_PATH:"):
                    p = Path(line[len("REPORT_PATH:") :].strip())
                    if p.exists():
                        report_path = p

                # Throttled status posts
                if line.startswith("[STATUS]"):
                    now = time.time()
                    if now - last_status_post >= SLACK_STATUS_INTERVAL_S:
                        await self._post_progress(slack_ref, f"🔄 {line[len('[STATUS] '):][:250]}")
                        last_status_post = now

        async def drain_stderr():
            assert proc.stderr is not None
            async for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    log.warning("headless.stderr> %s", line)
                    stderr_tail.append(line)
                    if len(stderr_tail) > 20:
                        stderr_tail.pop(0)

        stdout_task = asyncio.create_task(drain_stdout())
        stderr_task = asyncio.create_task(drain_stderr())

        try:
            await asyncio.wait_for(proc.wait(), timeout=RESEARCH_SUBPROCESS_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout_task.cancel()
            stderr_task.cancel()
            raise

        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        if proc.returncode != 0:
            err_summary = "\n".join(stderr_tail[-5:]) or "(no stderr)"
            raise RuntimeError(
                f"headless.py exited with code {proc.returncode}:\n{err_summary}"
            )

        return report_path

    # ── Strategic compilation ────────────────────────────────────────────

    async def _compile_strategic_insight(self, report_path: Path, topic: str) -> Optional[dict]:
        """Read the report, LLM-extract Strategic Utility JSON."""
        try:
            text = report_path.read_text(encoding="utf-8")
        except Exception as exc:
            log.error("Cannot read report %s: %s", report_path, exc)
            return None

        # Truncate if huge — leave headroom for prompt + response
        max_chars = 12000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[… truncated for analysis]"

        messages = [
            {"role": "system", "content": _STRATEGIC_COMPILER_PROMPT},
            {"role": "user", "content": f"Topic: {topic}\n\n{text}"},
        ]
        try:
            raw = await self._ollama.chat(messages, stream=False)
        except Exception as exc:
            log.error("Strategic compilation LLM call failed: %s", exc)
            return None

        if not raw:
            return None

        parsed = self._parse_json(raw)
        if not parsed or not isinstance(parsed, dict):
            log.warning("Could not parse strategic JSON. Raw: %s", raw[:400])
            return None

        # Ensure topic is set
        parsed.setdefault("topic", topic)
        return parsed

    # ── RAG ingestion ────────────────────────────────────────────────────

    async def _ingest_insight(self, insight: dict, report_path: Path, topic: str) -> None:
        """Store the structured insight in JRVS's RAG memory."""
        content = self._format_for_ingestion(insight)
        try:
            await self._rag.add_document(
                content=content,
                title=f"Strategic Insight: {topic}",
                url=f"file://{report_path}",
                metadata={
                    "type": "strategic_insight",
                    "source": "autonomous_research",
                    "topic": topic,
                    "compiled_at": datetime.now(timezone.utc).isoformat(),
                    "report_file": report_path.name,
                },
            )
            log.info("Ingested strategic insight into RAG: %r", topic)
        except Exception as exc:
            log.error("RAG ingestion failed for %r: %s", topic, exc)

    @staticmethod
    def _format_for_ingestion(insight: dict) -> str:
        topic = insight.get("topic", "Unknown")
        return (
            f"STRATEGIC INSIGHT: {topic}\n"
            f"Type: strategic_insight | Source: autonomous_research\n\n"
            f"LEVERAGE POINTS:\n{insight.get('leverage_points', 'N/A')}\n\n"
            f"OPPORTUNITY COST:\n{insight.get('opportunity_cost', 'N/A')}\n\n"
            f"CROSS-PROJECT SYNERGY:\n{insight.get('cross_project_synergy', 'N/A')}\n\n"
            f"SUMMARY: {insight.get('one_line_summary', 'N/A')}"
        )

    # ── Slack helpers ────────────────────────────────────────────────────

    async def _post_progress(self, slack_ref: dict, text: str) -> None:
        """Post a threaded reply to the approval message."""
        if not slack_ref.get("channel") or not slack_ref.get("ts"):
            # Fall back to plain channel post
            from core.slack_notifier import notify_async
            await notify_async(text, channel_key="research")
            return
        await self._post_threaded(slack_ref["channel"], slack_ref["ts"], text)

    async def _post_final_summary(self, slack_ref: dict, insight: dict) -> None:
        topic = insight.get("topic", "?")
        text = (
            f"✅ *Strategic Intelligence compiled on {topic}*\n\n"
            f"📌 *Leverage Point:* {insight.get('leverage_points', 'N/A')}\n\n"
            f"⚠️ *Opportunity Cost:* {insight.get('opportunity_cost', 'N/A')}\n\n"
            f"🔗 *Cross-Project Synergy:* {insight.get('cross_project_synergy', 'N/A')}\n\n"
            f"_{insight.get('one_line_summary', '')}_\n\n"
            f"_Ingested into JRVS knowledge base as `strategic_insight`._"
        )
        await self._post_progress(slack_ref, text)

    async def _notify_error(self, job: ResearchJob, err: str) -> None:
        from core.slack_notifier import notify_async
        await notify_async(
            f"❌ Research job for *{job.topic}* crashed:\n```{err[:800]}```",
            channel_key="alerts",
        )

    @staticmethod
    async def _post_threaded(channel: str, thread_ts: str, text: str) -> None:
        """Post a threaded reply via Slack chat.postMessage."""
        import urllib.request
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        if not token or token.startswith("xoxb-YOUR"):
            return
        payload = json.dumps({
            "channel": channel,
            "thread_ts": thread_ts,
            "text": text,
        }).encode()

        def _do():
            try:
                req = urllib.request.Request(
                    "https://slack.com/api/chat.postMessage",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read())
                if not result.get("ok"):
                    log.warning("Threaded reply failed: %s", result.get("error"))
            except Exception as exc:
                log.warning("Threaded reply error: %s", exc)

        await asyncio.get_event_loop().run_in_executor(None, _do)

    # ── Parsing helper ───────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Extract the first JSON object from possibly-noisy LLM output."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


# Global singleton
autonomous_researcher = AutonomousResearcher()
