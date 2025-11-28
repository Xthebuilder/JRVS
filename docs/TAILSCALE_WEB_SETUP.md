# JRVS on Tailscale - Private Web Access 🔒

JRVS is now configured to run as a web server **only accessible on your Tailscale network**. This means you can access JRVS from all your devices (phone, tablet, other computers) while keeping it completely private and secure.

## 🎯 What This Gives You

- ✅ **Web UI** - Modern chat interface in your browser
- ✅ **Multi-device** - Access from phone, tablet, laptop, desktop
- ✅ **Secure** - Only accessible on Tailscale (not public internet)
- ✅ **Real-time** - WebSocket-based live chat
- ✅ **All Features** - Full JRVS functionality (MCP, calendar, RAG, etc.)

## 🚀 Quick Start

### Start the Web Server

```bash
./start_web_server.sh
```

### Access JRVS

From any device on your Tailscale network, open your browser:

```
http://100.113.61.115:8080/
```

Replace `100.113.61.115` with your actual Tailscale IP (shown when you start the server).

## 📱 Access from Your Devices

### Desktop/Laptop
1. Make sure Tailscale is running
2. Open browser
3. Go to `http://100.113.61.115:8080/`

### iPhone/iPad
1. Install Tailscale app from App Store
2. Connect to your Tailnet
3. Open Safari or Chrome
4. Go to `http://100.113.61.115:8080/`

### Android
1. Install Tailscale app from Play Store
2. Connect to your Tailnet
3. Open Chrome or Firefox
4. Go to `http://100.113.61.115:8080/`

## 🔧 Features Available

### Web Chat Interface
- Real-time messaging
- Automatic tool selection (MCP agent)
- Tool usage indicators
- Timestamped responses
- Auto-reconnect

### REST API Endpoints

#### Status
```bash
GET http://100.113.61.115:8080/api/status
```
Returns: MCP servers, Ollama models, current model

#### Calendar
```bash
# Get month calendar
GET http://100.113.61.115:8080/api/calendar/month?year=2025&month=11

# Add event
POST http://100.113.61.115:8080/api/calendar/event
Body: {
  "title": "Meeting",
  "date": "2025-11-12",
  "time": "14:00",
  "description": "Team sync"
}
```

#### MCP Servers
```bash
# List servers
GET http://100.113.61.115:8080/api/mcp/servers

# List tools
GET http://100.113.61.115:8080/api/mcp/tools
GET http://100.113.61.115:8080/api/mcp/tools?server=filesystem
```

## 🔒 Security

### Why Tailscale-Only?

1. **Not Public** - Server only binds to Tailscale IP (100.x.x.x)
2. **Encrypted** - All Tailscale traffic is encrypted
3. **Authenticated** - Only your Tailscale devices can access
4. **No Port Forwarding** - No firewall changes needed
5. **Private** - Not exposed to the internet

### What's Protected?

- ✅ JRVS web interface
- ✅ API endpoints
- ✅ WebSocket connections
- ✅ All your data and conversations
- ✅ MCP tool access

### Verification

Server is bound to: `100.113.61.115` (your Tailscale IP)
**Not accessible from:**
- Public internet
- Local network (192.168.x.x)
- Localhost (127.0.0.1)

**Only accessible from:**
- Your Tailscale-connected devices

## 🔄 Auto-Start on Boot (Optional)

To have JRVS web server start automatically:

### Install Service

```bash
sudo cp jrvs-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable jrvs-web
sudo systemctl start jrvs-web
```

### Check Status

```bash
sudo systemctl status jrvs-web
```

### View Logs

```bash
sudo journalctl -u jrvs-web -f
```

### Stop Service

```bash
sudo systemctl stop jrvs-web
```

### Disable Auto-Start

```bash
sudo systemctl disable jrvs-web
```

## 📖 Usage Examples

### Web Interface

1. **Open browser** to `http://100.113.61.115:8080/`
2. **Chat naturally** - Type your message and press Enter
3. **See tools used** - Blue badges show when MCP tools are called
4. **Real-time responses** - See JRVS thinking and responding live

Example chat:
```
You: read the file /tmp/test.txt

🔧 Tools Used: filesystem/read_file

JRVS: Here's the content of /tmp/test.txt:
[file contents shown]
```

### Mobile Usage

