#!/bin/bash
# jarvis.sh — start the JRVS API server + voice client with one command
# Usage: ./jarvis.sh

cd "$(dirname "$0")"

# JRVS_SERVER_PORT (default 8000) is read from .env so this script can never
# drift out of sync with what api/server.py actually binds to.
PORT="$(grep -oP '^JRVS_SERVER_PORT=\K.*' .env 2>/dev/null || true)"
PORT="${PORT:-8000}"

# ── Kill any existing JARVIS processes ──────────────────────────────────────
pkill -f "python voice.py" 2>/dev/null
if fuser "$PORT"/tcp &>/dev/null; then
    echo "Stopping existing server on port $PORT..."
    fuser -k "$PORT"/tcp &>/dev/null
    sleep 1
fi

# ── Start API server in the background ──────────────────────────────────────
echo "Starting JARVIS server..."
venv/bin/python api/server.py &>/tmp/jrvs_server.log &
SERVER_PID=$!

# ── Wait until the server is healthy (up to 20 s) ──────────────────────────
for i in $(seq 1 20); do
    if curl -sf http://localhost:"$PORT"/health &>/dev/null; then
        echo "Server ready."
        break
    fi
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "Server crashed. Check /tmp/jrvs_server.log"
        exit 1
    fi
    sleep 1
done

if ! curl -sf http://localhost:"$PORT"/health &>/dev/null; then
    echo "Server didn't start in time. Check /tmp/jrvs_server.log"
    exit 1
fi

# ── Trap Ctrl-C to cleanly stop everything ───────────────────────────────────
cleanup() {
    echo ""
    echo "Stopping JARVIS..."
    kill $SERVER_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# ── Start voice client (foreground) ─────────────────────────────────────────
echo "JARVIS online. Speak to begin."
echo "(Ctrl-C to quit)"
echo ""
venv/bin/python voice.py

# If voice.py exits on its own, also stop the server
kill $SERVER_PID 2>/dev/null
