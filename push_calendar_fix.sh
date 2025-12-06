#!/bin/bash
# Push calendar fix to GitHub

cd /home/xmanz/JRVS

echo "📝 Staging changes..."
git add web_server.py test_calendar_api.py

echo "💾 Committing changes..."
git commit -m "fix: Calendar event form submission now works properly

- Add Form import to FastAPI endpoint
- Update calendar event endpoint to properly handle form-encoded data
- Add error handling with detailed error messages
- Add test script for calendar API

🤖 Generated with MCP client

Co-Authored-By: Claude <noreply@anthropic.com>"

echo "🚀 Pushing to GitHub..."
git push mine main

echo "✅ Done! Calendar fix pushed to GitHub"
