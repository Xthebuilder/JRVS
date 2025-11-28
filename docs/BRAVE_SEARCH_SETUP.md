# Brave Search API Setup for JRVS

This guide will help you enable web search capabilities in JRVS using the Brave Search API.

## Why Brave Search?

- **Privacy-focused**: Brave doesn't track your searches
- **Free tier**: 2,000 queries per month (plenty for personal use)
- **Fast**: Direct API access without rate limiting issues
- **Quality**: Brave has its own independent search index

## Step-by-Step Setup

### 1. Get Your Brave Search API Key

1. **Visit** https://brave.com/search/api/
2. **Sign up** for a free account or log in
3. **Subscribe** to the free tier (Data for AI):
   - Go to your dashboard
   - Select "Data for AI" plan
   - It's FREE for up to 2,000 queries/month
4. **Copy your API key** from the dashboard

### 2. Add API Key to JRVS

1. **Open** `mcp/client_config.json`

2. **Find** the brave-search config in `_disabled_servers`:
```json
"brave-search": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-brave-search"],
  "env": {
    "BRAVE_API_KEY": "GET_YOUR_KEY_FROM_https://brave.com/search/api/"
  },
  "description": "Web search - DISABLED until you add your Brave API key"
}
```

3. **Replace** `GET_YOUR_KEY_FROM_...` with your actual API key:
```json
"BRAVE_API_KEY": "BSA1234567890abcdef..."
```

4. **Move** the entire brave-search config from `_disabled_servers` to `mcpServers`:

**Before:**
```json
{
  "mcpServers": {
    "filesystem": {...},
    "memory": {...}
  },
  "_disabled_servers": {
    "brave-search": {...}  ← Move this
  }
}
```

**After:**
```json
{
  "mcpServers": {
    "filesystem": {...},
    "memory": {...},
    "brave-search": {...}  ← Now active!
  },
  "_disabled_servers": {}
}
```

### 3. Restart JRVS

```bash
python main.py
```

You should see:
```
Connected to 3 MCP server(s): filesystem, memory, brave-search
```

### 4. Test Web Search

In JRVS, try:

```bash
# List tools to confirm brave-search is connected
/mcp-tools brave-search

# Search the web
/mcp-call brave-search brave_web_search '{"q": "Python async programming", "count": 5}'

# Local business search
/mcp-call brave-search brave_local_search '{"q": "pizza near me", "count": 3}'
```

## Usage Examples

### Web Search
```bash
/mcp-call brave-search brave_web_search '{"q": "latest AI news", "count": 10}'
```

Returns: Title, URL, description, and snippet for each result

### Local Search
```bash
/mcp-call brave-search brave_local_search '{"q": "coffee shops in San Francisco", "count": 5}'
```

Returns: Business name, address, phone, rating, hours

## API Limits

**Free Tier (Data for AI):**
- 2,000 queries/month
- No credit card required
- Rate limit: ~1 request/second
- Perfect for personal JRVS usage

**If you exceed the limit:**
- Upgrade to paid plan (starts at $5/month for 15k queries)
- Or wait until next month for free tier reset

## Monitoring Usage

1. Visit https://brave.com/search/api/dashboard
2. Check your usage stats
3. Set up alerts if needed

## Troubleshooting

### "API key invalid" error
- Double-check your API key is correct
- Make sure you're subscribed to the Data for AI plan
- API key might take a few minutes to activate after signup

### Connection timeout
- Check your internet connection
- Brave API might be temporarily down (rare)
- Try again in a few minutes

### No results returned
- Check your search query format
- Some queries might not return results
- Try a more general search term

## Alternative: Use Without Brave Search

JRVS works great without web search! You already have:
- ✅ **Filesystem** - File operations
- ✅ **Memory** - Persistent notes
- ✅ **Web scraping** - Built-in scraper with `/scrape` command
- ✅ **RAG** - Search your scraped documents

The built-in web scraper can handle most needs:
```bash
/scrape https://example.com
/search "topic I'm interested in"
```

## Security Notes

- **Keep your API key private** - Don't share it or commit to Git
- API key is stored locally in `mcp/client_config.json`
- Consider using environment variables for production use
- Brave doesn't track or log your searches (privacy-focused)

## Additional Resources

- [Brave Search API Docs](https://brave.com/search/api/)
- [Brave Search API GitHub](https://github.com/brave/brave-search-api)
- [MCP Brave Search Server](https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search)

---

**Ready to search!** 🔍 Once configured, JRVS can search the web on demand for real-time information.
