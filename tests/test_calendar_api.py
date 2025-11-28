#!/usr/bin/env python3
"""Test calendar API endpoint"""

import asyncio
import httpx
from datetime import datetime

async def test_calendar():
    """Test adding calendar event via API"""

    # Start by testing the calendar module directly
    print("1. Testing calendar module directly...")
    from core.calendar import calendar
    from datetime import datetime

    try:
        await calendar.initialize()
        event_id = await calendar.add_event(
            title="Direct Test Event",
            event_date=datetime.now(),
            description="Testing calendar directly"
        )
        print(f"✓ Direct calendar test passed! Event ID: {event_id}")

        # Get events
        events = await calendar.get_today_events()
        print(f"✓ Today's events: {len(events)}")
        for event in events:
            print(f"  - {event['title']} at {event['event_date']}")
    except Exception as e:
        print(f"✗ Direct calendar test failed: {e}")
        import traceback
        traceback.print_exc()

    # Now test via HTTP API
    print("\n2. Testing via HTTP API...")
    try:
        async with httpx.AsyncClient() as client:
            # Get Tailscale IP
            import subprocess
            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True
            )
            tailscale_ip = result.stdout.strip() if result.returncode == 0 else "localhost"

            url = f"http://{tailscale_ip}:8080/api/calendar/event"

            data = {
                "title": "API Test Event",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "time": "14:30",
                "description": "Testing via HTTP API"
            }

            print(f"Posting to: {url}")
            print(f"Data: {data}")

            response = await client.post(url, data=data)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")

            if response.status_code == 200:
                print("✓ API test passed!")
            else:
                print(f"✗ API test failed with status {response.status_code}")

    except Exception as e:
        print(f"✗ API test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_calendar())
