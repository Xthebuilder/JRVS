"""Brave Search API client — fetches web results and ingests them into FAISS/RAG"""
import aiohttp
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

from config import (
    BRAVE_API_KEY,
    BRAVE_MAX_REQUESTS_PER_SESSION,
    BRAVE_SEARCH_RESULTS_PER_QUERY,
    BRAVE_AUTO_SCRAPE,
    TIMEOUTS,
)
from core.lazy_loader import retry_on_failure

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchClient:
    def __init__(self):
        self.api_key: str = BRAVE_API_KEY
        self.max_requests: int = BRAVE_MAX_REQUESTS_PER_SESSION
        self.results_per_query: int = BRAVE_SEARCH_RESULTS_PER_QUERY
        self.auto_scrape: bool = BRAVE_AUTO_SCRAPE
        self._requests_used: int = 0
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def set_api_key(self, key: str) -> None:
        self.api_key = key.strip()
        # Close stale session so next request creates one with the new key
        if self._session and not self._session.closed:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._session.close())
            except RuntimeError:
                pass
            self._session = None

    def set_max_requests(self, limit: int) -> None:
        self.max_requests = max(1, int(limit))

    @property
    def requests_remaining(self) -> int:
        return max(0, self.max_requests - self._requests_used)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def reset_request_counter(self) -> None:
        self._requests_used = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=TIMEOUTS.get("web_scraping", 45))
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key,
                },
            )
        return self._session

    # ------------------------------------------------------------------
    # Core API call
    # ------------------------------------------------------------------

    async def search(self, query: str) -> List[Dict]:
        """
        Call the Brave Search API and return a list of result dicts.
        Each dict has keys: title, url, description.
        Returns [] if budget exhausted or API key missing.
        """
        if not self.is_configured:
            log.warning("BraveSearch: no API key configured")
            return []

        if self._requests_used >= self.max_requests:
            log.warning("BraveSearch: request budget exhausted (%d max)", self.max_requests)
            return []

        # aiohttp rejects bool values in query params (even though bool subclasses
        # int in Python).  Cast every value to str/int explicitly to avoid the
        # "Invalid variable type: got False of type bool" runtime error.
        params = {
            "q": str(query),
            "count": int(self.results_per_query),
            "safesearch": "moderate",
            "text_decorations": "false",
        }

        @retry_on_failure(max_retries=1, delay=0.5, backoff=1.5)
        async def _do_request() -> dict | None:
            session = await self._get_session()
            async with session.get(BRAVE_SEARCH_URL, params=params) as resp:
                if resp.status == 401:
                    log.error("BraveSearch: invalid API key (401) — use /brave-key to update it")
                    return None
                if resp.status == 429:
                    log.warning("BraveSearch: rate limited by Brave API (429)")
                    return None
                if resp.status != 200:
                    log.warning("BraveSearch: unexpected status %s", resp.status)
                    return None
                return await resp.json()

        try:
            data = await _do_request()
        except Exception as exc:
            log.error("BraveSearch: request error after retries: %s", exc)
            return []

        # Only count requests that actually reached the API and got a response
        if data is None:
            return []

        self._requests_used += 1

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                }
            )

        return results

    # ------------------------------------------------------------------
    # Search + ingest into FAISS
    # ------------------------------------------------------------------

    async def search_and_ingest(self, query: str) -> Dict:
        """
        Search Brave, then scrape each result URL and store in the RAG/FAISS
        database so JRVS can learn from the retrieved content.

        Returns a summary dict with keys:
          query, results_found, pages_ingested, requests_used, requests_remaining
        """
        from scraper.web_scraper import web_scraper  # local import to avoid circular

        results = await self.search(query)
        if not results:
            return {
                "query": query,
                "results_found": 0,
                "pages_ingested": 0,
                "requests_used": self._requests_used,
                "requests_remaining": self.requests_remaining,
            }

        pages_ingested = 0

        if self.auto_scrape:
            urls = [r["url"] for r in results if r.get("url")]
            doc_ids = await web_scraper.scrape_multiple_urls(urls, max_concurrent=3)
            pages_ingested = len(doc_ids)
        else:
            # Store only the snippets (no full page scrape)
            from rag.retriever import rag_retriever

            for item in results:
                if not item.get("description"):
                    continue
                content = f"{item['title']}\n\n{item['description']}"
                await rag_retriever.add_document(
                    content=content,
                    title=item["title"],
                    url=item["url"],
                    metadata={"source": "brave_search", "query": query},
                )
                pages_ingested += 1

        return {
            "query": query,
            "results_found": len(results),
            "pages_ingested": pages_ingested,
            "requests_used": self._requests_used,
            "requests_remaining": self.requests_remaining,
            "sources": [
                {"title": r.get("title", ""), "url": r.get("url", "")}
                for r in results if r.get("url")
            ],
        }

    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def get_status(self) -> Dict:
        return {
            "configured": self.is_configured,
            "max_requests": self.max_requests,
            "requests_used": self._requests_used,
            "requests_remaining": self.requests_remaining,
            "results_per_query": self.results_per_query,
            "auto_scrape": self.auto_scrape,
        }


# Global singleton
brave_search = BraveSearchClient()
