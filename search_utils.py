"""
Unified search backend for the JRVS training pipeline.

Priority (for synchronous/scripting use):
  1. Multi-API Search Router — Brave, Exa, Tavily, Serper, SerpAPI with rotation & failover
  2. Brave Search API  — if BRAVE_API_KEY env var is set (better quality, real index)
  3. DuckDuckGo        — free fallback, no key needed

Setup APIs:
  Brave:   https://search.brave.com/
  Exa:     https://exa.ai/
  Tavily:  https://app.tavily.com/home
  Serper:  https://serper.dev/dashboard
  SerpAPI: https://serpapi.com/dashboard

Usage:
  from search_utils import search, search_backend
  results = search("latest Ollama updates", max_results=4)
  # returns formatted string of results with source names
"""

import os
import requests
import asyncio
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BRAVE_URL     = "https://api.search.brave.com/res/v1/web/search"


def search(query: str, max_results: int = 4) -> str:
    """
    Search the web and return formatted results string.
    Uses multi-API router if configured, then Brave, then DuckDuckGo.
    """
    # Try multi-API search router (async)
    try:
        result = asyncio.run(_search_with_router(query, max_results))
        if result and "Error" not in result:
            return result
    except Exception as e:
        pass  # Fall through to next option
    
    # Fall back to Brave if configured
    if BRAVE_API_KEY:
        result = _brave_search(query, max_results)
        if result and "Falling back" not in result:
            return result
    
    # Ultimate fallback: DuckDuckGo
    return _ddg_search(query, max_results)


async def _search_with_router(query: str, max_results: int) -> str:
    """Use the multi-API search router for async searches"""
    try:
        from scraper.search_router import search_router
        
        result = await search_router.search(query)
        if result.get("error"):
            return None
        
        results = result.get("results", [])[:max_results]
        if not results:
            return None
        
        parts = []
        for i, res in enumerate(results, 1):
            title       = res.get("title", "")
            description = res.get("description", "")
            url         = res.get("url", "")
            source      = url.split("/")[2].replace("www.", "") if url else "Unknown"
            provider    = result.get("provider", "multi-api")
            parts.append(f"[{i}] {title} (Source: {source}, via {provider})\n{description}")
        
        return "\n\n".join(parts)
    except Exception as e:
        return None


def search_backend() -> str:
    """Return current search backend being used"""
    try:
        from scraper.search_router import search_router
        enabled = search_router.enabled_providers
        if enabled:
            providers = ", ".join([p.value for p in enabled])
            return f"Multi-API Router ({providers})"
    except:
        pass
    
    if BRAVE_API_KEY:
        return "Brave Search"
    return "DuckDuckGo"


def _brave_search(query: str, max_results: int) -> str:
    try:
        r = requests.get(
            BRAVE_URL,
            headers={
                "Accept":               "application/json",
                "Accept-Encoding":      "gzip",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
            params={"q": query, "count": max_results},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        results = data.get("web", {}).get("results", [])
        if not results:
            return f"No results found (Brave). Falling back to DuckDuckGo...\n" \
                   + _ddg_search(query, max_results)

        parts = []
        for i, res in enumerate(results[:max_results], 1):
            title       = res.get("title", "")
            description = res.get("description", "")
            url         = res.get("url", "")
            # Extract domain as source name for citations
            source = url.split("/")[2].replace("www.", "") if url else "Unknown"
            parts.append(f"[{i}] {title} (Source: {source})\n{description}")

        return "\n\n".join(parts)

    except requests.HTTPError as e:
        if e.response.status_code == 401:
            return f"Brave API key invalid or expired. Falling back to DuckDuckGo...\n" \
                   + _ddg_search(query, max_results)
        return f"Brave search error ({e}). Falling back to DuckDuckGo...\n" \
               + _ddg_search(query, max_results)
    except Exception as e:
        return f"Brave search failed ({e}). Falling back to DuckDuckGo...\n" \
               + _ddg_search(query, max_results)


def _ddg_search(query: str, max_results: int) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        parts = []
        for i, r in enumerate(results, 1):
            title  = r.get("title", "")
            body   = r.get("body", "")
            href   = r.get("href", "")
            source = href.split("/")[2].replace("www.", "") if href else "Unknown"
            parts.append(f"[{i}] {title} (Source: {source})\n{body}")
        return "\n\n".join(parts)
    except Exception as e:
        return f"Search failed: {e}"
