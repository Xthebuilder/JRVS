# Jarvis AI - Complete Setup Guide

## 🚀 Quick Start (3 Minutes)

### **Step 1: Start Ollama** (if not running)
```bash
ollama serve
```

### **Step 2: Start Jarvis API Backend**
```bash
cd /path/to/JRVS
./start-api.sh

# Or manually:
python api/server.py
```

You should see:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8010
```

### **Step 3: Start Next.js Frontend**
```bash
# Install dependencies (first time only)
npm install

# Start development server
npm run dev
```

Open: **http://localhost:3000**

---

## 📋 Complete Setup Options

### **Option A: Simple HTML Frontend** (No Build Required)

1. **Start API:**
   ```bash
   python api/server.py
   ```

2. **Open in Browser:**
   ```bash
   firefox frontend-example.html
   # or
   chrome frontend-example.html
   ```

**Pros:**
- No build step
- Works immediately
- Single file

**Cons:**
- Basic UI
- No hot reload

---

### **Option B: Next.js App** (Full-Featured)

1. **Start API:**
   ```bash
   ./start-api.sh
   ```

2. **Install Dependencies:**
   ```bash
   npm install
   ```

3. **Configure Environment:**
   Already created `.env.local`:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8010/api
   ```

4. **Start Dev Server:**
   ```bash
   npm run dev
   ```

5. **Access:**
   - App: http://localhost:3000
   - API Docs: http://localhost:8010/docs

**Pros:**
- Modern UI (Tailwind CSS)
- Hot reload
- TypeScript
- Production ready

---

### **Option C: Docker (Production)**

1. **Build:**
   ```bash
   docker-compose up --build
   ```

2. **Access:**
   - Jarvis CLI: `docker exec -it jarvis_ai_agent python main.py`
   - Ollama: http://localhost:11434
   - API: http://localhost:8010

---

## 🔧 API Endpoints Reference

### **Chat**
```bash
# Simple chat
curl -X POST http://localhost:8010/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello Jarvis"}'

# Response
{
  "response": "Hello! How can I help you?",
  "session_id": "uuid",
  "model_used": "gemma3:4b"
}
```

### **Models**
```bash
# List models
curl http://localhost:8010/api/models

# Switch model
curl -X POST http://localhost:8010/api/models/switch/deepseek-r1:14b
```

### **Calendar**
```bash
# Get upcoming events
curl http://localhost:8010/api/calendar/events?days=7

# Create event
curl -X POST http://localhost:8010/api/calendar/events \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Team Meeting",
    "event_date": "2025-11-10T14:30:00",
    "description": "Weekly sync"
  }'

# Complete event
curl -X POST http://localhost:8010/api/calendar/events/1/complete
```

### **Knowledge Base**
```bash
# Scrape website
curl -X POST http://localhost:8010/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.react.dev"}'

# Search documents
curl "http://localhost:8010/api/search?query=react%20hooks&limit=5"
```

---

## 🧪 Testing the Integration

### **Test 1: Chat Works**
```bash
curl -X POST http://localhost:8010/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2+2?"}'
```

Expected: JSON response with answer

### **Test 2: Frontend Connects**
1. Open http://localhost:3000
2. Type "Hello"
3. Should get response from Jarvis

### **Test 3: Calendar Integration**
1. In frontend, type: "meeting tomorrow at 10am"
2. Should create calendar event

---

## 📁 Files Created

### **Backend API:**
- `api/server.py` - FastAPI server
- `api/__init__.py` - Package marker
- `start-api.sh` - Startup script

### **Frontend:**
- `lib/jarvis-api.ts` - TypeScript API client
- `app/components/JarvisChat.tsx` - Chat UI component
- `.env.local` - Environment config

### **Documentation:**
- `README_FRONTEND.md` - Full API docs
- `QUICKSTART.md` - This file

---

## 🐛 Troubleshooting

### **"Connection refused" error:**
```bash
# Make sure API is running
python api/server.py

# Check if port 8010 is in use
lsof -i :8010
```

### **"Ollama not running":**
```bash
# Start Ollama
ollama serve

# Test
curl http://localhost:11434/api/tags
```

### **"Module not found" in frontend:**
```bash
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
```

### **CORS errors:**
API already configured for `allow_origins=["*"]`
For production, update `api/server.py`:
```python
allow_origins=["https://yourdomain.com"]
```

---

## 🎯 Next Steps

### **1. Customize the UI**
Edit `app/components/JarvisChat.tsx` for styling

### **2. Add Features**
The API already supports:
- Calendar events
- Document scraping
- Knowledge search
- Model switching

### **3. Deploy**
```bash
# Build for production
npm run build

# Start production server
npm start
```

---

## 📚 Architecture

```
User Browser
    ↓
Next.js Frontend (localhost:3000)
    ↓ HTTP/REST
FastAPI Backend (localhost:8010)
    ↓
├─ Ollama API (localhost:11434) → AI Responses
├─ SQLite Database → Conversations, Events
├─ FAISS Vector Store → RAG Context
└─ Web Scraper → Knowledge Ingestion
```

---

## 🔐 Security Notes

**Development:**
- CORS: `allow_origins=["*"]` ✅
- No auth required ✅

**Production:**
- Update CORS to your domain
- Add API authentication (JWT)
- Use HTTPS
- Rate limiting

---

## ✅ You're Done!

You now have:
✅ Jarvis backend running on port 8010
✅ Next.js frontend on port 3000
✅ Full API integration
✅ Calendar, chat, and RAG features
✅ Production-ready architecture

**Test it:** Open http://localhost:3000 and start chatting! 🚀
