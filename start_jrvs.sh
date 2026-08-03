#!/bin/bash
# Quick start script for JRVS
#
# Usage:
#   ./start_jrvs.sh              — CLI mode (default)
#   ./start_jrvs.sh --voice      — start API server + voice client
#   ./start_jrvs.sh --api        — start API server only (no CLI)
#   Any other args are forwarded to main.py (e.g. --theme cyberpunk)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# JRVS_SERVER_PORT (default 8000) is read from .env so this script can never
# drift out of sync with what api/server.py actually binds to.
PORT="$(grep -oP '^JRVS_SERVER_PORT=\K.*' .env 2>/dev/null || true)"
PORT="${PORT:-8000}"

VOICE_MODE=false
API_ONLY=false
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --voice) VOICE_MODE=true ;;
        --api)   API_ONLY=true ;;
        *)       PASSTHROUGH_ARGS+=("$arg") ;;
    esac
done

echo "Starting JRVS AI Agent..."
echo ""

# Check Ollama
if ! systemctl is-active --quiet ollama && ! pgrep -f "ollama serve" > /dev/null; then
    echo "Warning: Ollama doesn't appear to be running"
    echo "   Start it with: ollama serve"
    echo ""
fi

# Check Node.js for MCP servers
if ! command -v node &> /dev/null; then
    echo "Warning: Node.js not found - MCP servers won't work"
    echo "   Install from: https://nodejs.org/"
    echo ""
fi

_start_api_and_voice() {
    echo "Starting API server on :$PORT ..."
    python api/server.py &
    API_PID=$!

    echo "Waiting for API server to be ready..."
    for i in $(seq 1 20); do
        if curl -sf http://localhost:"$PORT"/health > /dev/null 2>&1; then
            echo "API server is ready."
            break
        fi
        sleep 1
    done

    echo "Starting voice client in background..."
    python voice.py &
    VOICE_PID=$!
}

_cleanup() {
    [ -n "$VOICE_PID" ] && kill "$VOICE_PID" 2>/dev/null
    [ -n "$API_PID" ]   && kill "$API_PID"   2>/dev/null
}
trap _cleanup EXIT INT TERM

if $VOICE_MODE; then
    # Voice-only mode: API server + voice client, no CLI
    _start_api_and_voice
    wait "$VOICE_PID"

elif $API_ONLY; then
    echo "Starting API server only on :$PORT ..."
    python api/server.py

else
    # Default: CLI + API server + voice client all together
    _start_api_and_voice
    python main.py "${PASSTHROUGH_ARGS[@]}"
fi
