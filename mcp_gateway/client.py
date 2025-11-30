"""
MCP Client for JRVS - Connect to MCP servers to access external tools

This allows JRVS to be an MCP client, connecting to MCP servers like:
- Filesystem servers
- Database servers
- API servers (GitHub, Slack, etc.)
- Custom MCP servers

Usage:
    from mcp_gateway.client import mcp_client

    # Initialize and connect to servers
    await mcp_client.initialize()

    # List available tools
    tools = await mcp_client.list_all_tools()

    # Call a tool
    result = await mcp_client.call_tool("server_name", "tool_name", {"arg": "value"})
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import subprocess

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("Warning: MCP client package not installed. Install with: pip install mcp")
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection"""
    name: str
    command: str
    args: List[str]
    env: Optional[Dict[str, str]] = None


class MCPClient:
    """MCP Client for connecting to multiple MCP servers"""

    def __init__(self, config_path: str = "mcp_gateway/client_config.json"):
        self.config_path = Path(config_path)
        self.servers: Dict[str, MCPServerConfig] = {}
        self.sessions: Dict[str, ClientSession] = {}
        self.tools_cache: Dict[str, List[Dict]] = {}  # server_name -> tools
        self.initialized = False

    async def initialize(self):
        """Initialize MCP client and load server configurations"""
        if ClientSession is None:
            print("MCP client not available. Install with: pip install mcp")
            return False

        try:
            # Load server configurations
            if self.config_path.exists():
                await self._load_config()
            else:
                # Create default config
                await self._create_default_config()
                await self._load_config()

            # Connect to all configured servers
            for server_name, server_config in self.servers.items():
                try:
                    await self._connect_server(server_name, server_config)
                except Exception as e:
                    print(f"Warning: Failed to connect to MCP server '{server_name}': {e}")

            self.initialized = True
            return True

        except Exception as e:
            print(f"MCP client initialization failed: {e}")
            return False

    async def _load_config(self):
        """Load MCP server configurations from file"""
        with open(self.config_path, 'r') as f:
            config_data = json.load(f)

        for name, server_data in config_data.get("mcpServers", {}).items():
            self.servers[name] = MCPServerConfig(
                name=name,
                command=server_data["command"],
                args=server_data.get("args", []),
                env=server_data.get("env")
            )

    async def _create_default_config(self):
        """Create a default MCP client configuration file"""
        default_config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home"],
                    "description": "Access to filesystem operations"
                },
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {
                        "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token_here"
                    },
                    "description": "GitHub API access (requires token in env)"
                }
            },
            "_comment": "Add your MCP servers here. Available servers: https://github.com/modelcontextprotocol/servers"
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(default_config, f, indent=2)

        print(f"Created default MCP client config at: {self.config_path}")

    async def _connect_server(self, name: str, config: MCPServerConfig):
        """Connect to an MCP server"""
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env
        )

        # Create session
        read, write = await stdio_client(server_params)
        session = ClientSession(read, write)

        await session.__aenter__()

        # Initialize session
        await session.initialize()

        # Store session
        self.sessions[name] = session

        # List and cache tools
        tools_result = await session.list_tools()
        self.tools_cache[name] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in tools_result.tools
        ]

        print(f"Connected to MCP server '{name}' - {len(self.tools_cache[name])} tools available")

    async def list_servers(self) -> List[str]:
        """List all connected MCP servers"""
        return list(self.sessions.keys())

    async def list_server_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List tools available from a specific server"""
        return self.tools_cache.get(server_name, [])

    async def list_all_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        """List all tools from all connected servers"""
        return self.tools_cache.copy()

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on a specific MCP server"""
        if server_name not in self.sessions:
            raise ValueError(f"Server '{server_name}' not connected")

        session = self.sessions[server_name]
        result = await session.call_tool(tool_name, arguments)

        return result

    async def search_tools(self, query: str) -> List[Dict[str, Any]]:
        """Search for tools across all servers by name or description"""
        results = []
        query_lower = query.lower()

        for server_name, tools in self.tools_cache.items():
            for tool in tools:
                if (query_lower in tool["name"].lower() or
                    query_lower in tool.get("description", "").lower()):
                    results.append({
                        "server": server_name,
                        "tool": tool["name"],
                        "description": tool.get("description", ""),
                        "schema": tool.get("input_schema")
                    })

        return results

    async def disconnect_server(self, server_name: str):
        """Disconnect from a specific MCP server"""
        if server_name in self.sessions:
            session = self.sessions[server_name]
            await session.__aexit__(None, None, None)
            del self.sessions[server_name]
            del self.tools_cache[server_name]

    async def cleanup(self):
        """Disconnect from all MCP servers"""
        for server_name in list(self.sessions.keys()):
            try:
                await self.disconnect_server(server_name)
            except Exception as e:
                print(f"Error disconnecting from {server_name}: {e}")

        self.initialized = False


# Global MCP client instance
mcp_client = MCPClient()
