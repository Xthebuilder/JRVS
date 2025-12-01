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
import os
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


class MCPConnection:
    """
    Connection manager for MCP server connections.

    This class wraps both the stdio transport and ClientSession contexts,
    ensuring they remain in scope and are properly cleaned up. This resolves
    the task affinity issues with anyio TaskGroups by keeping contexts
    entered/exited in the same task.

    Usage:
        async with MCPConnection(server_params) as connection:
            session = connection.session
            # Use session...
    """

    def __init__(self, server_params: StdioServerParameters):
        self.server_params = server_params
        self.stdio_ctx = None
        self.read = None
        self.write = None
        self.session = None
        self._entered = False

    async def __aenter__(self):
        """Enter both stdio and session contexts"""
        if self._entered:
            return self

        try:
            # Enter stdio context
            self.stdio_ctx = stdio_client(self.server_params)
            self.read, self.write = await self.stdio_ctx.__aenter__()

            # Create and enter session context
            self.session = ClientSession(self.read, self.write)
            await self.session.__aenter__()

            # Initialize the session
            await self.session.initialize()

            self._entered = True
            return self
        except Exception:
            # On any error, use __aexit__ to clean up whatever was entered
            # This ensures cleanup happens in the same task and reduces code duplication
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Exit both session and stdio contexts in reverse order.

        This method handles both normal cleanup and partial cleanup on errors.
        It checks what was actually entered (by checking if contexts exist) rather
        than relying solely on _entered flag, allowing it to clean up partial states.
        """
        # Exit session context first (if it was entered)
        if self.session:
            try:
                await self.session.__aexit__(exc_type, exc_val, exc_tb)
            except (Exception, asyncio.CancelledError):
                # Ignore errors during cleanup to ensure stdio context is also cleaned up
                # CancelledError can occur during shutdown when tasks are being cancelled
                pass
            self.session = None

        # Then exit stdio context (if it was entered)
        if self.stdio_ctx:
            try:
                await self.stdio_ctx.__aexit__(exc_type, exc_val, exc_tb)
            except (Exception, asyncio.CancelledError):
                # Ignore errors during cleanup
                # CancelledError can occur during shutdown when the cancel scope is cancelled
                pass
            self.stdio_ctx = None

        # Reset all state
        self.read = None
        self.write = None
        self._entered = False


class MCPClient:
    """MCP Client for connecting to multiple MCP servers"""

    def __init__(self, config_path: str = "mcp_gateway/client_config.json"):
        self.config_path = Path(config_path)
        self.servers: Dict[str, MCPServerConfig] = {}
        # Store connection managers - these keep contexts in scope
        # Each connection is entered when created and exited when disconnected
        self.connections: Dict[str, MCPConnection] = {}
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

    async def _validate_server_args(self, server_name: str, args: List[str], env: Optional[Dict[str, str]]) -> Optional[List[str]]:
        """
        Validate server arguments based on server type.
        Returns validated args if valid, None if server should be skipped.
        """
        # Handle filesystem server: validate paths
        if server_name == "filesystem" and len(args) > 2:
            # Filesystem server format: ["-y", "@modelcontextprotocol/server-filesystem", "path1", "path2", ...]
            # Skip the first two args (npx flags and package name), validate the paths
            invalid_paths = []
            valid_paths = []
            
            for path_arg in args[2:]:
                if os.path.exists(path_arg):
                    valid_paths.append(path_arg)
                else:
                    invalid_paths.append(path_arg)
            
            # If we have valid paths, use them
            if valid_paths:
                validated_args = args[:2] + valid_paths
                if invalid_paths:
                    print(f"Warning: Filesystem server '{server_name}' - filtered out {len(invalid_paths)} invalid path(s): {', '.join(invalid_paths)}")
                return validated_args
            else:
                # No valid paths - disable the server for safety
                print(f"Warning: Filesystem server '{server_name}' - all configured paths are invalid, disabling server")
                print(f"  Invalid paths: {', '.join(invalid_paths)}")
                print(f"  Update paths in {self.config_path} to enable this server")
                return None
        
        # For other servers, return args as-is
        return args

    async def _connect_server(self, name: str, config: MCPServerConfig):
        """
        Connect to an MCP server using the connection manager pattern.

        The connection manager keeps async contexts in scope, ensuring they are
        entered and exited in the same task, which resolves task affinity issues
        with anyio TaskGroups.
        """
        # Validate configuration for specific server types
        validated_args = await self._validate_server_args(name, config.args, config.env)
        
        # If validation returns None, skip this server
        if validated_args is None:
            return
        
        server_params = StdioServerParameters(
            command=config.command,
            args=validated_args,
            env=config.env
        )

        # Create connection manager and enter it
        # This keeps both stdio and session contexts in scope
        connection = MCPConnection(server_params)
        await connection.__aenter__()

        # Store the connection (it stays entered until disconnect)
        self.connections[name] = connection

        # List and cache tools
        tools_result = await connection.session.list_tools()
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
        return list(self.connections.keys())

    async def list_server_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List tools available from a specific server"""
        return self.tools_cache.get(server_name, [])

    async def list_all_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        """List all tools from all connected servers"""
        return self.tools_cache.copy()

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on a specific MCP server"""
        if server_name not in self.connections:
            raise ValueError(f"Server '{server_name}' not connected")

        connection = self.connections[server_name]
        if not connection._entered:
            raise RuntimeError(f"Connection to '{server_name}' is not active")

        result = await connection.session.call_tool(tool_name, arguments)
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
        """
        Disconnect from a specific MCP server.

        Exits the connection's async contexts, ensuring cleanup happens in the
        same task that created them, which maintains task affinity.
        """
        if server_name in self.connections:
            connection = self.connections[server_name]
            # Exit the connection (this exits both session and stdio contexts)
            # Note: exceptions are handled by cleanup() caller, but we still
            # remove the connection to prevent it from being cleaned up again
            try:
                await connection.__aexit__(None, None, None)
            finally:
                # Always remove connection even if __aexit__ raised
                del self.connections[server_name]

        if server_name in self.tools_cache:
            del self.tools_cache[server_name]

    async def cleanup(self):
        """Disconnect from all MCP servers"""
        for server_name in list(self.connections.keys()):
            try:
                await self.disconnect_server(server_name)
            except (Exception, asyncio.CancelledError) as e:
                # CancelledError can occur during shutdown when tasks are being cancelled
                # This is expected and should be handled gracefully
                if not isinstance(e, asyncio.CancelledError):
                    print(f"Error disconnecting from {server_name}: {e}")

        self.initialized = False


# Global MCP client instance
mcp_client = MCPClient()
