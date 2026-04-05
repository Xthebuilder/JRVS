"""
Unified search backend for the JRVS training pipeline.

Priority:
  1. Brave Search API  — if BRAVE_API_KEY env var is set (better quality, real index)
  2. DuckDuckGo        — free fallback, no key needed

Setup Brave (free tier = 2,000 queries/month):
  1. https://brave.com/search/api/  → sign up → get API key
  2. export BRAVE_API_KEY="your_key_here"
     # or add to ~/.bashrc / ~/.profile to make permanent

Usage:
  from search_utils import search
  results = search("latest Ollama updates", max_results=4)
  # returns formatted string of results with source names
"""

import os
import requests
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BRAVE_URL     = "https://api.search.brave.com/res/v1/web/search"


def search(query: str, max_results: int = 4) -> str:
    """
    Search the web and return formatted results string.
    Uses Brave if BRAVE_API_KEY is set, otherwise DuckDuckGo.
    """
    if BRAVE_API_KEY:
        return _brave_search(query, max_results)
    return _ddg_search(query, max_results)


def search_backend() -> str:
    return "Brave Search" if BRAVE_API_KEY else "DuckDuckGo"


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
