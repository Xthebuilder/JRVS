#!/usr/bin/env python3
"""
Test script for JRVS MCP Client

This script demonstrates connecting to MCP servers and calling tools.
"""

import asyncio
from mcp_gateway.client import mcp_client

async def main():
    print("🔌 Testing JRVS MCP Client\n")

    # Initialize
    print("Initializing MCP client...")
    success = await mcp_client.initialize()

    if not success:
        print("❌ Failed to initialize MCP client")
        return

    # List servers
    servers = await mcp_client.list_servers()
    print(f"\n✓ Connected to {len(servers)} server(s):")
    for server in servers:
        print(f"  • {server}")

    # List all tools
    print("\n📋 Available tools:")
    all_tools = await mcp_client.list_all_tools()
    for server, tools in all_tools.items():
        print(f"\n  {server}:")
        for tool in tools[:3]:  # Show first 3 tools
            print(f"    • {tool['name']} - {tool.get('description', 'No description')}")
        if len(tools) > 3:
            print(f"    ... and {len(tools) - 3} more")

    # Example tool call (if filesystem server is available)
    if "filesystem" in servers:
        print("\n🔧 Testing filesystem tool...")
        try:
            # List files in current directory
            result = await mcp_client.call_tool(
                "filesystem",
                "list_directory",
                {"path": "."}
            )
            print(f"✓ Listed directory successfully")
        except Exception as e:
            print(f"⚠️  Tool call failed: {e}")

    # Cleanup
    print("\n🧹 Cleaning up...")
    await mcp_client.cleanup()
    print("✓ Done!")

if __name__ == "__main__":
    asyncio.run(main())
