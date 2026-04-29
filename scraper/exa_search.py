"""Exa.ai search API client"""
import aiohttp
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

from config import (
    EXA_API_KEY,
    EXA_SEARCH_RESULTS_PER_QUERY,
    TIMEOUTS,
)
from core.lazy_loader import retry_on_failure

EXA_SEARCH_URL = "https://api.exa.ai/search"


class ExaSearchClient:
    """Exa.ai search client"""

    def __init__(self):
        self.api_key: str = EXA_API_KEY
        self.results_per_query: int = EXA_SEARCH_RESULTS_PER_QUERY
        self._requests_used: int = 0
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=TIMEOUTS.get("web_scraping", 45))
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def search(self, query: str) -> List[Dict]:
        """Search using Exa API"""
        if not self.is_configured:
            log.warning("Exa: no API key configured")
            return []

        payload = {
            "query": query,
            "numResults": self.results_per_query,
            "contents": {
                "text": True,
            },
        }

        headers = {"Authorization": f"Bearer {self.api_key}"}

        @retry_on_failure(max_retries=1, delay=0.5, backoff=1.5)
        async def _do_request() -> dict | None:
            session = await self._get_session()
            async with session.post(EXA_SEARCH_URL, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    log.error("Exa: invalid API key (401)")
                    return None
                if resp.status == 429:
                    log.warning("Exa: rate limited (429)")
                    return None
                if resp.status != 200:
                    log.warning(f"Exa: unexpected status {resp.status}")
                    return None
                return await resp.json()

        try:
            data = await _do_request()
        except Exception as exc:
            log.error(f"Exa: request error: {exc}")
            return []

        if data is None:
            return []

        self._requests_used += 1

        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("text", "")[:500],  # Truncate long text
                }
            )

        return results

    async def cleanup(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def get_status(self) -> Dict:
        return {
            "configured": self.is_configured,
            "requests_used": self._requests_used,
            "results_per_query": self.results_per_query,
        }


# Global singleton
exa_search = ExaSearchClient()
