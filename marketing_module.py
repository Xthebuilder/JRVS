"""
Marketing Module — LLM-powered copy generation for JRVS brands.

Flow:
    1. Job queued via queue_draft() (CLI, agent tool, or Slack)
    2. Ollama generates draft with a brand-aware system prompt
    3. Platform formatter trims/shapes to platform constraints
    4. Draft saved to marketing_drafts SQLite table
    5. Slack notification (no approval gate — drafts are safe to generate)

Hooked into jarvis_daemon.py as a _supervise()d task.

Brands: tensorlink, xthebuilder
Platforms: linkedin, twitter, email
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("jarvis.marketing")


# ── Brand profiles ────────────────────────────────────────────────────────────

BRAND_PROFILES: dict[str, dict] = {
    "tensorlink": {
        "name": "TensorLink",
        "tagline": "Edge-native AI inference, owned by you.",
        "voice": "technical, confident, infrastructure-focused. No hype — let the specs speak.",
        "audience": "ML engineers, self-hosters, enterprise IT buyers evaluating on-prem AI",
        "avoid": "cloud lock-in buzzwords, vague AI hype, overclaiming benchmarks",
        "cta": "Deploy in 10 minutes. Try it yourself.",
    },
    "xthebuilder": {
        "name": "Xthebuilder",
        "tagline": "Building in public. AI tools, homelab, and the grind.",
        "voice": "authentic, direct, builder-culture. First-person. Show the work, not the polish.",
        "audience": "developers, indie hackers, AI enthusiasts, Linux/homelab community",
        "avoid": "corporate speak, humble bragging, motivation-poster platitudes",
        "cta": "Follow along. Drop a comment.",
    },
}


# ── Platform specs ────────────────────────────────────────────────────────────

PLATFORM_SPECS: dict[str, dict] = {
    "linkedin": {
        "char_limit": 1300,
        "instructions": (
            "Hook on line 1 — no hashtags in the first 3 lines. "
            "Short paragraphs (2-3 sentences). "
            "3-5 relevant hashtags at the very end. "
            "Professional but human tone."
        ),
    },
    "twitter": {
        "char_limit": 280,
        "instructions": (
            "One punchy idea per tweet. 1-2 hashtags max, or none. "
            "No filler. Thread-opener style if the topic needs more space."
        ),
    },
    "email": {
        "char_limit": 0,
        "instructions": (
            "First line must be exactly: Subject: <subject line>\n"
            "Then a blank line, then the body. "
            "Plain text. Conversational opening. "
            "Single clear CTA in the final paragraph."
        ),
    },
}

_GENERATION_SYSTEM = """\
You are a marketing copywriter for {name} — "{tagline}"

Brand voice: {voice}
Target audience: {audience}
Avoid: {avoid}
Brand CTA: {cta}

Platform: {platform}
Platform instructions: {instructions}
{char_limit_note}

