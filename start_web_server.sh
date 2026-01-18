#!/bin/bash
# Start JRVS Web Server on Tailscale network

cd "$(dirname "$0")"

# Check Tailscale
if ! tailscale status &>/dev/null; then
    echo "❌ Error: Tailscale is not running"
    echo "   Start it with: sudo systemctl start tailscaled"
    exit 1
fi

TAILSCALE_IP=$(tailscale ip -4)
if [ -z "$TAILSCALE_IP" ]; then
    echo "❌ Error: Could not get Tailscale IP"
    exit 1
fi

echo "🚀 Starting JRVS Web Server..."
echo "   Tailscale IP: $TAILSCALE_IP"
echo "   Port: 8080"
echo ""
echo "🔒 Access JRVS at: http://$TAILSCALE_IP:8080/"
echo ""
echo "   From any Tailscale device:"
echo "   - Desktop browsers"
echo "   - Mobile devices"
echo "   - Tablets"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 web_server.py
