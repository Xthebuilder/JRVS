#!/usr/bin/env python3
"""
Connect JRVS to available MCP servers

This script connects JRVS to:
1. Filesystem MCP server (file operations)
2. Memory MCP server (persistent notes)
3. Any other MCP servers you have installed

JRVS can then use tools from these servers!
"""

import asyncio
import json
from pathlib import Path
from mcp.client import mcp_client


async def discover_and_connect():
    """Discover and connect to available MCP servers"""

    print("🔍 Discovering MCP servers...\n")

    # Load config
    config_path = Path(__file__).parent / "mcp_config.json"

    if not config_path.exists():
        print("❌ No mcp_config.json found")
        return

    with open(config_path) as f:
        config = json.load(f)

    # Initialize MCP client
    await mcp_client.initialize()

    # Connect to each server
    for server_name, server_config in config["mcpServers"].items():
        print(f"📡 Connecting to {server_name}...")
        print(f"   Description: {server_config.get('description', 'N/A')}")
        print(f"   Command: {server_config['command']} {' '.join(server_config['args'])}")

        try:
            await mcp_client.add_server(
                name=server_name,
                command=server_config["command"],
                args=server_config["args"],
                env=server_config.get("env")
            )
            print(f"   ✅ Connected!\n")
        except Exception as e:
            print(f"   ❌ Failed: {e}\n")

    # List all available tools
    print("\n" + "="*60)
    print("📋 Available MCP Tools:")
    print("="*60 + "\n")

    all_tools = await mcp_client.list_all_tools()

    for server, tools in all_tools.items():
        print(f"\n🔧 {server.upper()} ({len(tools)} tools):")
        for tool in tools[:10]:  # Show first 10
            print(f"   • {tool['name']}")
            if tool.get('description'):
                print(f"     → {tool['description']}")

        if len(tools) > 10:
            print(f"   ... and {len(tools) - 10} more")

    print("\n" + "="*60)
    print(f"✅ Total: {sum(len(t) for t in all_tools.values())} tools available")
    print("="*60)

    # Test a tool
    print("\n🧪 Testing filesystem tool...")
    try:
        if "filesystem" in all_tools:
            result = await mcp_client.call_tool(
                "filesystem",
                "list_directory",
                {"path": "/home/xmanz"}
            )
            print("✅ Filesystem test successful!")
            print(f"   Found {len(result.get('entries', []))} items in /home/xmanz")
    except Exception as e:
        print(f"❌ Test failed: {e}")


async def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║          JRVS MCP Server Discovery & Connection           ║
╚═══════════════════════════════════════════════════════════╝
    """)

    await discover_and_connect()

    print("""
💡 Next Steps:
   1. Start JRVS web server: python3 web_server.py
   2. JRVS can now use tools from all connected MCP servers
   3. Add more MCP servers to mcp_config.json
    """)


if __name__ == "__main__":
    asyncio.run(main())
