"""Multi-provider web search router with API rotation and failover"""
import asyncio
import logging
from typing import List, Dict, Optional, Literal
from enum import Enum
from datetime import datetime
import random

log = logging.getLogger(__name__)

from config import (
    BRAVE_API_KEY,
    BRAVE_SEARCH_RESULTS_PER_QUERY,
    BRAVE_AUTO_SCRAPE,
    EXA_API_KEY,
    EXA_SEARCH_RESULTS_PER_QUERY,
    TAVILY_API_KEY,
    TAVILY_SEARCH_RESULTS_PER_QUERY,
    SERPER_API_KEY,
    SERPER_SEARCH_RESULTS_PER_QUERY,
    SERPAPI_API_KEY,
    SERPAPI_SEARCH_RESULTS_PER_QUERY,
    SEARCH_API_ROTATION_STRATEGY,
    SEARCH_API_FAILOVER_ENABLED,
    SEARCH_AUTO_SCRAPE,
    TIMEOUTS,
)

try:
    from scraper.brave_search import BraveSearchClient
except ImportError:
    BraveSearchClient = None

try:
    from scraper.exa_search import ExaSearchClient
except ImportError:
    ExaSearchClient = None

try:
    from scraper.tavily_search import TavilySearchClient
except ImportError:
    TavilySearchClient = None

try:
    from scraper.serper_search import SerperSearchClient
except ImportError:
    SerperSearchClient = None

try:
    from scraper.serpapi_search import SerpAPISearchClient
except ImportError:
    SerpAPISearchClient = None


class SearchProvider(str, Enum):
    """Available search providers"""
    BRAVE = "brave"
    EXA = "exa"
    TAVILY = "tavily"
    SERPER = "serper"
    SERPAPI = "serpapi"


class RotationStrategy(str, Enum):
    """API rotation strategies"""
    ROUND_ROBIN = "round-robin"
    RANDOM = "random"
    LEAST_RECENTLY_USED = "least-recently-used"


