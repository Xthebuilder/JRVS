#!/usr/bin/env python3
"""Quick test: send a Slack message via the MCP Slack server"""

import asyncio
import json
import os
import subprocess
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "mcp_gateway" / "client_config.json"


async def test_slack():
    config = json.loads(CONFIG_PATH.read_text())
    slack_cfg = config["mcpServers"]["slack"]

    env = {**os.environ}
    for k, v in (slack_cfg.get("env") or {}).items():
        env[k] = v

    print(f"Bot token: {env.get('SLACK_BOT_TOKEN', '')[:20]}...")
    print(f"Team ID:   {env.get('SLACK_TEAM_ID', '')}")

    # Use the Slack Web API directly to post a test DM to yourself
    import urllib.request
    import urllib.parse

    token = env["SLACK_BOT_TOKEN"]

    # Step 1: find your user ID
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    if not data.get("ok"):
        print(f"Auth failed: {data.get('error')}")
        return

    user_id = data["user_id"]
    print(f"Authenticated as: {data['user']} ({user_id})")

    # Step 2: list channels and pick the first one
    req = urllib.request.Request(
        "https://slack.com/api/conversations.list?limit=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:
        chans = json.loads(resp.read())

    if not chans.get("ok") or not chans["channels"]:
        print(f"Could not list channels: {chans.get('error')}")
        return

    channel = chans["channels"][0]["id"]
    channel_name = chans["channels"][0]["name"]
    print(f"Posting to: #{channel_name}")

    # Step 3: send a test message
    payload = json.dumps({
        "channel": channel,
        "text": "Hey! JARVIS Slack integration is working!",
    }).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    if result.get("ok"):
        print("Message sent! Check your Slack DMs.")
    else:
        print(f"Failed to send: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(test_slack())
