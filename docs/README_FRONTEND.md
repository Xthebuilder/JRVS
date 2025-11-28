# Jarvis Frontend Integration Guide

## Quick Start

### 1. Install API Dependencies
```bash
pip install fastapi uvicorn websockets pydantic
```

### 2. Start the API Server
```bash
cd /home/xavier/jarvis_ai_agent
python api/server.py
```

Server runs at: `http://localhost:8000`

### 3. Open Frontend Example
```bash
# Just open the HTML file in your browser
firefox frontend-example.html
# or
chrome frontend-example.html
```

---

## API Endpoints

### Chat
```bash
POST /api/chat
{
  "message": "Hello Jarvis",
  "session_id": "optional-uuid",
  "stream": false
}

Response:
{
  "response": "Hello! How can I help?",
  "session_id": "uuid",
  "model_used": "gemma3:12b",
  "context_used": "..."
}
```

### WebSocket Streaming
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat');
ws.send(JSON.stringify({ message: "Hello" }));
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'chunk') {
    console.log(data.content);
  }
};
```

### Models
```bash
GET  /api/models                    # List models
POST /api/models/switch/{model}     # Switch model
```

### Calendar
```bash
GET  /api/calendar/events?days=7    # Upcoming events
GET  /api/calendar/today            # Today's events
POST /api/calendar/events           # Create event
{
  "title": "Meeting",
  "event_date": "2025-11-10T14:30:00",
  "description": "Team sync"
}

POST /api/calendar/events/{id}/complete
DELETE /api/calendar/events/{id}
```

### Knowledge Base
```bash
POST /api/scrape
{
  "url": "https://example.com"
}

GET /api/search?query=react&limit=5
```

### History
```bash
GET /api/history/{session_id}?limit=10
```

### Stats
```bash
GET /api/stats
GET /api/health
```

---

## Frontend Frameworks

### React Example
```jsx
import { useState } from 'react';

function JarvisChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');

  const sendMessage = async () => {
    const response = await fetch('http://localhost:8000/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: input })
    });
    const data = await response.json();

    setMessages([
      ...messages,
      { role: 'user', content: input },
      { role: 'assistant', content: data.response }
    ]);
    setInput('');
  };

  return (
    <div>
      {messages.map((msg, i) => (
        <div key={i}>{msg.role}: {msg.content}</div>
      ))}
      <input value={input} onChange={e => setInput(e.target.value)} />
      <button onClick={sendMessage}>Send</button>
    </div>
  );
}
```

### Vue Example
```vue
<template>
  <div>
    <div v-for="msg in messages" :key="msg.id">
      {{ msg.role }}: {{ msg.content }}
    </div>
    <input v-model="input" @keyup.enter="sendMessage" />
    <button @click="sendMessage">Send</button>
  </div>
</template>

<script>
export default {
  data() {
    return {
      messages: [],
      input: ''
    }
  },
  methods: {
    async sendMessage() {
      const res = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: this.input })
      });
      const data = await res.json();

      this.messages.push(
        { role: 'user', content: this.input },
        { role: 'assistant', content: data.response }
      );
      this.input = '';
    }
  }
}
</script>
```

### Svelte Example
```svelte
<script>
  let messages = [];
  let input = '';

  async function sendMessage() {
    const res = await fetch('http://localhost:8000/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: input })
    });
    const data = await res.json();

    messages = [
      ...messages,
      { role: 'user', content: input },
      { role: 'assistant', content: data.response }
    ];
    input = '';
  }
</script>

{#each messages as msg}
  <div>{msg.role}: {msg.content}</div>
{/each}

<input bind:value={input} on:keyup={(e) => e.key === 'Enter' && sendMessage()} />
<button on:click={sendMessage}>Send</button>
```

---

## Production Considerations

### 1. CORS
Update `api/server.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 2. Authentication
Add JWT or API key middleware

### 3. Rate Limiting
```bash
pip install slowapi
```

### 4. HTTPS
Use nginx or Caddy as reverse proxy

### 5. Docker Compose
```yaml
version: '3.8'
services:
  api:
    build: .
    command: python api/server.py
    ports:
      - "8000:8000"

  frontend:
    image: nginx:alpine
    volumes:
      - ./dist:/usr/share/nginx/html
    ports:
      - "80:80"
```

---

## Mobile Apps

### React Native
Same API calls, use `fetch` or `axios`

### Flutter
```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

Future<String> chat(String message) async {
  final response = await http.post(
    Uri.parse('http://localhost:8000/api/chat'),
    headers: {'Content-Type': 'application/json'},
    body: json.encode({'message': message}),
  );
  return json.decode(response.body)['response'];
}
```

---

## Desktop Apps

### Electron
Wrap your web frontend + bundle API server

### Tauri
Rust-based alternative to Electron

---

Your Jarvis backend is now **API-first** and can connect to any frontend!