class SearchRouter:
    """
    Routes web searches across multiple providers with:
    - Automatic rotation (round-robin, random, or LRU)
    - Failover support (try next provider if current fails)
    - Usage tracking and statistics
    - Unified result format
    """

    def __init__(self):
        """Initialize search clients and routing state"""
        self.clients: Dict[SearchProvider, any] = {}
        self.enabled_providers: List[SearchProvider] = []
        self.rotation_index: int = 0
        self.last_used: Dict[SearchProvider, datetime] = {}
        self.call_count: Dict[SearchProvider, int] = {}
        self.error_count: Dict[SearchProvider, int] = {}
        self.rotation_strategy = RotationStrategy(SEARCH_API_ROTATION_STRATEGY)
        self.failover_enabled = SEARCH_API_FAILOVER_ENABLED
        self.auto_scrape = SEARCH_AUTO_SCRAPE

        self._initialize_clients()

    def _initialize_clients(self):
        """Initialize available search clients based on config"""
        # Brave
        if BRAVE_API_KEY:
            try:
                if BraveSearchClient:
                    from scraper.brave_search import BraveSearchClient
                    self.clients[SearchProvider.BRAVE] = BraveSearchClient()
                    self.enabled_providers.append(SearchProvider.BRAVE)
                    self.call_count[SearchProvider.BRAVE] = 0
                    self.error_count[SearchProvider.BRAVE] = 0
                    log.info("✓ Brave Search initialized")
            except Exception as e:
                log.warning(f"Failed to initialize Brave Search: {e}")

        # Exa
        if EXA_API_KEY:
            try:
                if ExaSearchClient:
                    from scraper.exa_search import ExaSearchClient
                    self.clients[SearchProvider.EXA] = ExaSearchClient()
                    self.enabled_providers.append(SearchProvider.EXA)
                    self.call_count[SearchProvider.EXA] = 0
                    self.error_count[SearchProvider.EXA] = 0
                    log.info("✓ Exa Search initialized")
            except Exception as e:
                log.warning(f"Failed to initialize Exa Search: {e}")

        # Tavily
        if TAVILY_API_KEY:
            try:
                if TavilySearchClient:
                    from scraper.tavily_search import TavilySearchClient
                    self.clients[SearchProvider.TAVILY] = TavilySearchClient()
                    self.enabled_providers.append(SearchProvider.TAVILY)
                    self.call_count[SearchProvider.TAVILY] = 0
                    self.error_count[SearchProvider.TAVILY] = 0
                    log.info("✓ Tavily Search initialized")
            except Exception as e:
                log.warning(f"Failed to initialize Tavily Search: {e}")

        # Serper
        if SERPER_API_KEY:
            try:
                if SerperSearchClient:
                    from scraper.serper_search import SerperSearchClient
                    self.clients[SearchProvider.SERPER] = SerperSearchClient()
                    self.enabled_providers.append(SearchProvider.SERPER)
                    self.call_count[SearchProvider.SERPER] = 0
                    self.error_count[SearchProvider.SERPER] = 0
                    log.info("✓ Serper Search initialized")
            except Exception as e:
                log.warning(f"Failed to initialize Serper Search: {e}")

        # SerpAPI
        if SERPAPI_API_KEY:
            try:
                if SerpAPISearchClient:
                    from scraper.serpapi_search import SerpAPISearchClient
                    self.clients[SearchProvider.SERPAPI] = SerpAPISearchClient()
                    self.enabled_providers.append(SearchProvider.SERPAPI)
                    self.call_count[SearchProvider.SERPAPI] = 0
                    self.error_count[SearchProvider.SERPAPI] = 0
                    log.info("✓ SerpAPI Search initialized")
            except Exception as e:
                log.warning(f"Failed to initialize SerpAPI Search: {e}")

        if not self.enabled_providers:
            log.warning("⚠ No web search APIs configured. Set API keys in .env or config")

    def _select_provider(self) -> Optional[SearchProvider]:
        """Select next provider based on rotation strategy"""
        if not self.enabled_providers:
            return None

        if self.rotation_strategy == RotationStrategy.ROUND_ROBIN:
            provider = self.enabled_providers[self.rotation_index % len(self.enabled_providers)]
            self.rotation_index += 1
            return provider

        elif self.rotation_strategy == RotationStrategy.RANDOM:
            return random.choice(self.enabled_providers)

        elif self.rotation_strategy == RotationStrategy.LEAST_RECENTLY_USED:
            # Select the provider that was used least recently
            return min(
                self.enabled_providers,
                key=lambda p: self.last_used.get(p, datetime.min)
            )

        return self.enabled_providers[0]

    async def search(
        self,
        query: str,
        max_retries: int = None
    ) -> Dict:
        """
        Search across providers with automatic rotation and failover.

        Returns:
            Dict with keys:
              - query: original search query
              - results: list of result dicts (title, url, description)
              - provider: which provider was used
              - results_found: count
              - error: error message if failed (None on success)
        """
        if max_retries is None:
            max_retries = len(self.enabled_providers) if self.failover_enabled else 1

        last_error = None
        providers_tried = []

        for attempt in range(max_retries):
            provider = self._select_provider()
            if not provider:
                return {
                    "query": query,
                    "results": [],
                    "provider": None,
                    "results_found": 0,
                    "error": "No search providers configured",
                }

            providers_tried.append(provider)

            try:
                log.debug(f"Searching '{query}' with {provider.value} (attempt {attempt + 1})")
                client = self.clients[provider]

                # Call provider-specific search
                results = await client.search(query)

                # Track usage
                self.call_count[provider] = self.call_count.get(provider, 0) + 1
                self.last_used[provider] = datetime.now()

                log.info(
                    f"✓ {provider.value}: {len(results)} results "
                    f"(total calls: {self.call_count[provider]})"
                )

                return {
                    "query": query,
                    "results": results,
                    "provider": provider.value,
                    "results_found": len(results),
                    "error": None,
                }

            except Exception as e:
                last_error = str(e)
                self.error_count[provider] = self.error_count.get(provider, 0) + 1
                log.warning(
                    f"✗ {provider.value} failed (attempt {attempt + 1}/{max_retries}): {e}"
                )

                if not self.failover_enabled:
                    break

        return {
            "query": query,
            "results": [],
            "provider": None,
            "results_found": 0,
            "providers_tried": [p.value for p in providers_tried],
            "error": last_error,
        }

    async def search_and_ingest(
        self,
        query: str,
        max_retries: int = None
    ) -> Dict:
        """
        Search and ingest results into RAG database.
        Uses same failover logic as search().
        """
        from scraper.web_scraper import web_scraper

        search_result = await self.search(query, max_retries)

        if search_result["error"]:
            log.error(f"Search failed: {search_result['error']}")
            return search_result

        results = search_result["results"]
        pages_ingested = 0

        if self.auto_scrape and results:
            urls = [r["url"] for r in results if r.get("url")]
            try:
                doc_ids = await web_scraper.scrape_multiple_urls(urls, max_concurrent=3)
                pages_ingested = len(doc_ids)
            except Exception as e:
                log.warning(f"Auto-scrape failed: {e}")
                pages_ingested = 0
        else:
            # Store only snippets
            from rag.retriever import rag_retriever

            for item in results:
                if not item.get("description"):
                    continue
                try:
                    content = f"{item['title']}\n\n{item['description']}"
                    await rag_retriever.add_document(
                        content=content,
                        title=item["title"],
                        url=item["url"],
                        metadata={
                            "source": f"web_search ({search_result['provider']})",
                            "query": query,
                        },
                    )
                    pages_ingested += 1
                except Exception as e:
                    log.warning(f"Failed to ingest result: {e}")

        return {
            "query": query,
            "provider": search_result.get("provider"),
            "results_found": search_result.get("results_found", 0),
            "pages_ingested": pages_ingested,
            "error": search_result.get("error"),
            "sources": [
                {"title": r.get("title", ""), "url": r.get("url", "")}
                for r in results if r.get("url")
            ],
        }

    def get_status(self) -> Dict:
        """Get router status and statistics"""
        return {
            "enabled_providers": [p.value for p in self.enabled_providers],
            "rotation_strategy": self.rotation_strategy.value,
            "failover_enabled": self.failover_enabled,
            "auto_scrape": self.auto_scrape,
            "provider_stats": {
                p.value: {
                    "calls": self.call_count.get(p, 0),
                    "errors": self.error_count.get(p, 0),
                    "last_used": self.last_used.get(p, None).isoformat()
                    if self.last_used.get(p) else None,
                }
                for p in self.enabled_providers
            },
        }

    async def cleanup(self):
        """Clean up all client connections"""
        for provider, client in self.clients.items():
            try:
                if hasattr(client, "cleanup"):
                    await client.cleanup()
                log.debug(f"Cleaned up {provider.value} client")
            except Exception as e:
                log.warning(f"Error cleaning up {provider.value}: {e}")


# Global singleton router instance
search_router = SearchRouter()
