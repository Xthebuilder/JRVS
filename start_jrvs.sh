#!/bin/bash
# Quick start script for JRVS

echo "🤖 Starting JRVS AI Agent..."
echo ""

# Check Ollama
if ! systemctl is-active --quiet ollama && ! pgrep -f "ollama serve" > /dev/null; then
    echo "⚠️  Warning: Ollama doesn't appear to be running"
    echo "   Start it with: ollama serve"
    echo ""
fi

# Check Node.js for MCP servers
if ! command -v node &> /dev/null; then
    echo "⚠️  Warning: Node.js not found - MCP servers won't work"
    echo "   Install from: https://nodejs.org/"
    echo ""
fi

# Start JRVS
cd "$(dirname "$0")"
python main.py "$@"
