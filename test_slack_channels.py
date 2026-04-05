#!/usr/bin/env python3
"""
Test JARVIS Slack channel routing.
Sends a sample message to every channel and demos the confidence router.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from core.slack_notifier import notify, _confidence_route, CHANNEL_KEYS, get_channel

# ── Sample messages that represent real JARVIS output ────────────────────────
TESTS = [
    {
        "label": "Morning email digest",
        "channel_key": "inbox",
        "text": (
            ":sunrise: *Morning Digest — Apr 4*\n"
            "You have 7 unread emails. Key senders: your manager (project update), "
            "GitHub (PR review needed), newsletter. No urgent flags."
        ),
    },
    {
        "label": "Daily calendar brief",
        "channel_key": "calendar",
        "text": (
            ":calendar: *Today's Schedule*\n"
            "• 10:00 AM — Standup (30 min)\n"
            "• 2:00 PM — Client call (1 hr)\n"
            "• 4:30 PM — Back-to-back conflict detected with team sync!"
        ),
    },
    {
        "label": "Weekly research brief",
        "channel_key": "research",
        "text": (
            ":mag: *Weekly Research Brief*\n"
            "Top AI tools this week: GPT-4o voice mode, Gemini 2.0 Flash. "
            "YouTube trend: Shorts are outperforming long-form for new channels. "
            "Content strategy insight: hooks under 3s = 40% higher retention."
        ),
    },
    {
        "label": "Cron job completion",
        "channel_key": "schedule",
        "text": (
            ":white_check_mark: *Scheduled job ran* — _Back up workspace files daily at midnight_\n"
            "Backed up 142 files to ~/jrvs-workspace/backups/2026-04-04. All good."
        ),
    },
    {
        "label": "Error / failure",
        "channel_key": "alerts",
        "text": (
            ":x: *Goal failed* — `weekly_youtube_report`\n"
            "Error: Google API quota exceeded. Will retry next scheduled run."
        ),
    },
    {
        "label": "Low-confidence → general (auto-routed)",
        "channel_key": None,  # let the router decide
        "text": (
            "Hey, just wanted to let you know I noticed your music folder "
            "has some new files since last time. Might be worth a look."
        ),
    },
]

# ── Run tests ────────────────────────────────────────────────────────────────
print("\nJARVIS Slack Channel Test\n" + "=" * 50)

all_passed = True
for t in TESTS:
    label = t["label"]
    key = t["channel_key"]
    text = t["text"]

    # Show routing decision
    if key is None:
        routed_key, confidence = _confidence_route(text)
        channel = get_channel(routed_key)
        routing_info = f"auto-routed → {channel} (confidence {confidence:.0%})"
    else:
        channel = get_channel(key)
        routing_info = f"direct → {channel}"

    ok = notify(text, channel_key=key)
    status = "✓" if ok else "✗"
    print(f"{status} [{label}]")
    print(f"  {routing_info}")
    if not ok:
        print(f"  FAILED — is @jarvis invited to {channel}?")
        all_passed = False

print("=" * 50)
if all_passed:
    print("All messages sent! Check your Slack channels.")
else:
    print("Some failed — invite @jarvis to the missing channels and retry.")
