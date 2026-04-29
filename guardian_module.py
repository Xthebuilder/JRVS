"""
GuardianModule - modular ingestion and analysis layer for The Guardian Open Platform.

Responsibilities:
- Fetch articles from The Guardian API
- Persist normalized records in SQLite
- Optionally ingest new items into JRVS RAG memory
- Build analyst-style briefs with section trends and sentiment mix
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

from config import (
    GUARDIAN_API_BASE_URL,
    GUARDIAN_API_KEY,
    JRVS_SERVER_HOST,
    JRVS_SERVER_PORT,
)
from core.database import db

log = logging.getLogger("jarvis.guardian")

_POSITIVE_WORDS = {
    "growth", "gain", "wins", "win", "improve", "improved", "surge", "record", "strong",
    "breakthrough", "recovery", "benefit", "progress", "upbeat", "expand", "expanded",
}
_NEGATIVE_WORDS = {
    "decline", "drop", "fall", "falls", "crisis", "risk", "loss", "losses", "weak",
    "concern", "concerns", "warning", "warn", "cut", "cuts", "slowdown", "downturn",
}
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from", "at",
    "by", "is", "are", "was", "were", "be", "been", "as", "that", "this", "it", "its",
    "after", "before", "about", "into", "over", "under", "than", "but", "not", "will",
}


class GuardianModule:
    def __init__(self) -> None:
        self.base_url = GUARDIAN_API_BASE_URL.rstrip("/")
        self.api_key = GUARDIAN_API_KEY

    async def _ensure_ready(self) -> None:
        """Initialize the shared SQLite schema before any Guardian DB access."""
        await db.initialize()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def fetch_and_store(
        self,
        query: str = "",
        section: str = "",
        from_date: str = "",
        to_date: str = "",
        page_size: int = 25,
        pages: int = 1,
        ingest_to_rag: bool = True,
    ) -> dict[str, Any]:
        await self._ensure_ready()
        if not self.configured:
            raise RuntimeError("GUARDIAN_API_KEY is not configured")

        page_size = max(1, min(page_size, 50))
        pages = max(1, min(pages, 5))

        total_seen = 0
        total_new = 0
        ingested = 0
        collected: list[dict[str, Any]] = []

        for page in range(1, pages + 1):
            payload = await self._fetch_page(
                query=query,
                section=section,
                from_date=from_date,
                to_date=to_date,
                page=page,
                page_size=page_size,
            )
            results = payload.get("response", {}).get("results", [])
            if not results:
                break
            collected.extend(results)

        for item in collected:
            total_seen += 1
            normalized = self._normalize_article(item)
            row_id, created = await db.upsert_guardian_article(normalized)
            if created:
                total_new += 1
                if ingest_to_rag:
                    ok = await self._ingest_article_to_rag(normalized)
                    if ok:
                        ingested += 1
            elif row_id:
                await db.touch_guardian_article(row_id)

        return {
            "seen": total_seen,
            "new": total_new,
            "rag_ingested": ingested,
            "query": query,
            "section": section,
        }

    async def search_articles(
        self,
        query: str,
        limit: int = 20,
        section: str = "",
    ) -> list[dict[str, Any]]:
        await self._ensure_ready()
        return await db.search_guardian_articles(query=query, section=section or None, limit=limit)

    async def analyst_brief(
        self,
        days: int = 1,
        topic: str = "",
        limit: int = 120,
    ) -> dict[str, Any]:
        await self._ensure_ready()
        days = max(1, min(days, 30))
        articles = await db.get_guardian_articles_since(days=days, topic=topic or None, limit=limit)
        if not articles:
            return {
                "articles_analyzed": 0,
                "window_days": days,
                "topic": topic,
                "summary": "No Guardian articles found for this window.",
                "section_trends": [],
                "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
                "top_keywords": [],
            }

        section_counts = Counter((a.get("section_name") or "Unknown") for a in articles)
        sentiments = Counter(self._score_sentiment(a) for a in articles)
        top_keywords = self._extract_keywords(articles, top_n=10)

        top_sections = [
            {"section": name, "count": count}
            for name, count in section_counts.most_common(6)
        ]

        total = len(articles)
        positive = sentiments.get("positive", 0)
        neutral = sentiments.get("neutral", 0)
        negative = sentiments.get("negative", 0)

        summary = (
            f"Analyzed {total} Guardian articles over the last {days} day(s). "
            f"Coverage concentrated in {len(section_counts)} sections; top section is "
            f"{top_sections[0]['section']} ({top_sections[0]['count']} stories). "
            f"Sentiment mix is {positive} positive, {neutral} neutral, {negative} negative."
        )

        return {
            "articles_analyzed": total,
            "window_days": days,
            "topic": topic,
            "summary": summary,
            "section_trends": top_sections,
            "sentiment": {
                "positive": positive,
                "neutral": neutral,
                "negative": negative,
            },
            "top_keywords": top_keywords,
            "recent": articles[: min(8, len(articles))],
        }

    async def generate_and_save_report(
        self,
        days: int = 1,
        topic: str = "",
        limit: int = 150,
    ) -> dict[str, Any]:
        """Build an analyst brief and persist it as markdown and HTML report files."""
        await self._ensure_ready()
        brief = await self.analyst_brief(days=days, topic=topic, limit=limit)

        reports_dir = Path("static") / "reports" / "guardian"
        reports_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = re.sub(r"[^a-z0-9_-]+", "-", (topic or "all").lower()).strip("-") or "all"
        
        # Save markdown
        md_filename = f"guardian-brief-{safe_topic}-{ts}.md"
        md_path = reports_dir / md_filename
        markdown = self._to_markdown(brief)
        md_path.write_text(markdown, encoding="utf-8")
        
        # Save HTML
        html_filename = f"guardian-brief-{safe_topic}-{ts}.html"
        html_path = reports_dir / html_filename
        html = self._to_html(brief)
        html_path.write_text(html, encoding="utf-8")

        return {
            **brief,
            "report_path": str(md_path),
            "report_url": self._report_url(md_filename),
            "html_report_path": str(html_path),
            "html_report_url": self._report_url(html_filename),
            "generated_at": datetime.now().isoformat(),
        }

    async def _fetch_page(
        self,
        query: str,
        section: str,
        from_date: str,
        to_date: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        params = {
            "api-key": self.api_key,
            "page": page,
            "page-size": page_size,
            "show-fields": "headline,trailText,bodyText",
            "order-by": "newest",
        }
        if query:
            params["q"] = query
        if section:
            params["section"] = section
        if from_date:
            params["from-date"] = from_date
        if to_date:
            params["to-date"] = to_date

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{self.base_url}/search", params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Guardian API error {resp.status}: {body[:500]}")
                return await resp.json()

    def _normalize_article(self, item: dict[str, Any]) -> dict[str, Any]:
        fields = item.get("fields") or {}
        return {
            "guardian_id": item.get("id", ""),
            "type": item.get("type", ""),
            "section_id": item.get("sectionId", ""),
            "section_name": item.get("sectionName", ""),
            "web_title": item.get("webTitle", ""),
            "web_url": item.get("webUrl", ""),
            "api_url": item.get("apiUrl", ""),
            "published_at": item.get("webPublicationDate", ""),
            "headline": fields.get("headline", ""),
            "trail_text": fields.get("trailText", ""),
            "body_text": fields.get("bodyText", ""),
        }

    async def _ingest_article_to_rag(self, article: dict[str, Any]) -> bool:
        url = article.get("web_url", "")
        if not url:
            return False
        try:
            from rag.retriever import rag_retriever

            exists = await db.check_document_exists(url)
            if exists:
                return False

            content = "\n\n".join(
                [
                    article.get("headline", "") or article.get("web_title", ""),
                    article.get("trail_text", ""),
                    article.get("body_text", ""),
                ]
            ).strip()
            if not content:
                return False

            await rag_retriever.add_document(
                content=content,
                title=article.get("web_title", "Guardian article"),
                url=url,
                metadata={
                    "source": "guardian",
                    "guardian_id": article.get("guardian_id", ""),
                    "section": article.get("section_name", ""),
                    "published_at": article.get("published_at", ""),
                },
            )
            return True
        except Exception as exc:
            log.warning("Guardian RAG ingest failed for %s: %s", url, exc)
            return False

    def _score_sentiment(self, article: dict[str, Any]) -> str:
        text = " ".join(
            [
                article.get("web_title", ""),
                article.get("headline", ""),
                article.get("trail_text", ""),
            ]
        ).lower()
        words = re.findall(r"[a-z']+", text)
        pos = sum(1 for w in words if w in _POSITIVE_WORDS)
        neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
        if pos - neg >= 1:
            return "positive"
        if neg - pos >= 1:
            return "negative"
        return "neutral"

    def _extract_keywords(self, articles: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
        counter: Counter[str] = Counter()
        for a in articles:
            text = f"{a.get('web_title', '')} {a.get('headline', '')} {a.get('trail_text', '')}".lower()
            words = re.findall(r"[a-z]{3,}", text)
            for w in words:
                if w in _STOPWORDS:
                    continue
                counter[w] += 1
        return [{"keyword": k, "count": v} for k, v in counter.most_common(top_n)]

    def _report_url(self, filename: str) -> str:
        from config import SERVER_URL
        return f"{SERVER_URL.rstrip('/')}/static/reports/guardian/{filename}"

    def _to_markdown(self, brief: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("# Guardian Analyst Brief")
        lines.append("")
        lines.append(f"- Generated: {datetime.now().isoformat()}")
        lines.append(f"- Window (days): {brief.get('window_days', 0)}")
        lines.append(f"- Topic: {brief.get('topic') or 'all'}")
        lines.append(f"- Articles analyzed: {brief.get('articles_analyzed', 0)}")
        lines.append("")
        lines.append("## Summary")
        lines.append(brief.get("summary", "No summary available."))
        lines.append("")

        lines.append("## Section Trends")
        for s in brief.get("section_trends", []):
            lines.append(f"- {s.get('section', 'Unknown')}: {s.get('count', 0)}")
        if not brief.get("section_trends"):
            lines.append("- None")
        lines.append("")

        sentiment = brief.get("sentiment", {})
        lines.append("## Sentiment Mix")
        lines.append(f"- Positive: {sentiment.get('positive', 0)}")
        lines.append(f"- Neutral: {sentiment.get('neutral', 0)}")
        lines.append(f"- Negative: {sentiment.get('negative', 0)}")
        lines.append("")

        lines.append("## Top Keywords")
        for k in brief.get("top_keywords", []):
            lines.append(f"- {k.get('keyword', '')}: {k.get('count', 0)}")
        if not brief.get("top_keywords"):
            lines.append("- None")
        lines.append("")

        lines.append("## Recent Articles")
        for a in brief.get("recent", []):
            title = a.get("web_title", "Untitled")
            section = a.get("section_name", "Unknown")
            url = a.get("web_url", "")
            published = a.get("published_at", "")
            lines.append(f"- [{section}] {title}")
            if published:
                lines.append(f"  - Published: {published}")
            if url:
                lines.append(f"  - URL: {url}")
        if not brief.get("recent"):
            lines.append("- None")
        lines.append("")
        return "\n".join(lines)

    def _to_html(self, brief: dict[str, Any]) -> str:
        """Convert brief to styled HTML report."""
        gen_time = datetime.now().isoformat()
        window_days = brief.get("window_days", 0)
        topic = brief.get("topic") or "all"
        articles_count = brief.get("articles_analyzed", 0)
        summary = brief.get("summary", "No summary available.")
        sentiment = brief.get("sentiment", {})
        
        sentiment_positive = sentiment.get("positive", 0)
        sentiment_neutral = sentiment.get("neutral", 0)
        sentiment_negative = sentiment.get("negative", 0)
        
        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="en">',
            '<head>',
            '  <meta charset="UTF-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            '  <title>Guardian Analyst Brief</title>',
            '  <style>',
            '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #1a1a1a; color: #e0e0e0; }',
            '    .container { background: #2a2a2a; border-radius: 8px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.5); }',
            '    h1 { color: #5fa3ff; margin-bottom: 10px; }',
            '    .metadata { background: #333333; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-size: 14px; color: #b0b0b0; }',
            '    .metadata strong { color: #f0f0f0; }',
            '    .section { margin-bottom: 25px; }',
            '    h2 { color: #5fa3ff; font-size: 20px; border-bottom: 2px solid #444444; padding-bottom: 10px; margin-top: 25px; }',
            '    .summary { background: #3a3520; border-left: 4px solid #fbbc04; padding: 15px; border-radius: 4px; color: #e0e0e0; }',
            '    .trends { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }',
            '    .trend-item { background: #333350; padding: 12px; border-radius: 6px; color: #c0c0ff; }',
            '    .sentiment { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 10px; }',
            '    .sentiment-card { text-align: center; padding: 15px; border-radius: 6px; }',
            '    .sentiment-positive { background: #1a3a1a; color: #66ff66; }',
            '    .sentiment-neutral { background: #1a2a3a; color: #66d9ff; }',
            '    .sentiment-negative { background: #3a1a1a; color: #ff6666; }',
            '    .sentiment-card strong { font-size: 24px; display: block; }',
            '    .keywords { display: flex; flex-wrap: wrap; gap: 8px; }',
            '    .keyword { background: #303050; color: #9ca3ff; padding: 6px 12px; border-radius: 20px; font-size: 14px; }',
            '    .articles { list-style: none; padding: 0; }',
            '    .article { background: #333333; padding: 15px; margin-bottom: 12px; border-radius: 6px; border-left: 3px solid #5fa3ff; }',
            '    .article-title { font-weight: 600; color: #5fa3ff; margin-bottom: 8px; }',
            '    .article-meta { font-size: 13px; color: #808080; margin-bottom: 6px; }',
            '    .article-meta span { display: inline-block; margin-right: 15px; }',
            '    .article-url { font-size: 13px; color: #5fa3ff; word-break: break-all; }',
            '    a { color: #5fa3ff; text-decoration: none; }',
            '    a:hover { text-decoration: underline; }',
            '    .empty { color: #808080; font-style: italic; }',
            '  </style>',
            '</head>',
            '<body>',
            '  <div class="container">',
            f'    <h1>📰 Guardian Analyst Brief</h1>',
            f'    <div class="metadata">',
            f'      <div><strong>Generated:</strong> {gen_time}</div>',
            f'      <div><strong>Window:</strong> Last {window_days} day(s)</div>',
            f'      <div><strong>Topic:</strong> {topic}</div>',
            f'      <div><strong>Articles Analyzed:</strong> {articles_count}</div>',
            f'    </div>',
            f'    <div class="section">',
            f'      <h2>Summary</h2>',
            f'      <div class="summary">{summary}</div>',
            f'    </div>',
        ]
        
        # Section trends
        html_parts.append('    <div class="section">')
        html_parts.append('      <h2>Section Trends</h2>')
        trends = brief.get("section_trends", [])
        if trends:
            html_parts.append('      <div class="trends">')
            for t in trends:
                section = t.get("section", "Unknown")
                count = t.get("count", 0)
                html_parts.append(f'        <div class="trend-item"><strong>{section}</strong><br>{count} article{"s" if count != 1 else ""}</div>')
            html_parts.append('      </div>')
        else:
            html_parts.append('      <p class="empty">No section data</p>')
        html_parts.append('    </div>')
        
        # Sentiment
        html_parts.append('    <div class="section">')
        html_parts.append('      <h2>Sentiment Mix</h2>')
        html_parts.append('      <div class="sentiment">')
        html_parts.append(f'        <div class="sentiment-card sentiment-positive"><strong>{sentiment_positive}</strong>Positive</div>')
        html_parts.append(f'        <div class="sentiment-card sentiment-neutral"><strong>{sentiment_neutral}</strong>Neutral</div>')
        html_parts.append(f'        <div class="sentiment-card sentiment-negative"><strong>{sentiment_negative}</strong>Negative</div>')
        html_parts.append('      </div>')
        html_parts.append('    </div>')
        
        # Keywords
        html_parts.append('    <div class="section">')
        html_parts.append('      <h2>Top Keywords</h2>')
        keywords = brief.get("top_keywords", [])
        if keywords:
            html_parts.append('      <div class="keywords">')
            for k in keywords:
                keyword = k.get("keyword", "")
                count = k.get("count", 0)
                html_parts.append(f'        <span class="keyword">{keyword} ({count})</span>')
            html_parts.append('      </div>')
        else:
            html_parts.append('      <p class="empty">No keywords found</p>')
        html_parts.append('    </div>')
        
        # Recent articles
        html_parts.append('    <div class="section">')
        html_parts.append('      <h2>Recent Articles</h2>')
        articles = brief.get("recent", [])
        if articles:
            html_parts.append('      <ul class="articles">')
            for a in articles:
                title = a.get("web_title", "Untitled")
                section = a.get("section_name", "Unknown")
                url = a.get("web_url", "")
                published = a.get("published_at", "")
                html_parts.append('        <li class="article">')
                html_parts.append(f'          <div class="article-title">{title}</div>')
                html_parts.append('          <div class="article-meta">')
                html_parts.append(f'            <span><strong>Section:</strong> {section}</span>')
                if published:
                    html_parts.append(f'            <span><strong>Published:</strong> {published}</span>')
                html_parts.append('          </div>')
                if url:
                    html_parts.append(f'          <div class="article-url"><a href="{url}" target="_blank">Read on The Guardian →</a></div>')
                html_parts.append('        </li>')
            html_parts.append('      </ul>')
        else:
            html_parts.append('      <p class="empty">No articles found</p>')
        html_parts.append('    </div>')
        
        html_parts.extend([
            '  </div>',
            '</body>',
            '</html>',
        ])
        
        return '\n'.join(html_parts)


guardian_module = GuardianModule()
