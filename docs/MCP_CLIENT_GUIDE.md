# JRVS MCP Client Guide

JRVS can now act as an **MCP Client** to connect to MCP servers and access their tools! This makes JRVS more powerful by letting it use external services and capabilities.

## What This Means

Instead of just *being* a tool for others, JRVS can now *use* tools from:
- File systems
- Databases (PostgreSQL, SQLite)
- APIs (GitHub, GitLab, Slack, etc.)
- Web search
- Memory/notes systems
- Custom MCP servers you build

## Quick Start

### 1. Configure MCP Servers

Edit `mcp/client_config.json` to add servers you want to connect to:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/xmanz"],
      "description": "File operations"
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "description": "Persistent memory"
    }
  }
}
```

### 2. Start JRVS

```bash
python main.py
```

JRVS will automatically connect to configured servers on startup.

### 3. Use MCP Commands

In JRVS, use these commands:

```bash
# List connected servers
/mcp-servers

# List all available tools
/mcp-tools

# List tools from specific server
/mcp-tools filesystem

# Call a tool directly
/mcp-call filesystem read_file '{"path": "/tmp/test.txt"}'
```

## Available MCP Servers

Here are some official MCP servers you can connect to:

### Filesystem
```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allow"]
  }
}
```
Tools: read_file, write_file, list_directory, search_files, etc.

### GitHub
```json
{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token"
    }
  }
}
```
Tools: create_issue, create_pr, search_repos, get_file_contents, etc.

### PostgreSQL
```json
{
  "postgres": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/dbname"]
  }
}
```
Tools: query, list_tables, describe_table, etc.

### Brave Search
```json
{
  "brave-search": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-brave-search"],
    "env": {
      "BRAVE_API_KEY": "your_api_key"
    }
  }
}
```
Tools: brave_web_search, brave_local_search

### Memory (Persistent Notes)
```json
{
  "memory": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"]
  }
}
```
Tools: create_memory, search_memories, etc.

### Slack
```json
{
  "slack": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-slack"],
    "env": {
      "SLACK_BOT_TOKEN": "xoxb-your-token",
      "SLACK_TEAM_ID": "T01234567"
    }
  }
}
```
Tools: send_message, list_channels, get_channel_history, etc.

## Examples

### Read a file
```
/mcp-call filesystem read_file '{"path": "/home/xmanz/notes.txt"}'
```

### Search the web (with Brave)
```
/mcp-call brave-search brave_web_search '{"query": "Python async programming", "count": 5}'
```

### Create GitHub issue
```
/mcp-call github create_issue '{"owner": "user", "repo": "project", "title": "Bug fix", "body": "Description"}'
```

### Store a memory
```
/mcp-call memory create_memory '{"content": "Remember to backup database every Sunday"}'
```

## Natural Language Integration (Coming Soon)

In the future, JRVS will automatically detect when to use MCP tools based on your natural language requests:

- "Read the file at /tmp/data.txt" → Uses filesystem server
- "Search GitHub for React repositories" → Uses GitHub server
- "Remember that I prefer Python 3.11" → Uses memory server

## Troubleshooting

### Server won't connect
- Make sure Node.js and npm are installed: `node --version`
- Try installing the server manually: `npx -y @modelcontextprotocol/server-NAME`
- Check server logs in JRVS startup output

### API key errors
- Make sure API keys are set in the `env` field
- Some servers need tokens from their respective platforms:
  - GitHub: https://github.com/settings/tokens
  - Brave Search: https://brave.com/search/api/
  - Slack: https://api.slack.com/apps

### Tool not found
- Run `/mcp-tools` to see available tools
- Each server exposes different tools - check the server's documentation

## Building Your Own MCP Server

You can build custom MCP servers for JRVS! See:
- https://modelcontextprotocol.io/
- https://github.com/modelcontextprotocol/servers

Then add it to `mcp/client_config.json`:

```json
{
  "my-custom-server": {
    "command": "python",
    "args": ["/path/to/my_server.py"]
  }
}
```

## Resources

- MCP Specification: https://modelcontextprotocol.io/
- Official Servers: https://github.com/modelcontextprotocol/servers
- JRVS MCP Server (for others to use JRVS): `mcp/server.py`