Perfect for:
- Quick questions on your phone
- Checking your calendar
- Accessing JRVS while away from desk
- Using voice typing on mobile

### API Usage

```bash
# From any Tailscale device
curl http://100.113.61.115:8080/api/status

# Get calendar
curl http://100.113.61.115:8080/api/calendar/month

# Add event
curl -X POST http://100.113.61.115:8080/api/calendar/event \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "title=Dentist&date=2025-11-15&time=14:30"
```

## 🎨 Web UI Features

### Modern Design
- Gradient purple background
- Clean, modern chat interface
- Responsive design (works on all screen sizes)
- Smooth animations

### Smart Features
- **Auto-scroll** - Always shows latest messages
- **Tool indicators** - See when JRVS uses tools
- **Status updates** - "Analyzing request...", "Generating response..."
- **Timestamps** - See when messages were sent
- **Auto-reconnect** - Reconnects if connection drops

## 🔧 Troubleshooting

### Can't access the web interface

**Check Tailscale is running:**
```bash
tailscale status
```

**Verify server is running:**
```bash
ps aux | grep web_server.py
```

**Check firewall (if needed):**
```bash
sudo firewall-cmd --list-all
# Port 8080 should be open on Tailscale interface
```

### Connection drops

The web interface auto-reconnects. If it doesn't:
1. Refresh the page
2. Check Tailscale connection
3. Restart the web server

### Slow responses

- Switch to a faster Ollama model
- Check MCP server connections
- Monitor system resources

## 📊 Performance

### Expected Response Times
- Simple chat: 1-3 seconds
- With tool usage: 2-5 seconds
- Complex queries: 5-10 seconds

### Resource Usage
- RAM: ~500MB-1GB
- CPU: Varies with Ollama model
- Network: Minimal (only Tailscale traffic)

## 🔄 Updating

If you make changes to JRVS:

1. **Stop the server** (Ctrl+C or `systemctl stop jrvs-web`)
2. **Make your changes**
3. **Restart** (`./start_web_server.sh` or `systemctl start jrvs-web`)

## 🎯 Advanced: Multiple Servers

You can run multiple JRVS instances on different ports:

```bash
# Edit web_server.py, change port = 8080 to port = 8081
# Or pass port as argument (requires code modification)
```

## 📱 Bookmarking on Mobile

### iPhone/iPad
1. Open `http://100.113.61.115:8080/` in Safari
2. Tap Share button
3. Select "Add to Home Screen"
4. Name it "JRVS"
5. Tap "Add"

Now JRVS appears as an app icon!

### Android
1. Open `http://100.113.61.115:8080/` in Chrome
2. Tap menu (3 dots)
3. Select "Add to Home screen"
4. Name it "JRVS"
5. Tap "Add"

## 🌐 Accessing from Other Networks

With Tailscale, you can access JRVS:
- **At home** - Connected to home WiFi + Tailscale
- **At work** - Connected to work network + Tailscale
- **On cellular** - Mobile data + Tailscale
- **On public WiFi** - Coffee shop + Tailscale

Always secure, always private! 🔒

## ⚡ Quick Commands Reference

```bash
# Start web server (manual)
./start_web_server.sh

# Start as service
sudo systemctl start jrvs-web

# Check status
sudo systemctl status jrvs-web

# View logs
sudo journalctl -u jrvs-web -f

# Stop server
sudo systemctl stop jrvs-web

# Check Tailscale IP
tailscale ip -4

# Check Tailscale devices
tailscale status
```

## 🎉 Benefits

### Before (CLI only)
- ✅ Powerful features
- ❌ Command line only
- ❌ One device (where JRVS is installed)
- ❌ Manual commands

### Now (Web + CLI)
- ✅ All the same powerful features
- ✅ Modern web interface
- ✅ Access from any device
- ✅ Natural language chat
- ✅ Mobile-friendly
- ✅ Secure (Tailscale-only)

## 📚 Related Documentation

- **README.md** - Main JRVS documentation
- **MCP_CLIENT_GUIDE.md** - MCP features
- **INTELLIGENT_AGENT_GUIDE.md** - How the AI agent works
- **SETUP_COMPLETE.md** - Initial setup

---

**You can now access JRVS from any device on your Tailscale network!** 🎉

```bash
./start_web_server.sh
```

Then open `http://100.113.61.115:8080/` in your browser!
