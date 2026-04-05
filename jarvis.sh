#!/bin/bash
# jarvis.sh — start the JRVS API server + voice client with one command
# Usage: ./jarvis.sh

cd "$(dirname "$0")"

# ── Kill any existing JARVIS processes ──────────────────────────────────────
pkill -f "python voice.py" 2>/dev/null
if fuser 8000/tcp &>/dev/null; then
    echo "Stopping existing server on port 8000..."
    fuser -k 8000/tcp &>/dev/null
    sleep 1
fi

# ── Start API server in the background ──────────────────────────────────────
echo "Starting JARVIS server..."
venv/bin/python api/server.py &>/tmp/jrvs_server.log &
SERVER_PID=$!

# ── Wait until the server is healthy (up to 20 s) ──────────────────────────
for i in $(seq 1 20); do
    if curl -sf http://localhost:8000/health &>/dev/null; then
        echo "Server ready."
        break
    fi
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "Server crashed. Check /tmp/jrvs_server.log"
        exit 1
    fi
    sleep 1
done

if ! curl -sf http://localhost:8000/health &>/dev/null; then
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
