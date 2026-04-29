# Multi-API Web Search Setup Guide

JRVS now supports automatic rotation and failover across 5 different web search APIs:

1. **Brave Search** — https://search.brave.com/
2. **Exa.ai** — https://exa.ai/
3. **Tavily** — https://app.tavily.com/home
4. **Serper** — https://serper.dev/dashboard
5. **SerpAPI** — https://serpapi.com/dashboard

## Features

- ✅ **Automatic Rotation** — Distributes requests across enabled APIs
- ✅ **Failover Support** — Automatically tries next API if one fails
- ✅ **Usage Tracking** — Monitor which APIs are being used and how often
- ✅ **Unified Format** — All results standardized to title/url/description
- ✅ **Round-robin, Random, or LRU Selection** — Configurable rotation strategy

## Setup Instructions

### 1. Get API Keys

Get an API key from each service you want to use (at least one):

| API | Free Tier | Link |
|-----|-----------|------|
| **Brave** | 2,000 queries/month | https://search.brave.com/ |
| **Exa** | 10,000 queries/month | https://exa.ai/ |
| **Tavily** | 1,000 queries/month | https://app.tavily.com/home |
| **Serper** | 100 free queries | https://serper.dev/dashboard |
| **SerpAPI** | 100 free searches | https://serpapi.com/dashboard |

### 2. Configure in .env

Add your API keys to `.env`:

```bash
# Brave Search
BRAVE_API_KEY="your_brave_key_here"
BRAVE_SEARCH_RESULTS_PER_QUERY=5

# Exa.ai
EXA_API_KEY="your_exa_key_here"
EXA_SEARCH_RESULTS_PER_QUERY=5

# Tavily
TAVILY_API_KEY="your_tavily_key_here"
TAVILY_SEARCH_RESULTS_PER_QUERY=5

# Serper
SERPER_API_KEY="your_serper_key_here"
SERPER_SEARCH_RESULTS_PER_QUERY=5

# SerpAPI
SERPAPI_API_KEY="your_serpapi_key_here"
SERPAPI_SEARCH_RESULTS_PER_QUERY=5

# Router Configuration
SEARCH_API_ROTATION_STRATEGY="round-robin"  # Options: round-robin, random, least-recently-used
SEARCH_API_FAILOVER_ENABLED="true"          # Enable automatic failover if API fails
SEARCH_AUTO_SCRAPE="true"                   # Automatically scrape result pages
```

### 3. Usage

The search router is automatically used when:

1. **CLI web search**: `jarvis search unemployment statistics`
2. **Web scraper**: `web_scraper.search_and_scrape("query")`
3. **Search utils**: `search("query")`

All calls will automatically rotate through enabled APIs.

## Rotation Strategies

### Round-Robin (Default)
- Uses each enabled API in sequence
- Best for: Distributed load balancing

```
Request 1 → Brave
Request 2 → Exa
Request 3 → Tavily
Request 4 → Serper
Request 5 → SerpAPI
Request 6 → Brave (cycles)
```

### Random
- Picks a random enabled API for each request
- Best for: Unpredictable usage patterns

### Least-Recently-Used
- Picks the API that hasn't been used recently
- Best for: Maximizing diverse API usage

## Failover Behavior

When `SEARCH_API_FAILOVER_ENABLED=true`:

1. Primary API fails (402, 429, timeout, etc.)
2. Router automatically tries next API
3. Continues until success or all APIs exhausted
4. Returns error with `providers_tried` list

When `SEARCH_API_FAILOVER_ENABLED=false`:
- Only tries selected API once
- Fails immediately if it returns an error

## Status & Statistics

Check which APIs are configured and usage stats:

```python
from scraper.search_router import search_router

# View enabled providers and statistics
print(search_router.get_status())
# Output:
# {
#   "enabled_providers": ["brave", "exa", "tavily"],
#   "rotation_strategy": "round-robin",
#   "failover_enabled": true,
#   "auto_scrape": true,
#   "provider_stats": {
#     "brave": {"calls": 5, "errors": 0, "last_used": "2026-04-28T10:30:00"},
#     "exa": {"calls": 3, "errors": 1, "last_used": "2026-04-28T10:28:00"},
#     ...
#   }
# }
```

## Troubleshooting

### Error: "No search providers configured"
- Make sure at least one API key is set in `.env`
- Restart JRVS after adding keys

### Error: "402 Payment Required"
- Free tier quota exceeded
- Check API dashboard for usage statistics
- Wait for quota reset (usually monthly)

### Error: "401 Unauthorized"
- API key is invalid or expired
- Regenerate key from API dashboard
- Update `.env` and restart

### Rotation not working
- Check `SEARCH_API_ROTATION_STRATEGY` is set correctly
- Verify multiple APIs are configured
- Check logs for errors: `tail -f data/logs/*.log`

## Performance Tips

1. **Use multiple APIs** — Redundancy protects against quota limits
2. **Monitor usage** — Use `get_status()` to track which APIs are being used
3. **Adjust rotation** — Use `least-recently-used` to balance quotas
4. **Auto-scrape** — Disable `SEARCH_AUTO_SCRAPE` if only need snippets (faster, fewer requests)

## API Feature Comparison

| Feature | Brave | Exa | Tavily | Serper | SerpAPI |
|---------|-------|-----|--------|--------|---------|
| Web Search | ✅ | ✅ | ✅ | ✅ | ✅ |
| Free Tier | 2K/mo | 10K/mo | 1K/mo | 100 | 100 |
| Real-time Results | ✅ | ✅ | ✅ | ✅ | ✅ |
| Auth | Bearer | Bearer | API Key | X-API-Key | API Key |
| Response Format | JSON | JSON | JSON | JSON | JSON |

## Legacy Brave-Only Mode

If you only want to use Brave Search (old behavior):

```bash
# Set only this in .env
BRAVE_API_KEY="your_key_here"

# JRVS will automatically fall back to Brave if no other APIs are configured
```

---

**Need Help?** Check the logs:
```bash
tail -f data/logs/scraper.brave_search.log
tail -f data/logs/scraper.search_router.log
```