Return ONLY the final copy. No preamble, no label like "Here's a post:", no explanation.\
"""


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class MarketingJob:
    brand: str
    platform: str
    topic: str
    content_type: str = "post"
    source: str = "manual"
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Module class ──────────────────────────────────────────────────────────────

class MarketingModule:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[MarketingJob] = asyncio.Queue()
        self._ollama = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Long-running queue consumer. Called by _supervise() in jarvis_daemon.py."""
        from llm.ollama_client import ollama_client
        from core.database import db

        self._ollama = ollama_client
        self._db = db

        log.info("MarketingModule ready (queue_size=%d)", self._queue.qsize())

        while True:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                raise
            try:
                await self._process_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("Marketing job %s failed: %s", job.job_id[:8], exc)
                await _notify_slack(
                    f":x: Marketing job for *{job.brand}/{job.platform}* failed:\n```{str(exc)[:500]}```",
                    channel_key="alerts",
                )
            finally:
                self._queue.task_done()

    # ── Public API ────────────────────────────────────────────────────────

    async def queue_draft(
        self,
        brand: str,
        platform: str,
        topic: str,
        content_type: str = "post",
        source: str = "manual",
    ) -> str:
        """Enqueue a generation job. Returns job_id. Raises ValueError on bad brand/platform."""
        if brand not in BRAND_PROFILES:
            raise ValueError(
                f"Unknown brand: {brand!r}. Available: {sorted(BRAND_PROFILES)}"
            )
        if platform not in PLATFORM_SPECS:
            raise ValueError(
                f"Unknown platform: {platform!r}. Available: {sorted(PLATFORM_SPECS)}"
            )
        job = MarketingJob(
            brand=brand, platform=platform, topic=topic,
            content_type=content_type, source=source,
        )
        await self._queue.put(job)
        log.info(
            "Queued marketing job %s: %s/%s %r", job.job_id[:8], brand, platform, topic
        )
        return job.job_id

    async def list_drafts(
        self,
        brand: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return recent drafts from the DB, newest first."""
        from core.database import db
        return await db.list_marketing_drafts(brand=brand, platform=platform, limit=limit)

    # ── Job processing ────────────────────────────────────────────────────

    async def _process_job(self, job: MarketingJob) -> None:
        content = await self._generate_draft(job)
        if not content:
            log.warning("Empty generation for job %s — skipping save", job.job_id[:8])
            return

        content = _format_for_platform(content, job.platform)
        draft_id = await self._save_draft(job, content)
        await self._notify_done(job, content, draft_id)

    async def _generate_draft(self, job: MarketingJob) -> Optional[str]:
        brand = BRAND_PROFILES[job.brand]
        spec = PLATFORM_SPECS[job.platform]
        char_limit = spec["char_limit"]
        char_limit_note = (
            f"Hard character limit: {char_limit} characters."
            if char_limit else
            "No character limit."
        )
        system = _GENERATION_SYSTEM.format(
            name=brand["name"],
            tagline=brand["tagline"],
            voice=brand["voice"],
            audience=brand["audience"],
            avoid=brand["avoid"],
            cta=brand["cta"],
            platform=job.platform,
            instructions=spec["instructions"],
            char_limit_note=char_limit_note,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": f"Write a {job.content_type} about: {job.topic}"},
        ]
        try:
            return await self._ollama.chat(messages, stream=False)
        except Exception as exc:
            log.error("Ollama chat failed for job %s: %s", job.job_id[:8], exc)
            return None

    async def _save_draft(self, job: MarketingJob, content: str) -> int:
        from core.database import db
        return await db.save_marketing_draft(
            job_id=job.job_id,
            brand=job.brand,
            platform=job.platform,
            topic=job.topic,
            content_type=job.content_type,
            content=content,
            source=job.source,
        )

    async def _notify_done(self, job: MarketingJob, content: str, draft_id: int) -> None:
        brand = BRAND_PROFILES[job.brand]
        char_count = len(content)
        limit = PLATFORM_SPECS[job.platform]["char_limit"]
        limit_note = f"({char_count}/{limit} chars)" if limit else f"({char_count} chars)"
        preview = content[:300] + ("…" if len(content) > 300 else "")
        msg = (
            f":pencil: *Marketing draft ready* — `{brand['name']}` / `{job.platform}` {limit_note}\n"
            f"*Topic:* {job.topic}\n\n"
            f"```{preview}```\n"
            f"_Draft #{draft_id} saved. Run `/marketing list` to review._"
        )
        await _notify_slack(msg, channel_key="general")


# ── Platform formatter ────────────────────────────────────────────────────────

def _format_for_platform(text: str, platform: str) -> str:
    """Trim and clean generated content to platform constraints."""
    text = text.strip()
    spec = PLATFORM_SPECS.get(platform, {})
    limit = spec.get("char_limit", 0)

    if platform == "twitter" and limit and len(text) > limit:
        # Trim at last word boundary before limit
        trimmed = text[:limit].rsplit(None, 1)[0]
        text = trimmed.rstrip(",;:-") + "…"

    elif platform == "linkedin" and limit and len(text) > limit:
        # Trim at last paragraph boundary
        text = text[:limit].rsplit("\n", 1)[0].rstrip()

    elif platform == "email":
        # Guarantee Subject: prefix on first line
        if not text.lower().startswith("subject:"):
            lines = text.splitlines()
            text = f"Subject: {lines[0].strip()}\n\n" + "\n".join(lines[1:]).lstrip()

    return text


# ── Slack helper ──────────────────────────────────────────────────────────────

async def _notify_slack(text: str, channel_key: Optional[str] = None) -> None:
    try:
        from core.slack_notifier import notify_async
        await notify_async(text, channel_key=channel_key)
    except Exception as exc:
        log.debug("_notify_slack: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
marketing_module = MarketingModule()
