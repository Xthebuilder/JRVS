"""
Brave Search + YouTube Search client for JRVS core.

Pipeline per search:
  1. Brave REST API  →  raw results
  2. Embed with sentence-transformers (lazy)
  3. Upsert to SQLite  (web_search_results / youtube_search_results)
  4. Add to FAISS namespace  (persistent semantic memory)
  5. Semantic re-rank against entire accumulated index
  6. Return formatted context string ready for LLM prompt injection
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import requests

from jrvs.config import Config

log = logging.getLogger(__name__)

WEB_NAMESPACE = "web_search"
YT_NAMESPACE  = "yt_search"


# ─────────────────────────────────────────────────────────────────────────────
# Raw API client
# ─────────────────────────────────────────────────────────────────────────────

class BraveClient:
    """Thin wrapper around the Brave Search REST API."""

    def __init__(self) -> None:
        self._api_key = Config.BRAVE_API_KEY
        if not self._api_key:
            raise RuntimeError("BRAVE_API_KEY not set. Add it to ~/JRVS/.env")
        self._base_url     = Config.BRAVE_SEARCH_URL
        self._result_count = Config.BRAVE_RESULT_COUNT

    def search(self, query: str, count: int | None = None) -> list[dict[str, Any]]:
        """Call Brave and return a flat list of {title, url, snippet}."""
        count = count or self._result_count
        try:
            resp = requests.get(
                self._base_url,
                headers={
                    "Accept":               "application/json",
                    "Accept-Encoding":      "gzip",
                    "X-Subscription-Token": self._api_key,
                },
                params={"q": query, "count": count},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Brave API error: {exc}") from exc

        results = []
        for r in resp.json().get("web", {}).get("results", []):
            title   = r.get("title", "")
            url     = r.get("url", "")
            snippet = r.get("description", "")
            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})
        log.info("Brave: %d results for '%s'", len(results), query)
        return results


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class WebSearchEngine:
    """Run Brave + YouTube search, embed results, persist, return for RAG."""

    def __init__(self, db=None) -> None:
        from jrvs.storage.database import Database
        self._db    = db or Database()
        self._brave = BraveClient()

    def run(
        self,
        query: str,
        top_k: int | None = None,
        count: int | None = None,
        yt_count: int | None = None,
    ) -> tuple[str, list[dict], str, list[dict]]:
        """Fetch, embed, store, re-rank.

        Returns
        -------
        web_context : str   — formatted Brave block for LLM prompt injection
        raw_web     : list  — raw Brave result dicts
        yt_context  : str   — formatted YouTube block for LLM prompt injection
        raw_yt      : list  — raw YouTube result dicts
        """
        top_k    = top_k    or Config.WEB_SEARCH_TOP_K
        yt_count = yt_count or Config.YOUTUBE_SEARCH_RESULT_COUNT

        # ── Brave ─────────────────────────────────────────────────────────
        raw_web = self._brave.search(query, count=count)
        if not raw_web:
            web_context = "No Brave results found."
        else:
            self._db.upsert_web_results([
                {
                    "result_id": _stable_id(r["url"]),
                    "query":     query,
                    "title":     r["title"],
                    "url":       r["url"],
                    "snippet":   r["snippet"],
                    "source":    "brave",
                }
                for r in raw_web
            ])
            texts = [f"{r['title']}. {r['snippet']}" for r in raw_web]
            vecs  = _encode(texts)
            _add_to_store(vecs, [
                {"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
                for r in raw_web
            ], namespace=WEB_NAMESPACE)
            hits        = _semantic_search(query, k=top_k, namespace=WEB_NAMESPACE)
            web_context = _format_web(query, hits)

        # ── YouTube ───────────────────────────────────────────────────────
        yt_context, raw_yt = self._search_youtube(query, yt_count)

        return web_context, raw_web, yt_context, raw_yt

    def _search_youtube(
        self, query: str, yt_count: int | None = None
    ) -> tuple[str, list[dict]]:
        yt_count = yt_count or Config.YOUTUBE_SEARCH_RESULT_COUNT

        if not Config.YOUTUBE_API_KEY:
            log.debug("YOUTUBE_API_KEY not set — skipping YT search")
            return "", []

        try:
            raw_videos = _yt_search(query, max_results=yt_count)
        except Exception as exc:
            log.warning("YouTube search failed: %s", exc)
            return "", []

        if not raw_videos:
            return "", []

        try:
            self._db.upsert_youtube_search_results([
                {
                    "result_id":     _stable_id(v.get("video_id", "") + query),
                    "query":         query,
                    "video_id":      v.get("video_id", ""),
                    "title":         v.get("title", ""),
                    "channel_title": v.get("channel_title", ""),
                    "channel_id":    v.get("channel_id", ""),
                    "views":         v.get("views", 0),
                    "url":           f"https://www.youtube.com/watch?v={v.get('video_id','')}",
                    "description":   v.get("description", "")[:300],
                    "source":        "youtube",
                }
                for v in raw_videos
            ])
        except Exception as exc:
            log.warning("Could not persist YT results: %s", exc)

        texts = [
            f"{v.get('title','')}. {v.get('channel_title','')}. {v.get('description','')[:150]}"
            for v in raw_videos
        ]
        vecs = _encode(texts)
        _add_to_store(vecs, [
            {
                "title":         v.get("title", ""),
                "channel_title": v.get("channel_title", ""),
                "views":         v.get("views", 0),
                "url":           f"https://www.youtube.com/watch?v={v.get('video_id','')}",
                "description":   v.get("description", "")[:150],
            }
            for v in raw_videos
        ], namespace=YT_NAMESPACE)

        hits       = _semantic_search(query, k=Config.YT_SEARCH_TOP_K, namespace=YT_NAMESPACE)
        yt_context = _format_yt(query, hits)
        return yt_context, raw_videos


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _stable_id(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def _encode(texts: list[str]):
    """Embed texts via singleton encoder (lazy-loaded)."""
    from jrvs.embeddings.encoder import EmbeddingEncoder
    return EmbeddingEncoder.get().encode(texts)


def _add_to_store(vecs, metadata: list[dict], namespace: str) -> None:
    from jrvs.embeddings.vector_store import VectorStore
    VectorStore(namespace).add(vecs, metadata)


def _semantic_search(query: str, k: int, namespace: str) -> list[dict]:
    from jrvs.embeddings.encoder import EmbeddingEncoder
    from jrvs.embeddings.vector_store import VectorStore
    store = VectorStore(namespace)
    if store.size == 0:
        return []
    q_vec = EmbeddingEncoder.get().encode_single(query)
    return store.search(q_vec, k=k)


def _yt_search(query: str, max_results: int) -> list[dict]:
    """Lightweight YouTube Data API v3 search (no heavy YouTubeClient needed)."""
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part":       "snippet",
            "q":          query,
            "type":       "video",
            "maxResults": max_results,
            "key":        Config.YOUTUBE_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    videos = []
    for item in resp.json().get("items", []):
        vid_id = item.get("id", {}).get("videoId", "")
        snip   = item.get("snippet", {})
        videos.append({
            "video_id":      vid_id,
            "title":         snip.get("title", ""),
            "channel_title": snip.get("channelTitle", ""),
            "channel_id":    snip.get("channelId", ""),
            "description":   snip.get("description", "")[:300],
            "views":         0,
        })
    return videos


def _format_web(query: str, hits: list[dict]) -> str:
    if not hits:
        return ""
    lines = [f'=== Web Search Results (query: "{query}") ===']
    for i, h in enumerate(hits, 1):
        lines.append(
            f"{i}. [{h.get('title','')}]({h.get('url','')})\n"
            f"   {h.get('snippet','')}\n"
            f"   (similarity: {h.get('score',0):.3f})"
        )
    return "\n".join(lines)


def _format_yt(query: str, hits: list[dict]) -> str:
    if not hits:
        return ""
    lines = [f'=== YouTube Results (query: "{query}") ===']
    for i, h in enumerate(hits, 1):
        lines.append(
            f"{i}. [{h.get('title','')}]({h.get('url','')}) "
            f"by {h.get('channel_title','')}\n"
            f"   {h.get('description','')}\n"
            f"   (similarity: {h.get('score',0):.3f})"
        )
    return "\n".join(lines)
