# JRVS — Self-Hosted AI Operations Assistant

Your team needs AI for the routine work — inbox triage, research digests, document drafting, calendar summaries. But ChatGPT and Claude.ai are off the table. Legal says no. Compliance says no. Your data policy says no.

**JRVS is a self-hosted AI operations assistant for teams that need Google Workspace automation with a full audit trail — and can't send that data to OpenAI.**

It runs on your servers. Inference happens on your hardware. Nothing leaves your building.

---

## Who It's For

Teams of 10–100 in regulated industries — healthcare, legal, financial services, government contracting — where someone (you) is responsible for keeping AI useful without creating a compliance incident.

You already live in Google Workspace. You have one IT person and Docker. You don't need a six-figure Microsoft Copilot contract. You need an AI that handles the boring-but-sensitive recurring work automatically, keeps a record of what it did, and never touches an external API.

---

## What Makes JRVS Different

### 1. Nothing leaves your server
JRVS connects to local model backends — Ollama or LM Studio — so inference runs on your hardware. No OpenAI API key. No telemetry. The compliance story is one sentence: the data never left.

### 2. Autonomous agents with approval tiers
JRVS runs scheduled tasks in the background — morning inbox digest, urgent email watch, weekly research brief — without you being at the keyboard. Each task has a trust tier you configure:

- **auto** — executes silently (low-risk reads and summaries)
- **notify** — executes and reports back via Slack or terminal
- **confirm** — drafts the output and waits for your approval before acting

Nothing sends an email or modifies a document without the tier you set allowing it.

### 3. Google Workspace integration with a structured audit log
Every write action JRVS takes — sending an email, creating a Doc, updating a Sheet — is logged twice: once before execution (intent) and once after (result), with timestamps and session IDs, in a rotating JSON log on your server. Your compliance team can read and export it.

---

## What It Can Do Today

| Category | Capability |
|----------|-----------|
| **Scheduled Agents** | Morning digest, urgent email watch, weekly research brief, end-of-day summary — runs on your schedule |
| **Google Workspace** | Read/write Gmail, Drive, Docs, Sheets — with full audit trail on every write |
| **Audit Logging** | JSON intent+result log for all write actions, rotating file, exportable |
| **Local Inference** | Ollama, LM Studio — switchable at runtime, no cloud dependency |
| **RAG Pipeline** | FAISS + BGE embeddings + cross-encoder reranking + MMR diversity |
| **Memory** | SQLite persistent memory, cross-session retrieval |
| **Web Search** | Brave Search API with auto-ingest into knowledge base |
| **File Uploads** | Drop files in `uploads/` and ingest into knowledge base |
| **MCP** | Full MCP client + server (17+ tools) |
| **API Server** | FastAPI server with bearer-token auth for programmatic access |
| **Vision Extension** | Camera capture, LLaVA/Moondream inference, anomaly detection |
| **Audio Extension** | Wake word → Whisper STT → JRVS → Piper/Kokoro TTS |

---

## Licensing

| | Community | Professional | Team |
|---|---|---|---|
| Self-hosted | Yes | Yes | Yes |
| Commercial use | No | Yes | Yes |
| Email support | No | Yes | Yes |
| Monthly 1-on-1 with creator | No | No | Yes |
| Custom goal configuration | No | No | Yes |
| **Price** | Free | $149 one-time | $499/mo |

> SSO/SAML and multi-user team management are on the roadmap. [See ENTERPRISE.md](./ENTERPRISE.md) for details.

[Full pricing details and FAQ →](./PRICING.md)

Community use is free under [CC BY-NC 4.0](LICENSE). Commercial use requires a Professional or Team license.

---

## Quick Start

### Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| Python 3.8+ | Yes | Runtime |
| Ollama **or** LM Studio | Yes | LLM backend |
| Node.js | Optional | MCP servers, web UI |

### Install

```bash
# 1. Clone the repo
git clone https://github.com/Xthebuilder/JRVS_Private.git
cd JRVS_Private

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Pull a model (Ollama)
ollama pull gemma3:12b

# 5. Run JRVS
python main.py
```

### Automated Setup Scripts

- **macOS**: `chmod +x setup_mac.sh && ./setup_mac.sh`
- **Windows**: `setup_windows.bat`

---

## Platform Setup

<details>
<summary><strong>Windows</strong></summary>

1. Install [Python 3.8+](https://python.org/downloads/) — check **"Add Python to PATH"**
2. Install [Ollama](https://ollama.ai/download) or [LM Studio](https://lmstudio.ai)
3. Install [Node.js LTS](https://nodejs.org/) (optional, for MCP and web UI)

```cmd
pip install -r requirements.txt
ollama serve
ollama pull gemma3:12b
python main.py
```

**Tips:**
- Use a virtual environment to avoid dependency conflicts:
  ```cmd
  python -m venv venv
  venv\Scripts\activate
  pip install -r requirements.txt
  ```
- If `torch` install fails: install [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
- If FAISS fails: `pip install faiss-cpu --no-cache-dir`

</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
# Install Homebrew if needed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.11 ollama node
pip3 install -r requirements.txt
ollama serve
ollama pull gemma3:12b
python3 main.py
```

**Tips:**
- Apple Silicon (M1/M2/M3): all dependencies support ARM natively
- If `python` is not found, use `python3`
- If SSL errors: `/Applications/Python\ 3.11/Install\ Certificates.command`
- Add Homebrew to PATH (Apple Silicon): `eval "$(/opt/homebrew/bin/brew shellenv)"`

</details>

<details>
<summary><strong>Linux</strong></summary>

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
ollama serve &
ollama pull gemma3:12b
python main.py
```

</details>

---

## Usage

### Starting JRVS

```bash
python main.py                          # Default (Ollama)
python main.py --use-lmstudio           # Use LM Studio
python main.py --theme cyberpunk        # Set theme
python main.py --model gemma3:12b       # Set model (default)
python main.py --debug                  # Debug mode
```

All options: `python main.py --help`

### CLI Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/models` | List available models |
| `/switch <model>` | Switch active model |
| **Knowledge Base** | |
| `/scrape <url>` | Scrape a URL into the knowledge base |
| `/search <query>` | Search stored documents |
| `/websearch <query>` | Search via Brave API and auto-ingest results |
| `/upload list` | List files in the `uploads/` folder |
| `/upload ingest <file>` | Ingest a specific file into the knowledge base |
| `/upload ingest-all` | Ingest all files in `uploads/` |
| `/upload read <file>` | Read a file from `uploads/` |
| **Brave Search** | |
| `/brave-key <key>` | Set Brave API key at runtime |
| `/brave-status` | Show Brave config and request usage |
| **Calendar** | |
| `/calendar` | Show upcoming events (7 days) |
| `/today` | Show today's events |
| `/month [month] [year]` | Show ASCII calendar |
| **MCP** | |
| `/mcp-servers` | List connected MCP servers |
| `/mcp-tools [server]` | List available MCP tools |
| **Google Workspace** | |
| `/google-auth` | Authenticate with Google (OAuth2 flow) |
| `/google-status` | Show connection + sync stats |
| `/google-sync` | Manually trigger Gmail + Drive sync |
| `/gmail search <query>` | Search Gmail and ingest results |
| `/gmail send <to> <subj> <body>` | Send email (audit-logged) |
| `/gdocs read <title\|id>` | Ingest a Google Doc |
| `/gdocs create <title> <content>` | Create a Google Doc |
| `/gsheets read <id> [range]` | Read a Google Sheet |
| `/gsheets update <id> <range> <val>` | Update Sheet cells |
| **Autonomous Goals** | |
| `/agent goals` | List goals from `goals.yaml` |
| `/agent run <id>` | Run a specific goal immediately |
| `/agent run --schedule <s>` | Run all goals for a schedule |
| `/agent start` | Start the background goal scheduler |
| `/agent status` | Show scheduler state and last-run times |
| **System** | |
| `/stats` | Show system statistics |
| `/history` | Show conversation history |
| `/theme <name>` | Change theme (`matrix`, `cyberpunk`, `minimal`) |
| `/clear` | Clear screen |
| `/exit` | Exit JRVS |

---

## Google Workspace Setup

JRVS can read Gmail, Google Drive, Google Docs, and Google Sheets, and write Docs/Sheets/emails with a full audit log.

**1. Create OAuth2 credentials**

- Go to [console.cloud.google.com](https://console.cloud.google.com)
- Create a project → Enable Gmail API, Drive API, Docs API, Sheets API
- OAuth 2.0 credentials → Desktop app → Download as JSON
- Copy the `client_id` and `client_secret` values

**2. Add to your `.env`**

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

**3. Authenticate inside JRVS**

```
/google-auth
```

Visit the URL printed, grant access, paste the code back. JRVS then starts a background sync that ingests new emails and Drive files into the knowledge base every 15 minutes (configurable with `GOOGLE_SYNC_INTERVAL_MINUTES`).

**4. Use it**

```
/google-status          check connection and sync stats
/gmail search invoice   search Gmail and ingest matches
/gdocs create "Notes" "First draft"
/agent goals            see Gmail-powered autonomous goals
/agent start            run goals on schedule automatically
```

---

## Extensions

JRVS ships with two standalone extension modules under `extensions/`. They hook into JRVS memory and events without modifying any core files. Both run entirely locally.

### Vision Extension

Connects to any camera — built-in webcam, USB camera, DroidCam over WiFi, or any RTSP/HTTP stream. Captures frames intelligently (only processes frames when motion is detected or on a periodic interval), runs local visual inference, logs observations into JRVS memory, and surfaces anomaly alerts when something unusual is detected.

**Quick start:**

```bash
# Install vision dependencies
pip install -r extensions/vision/requirements.txt

# For LLaVA inference: pull the model into Ollama (already running for JRVS)
ollama pull llava:7b

# Describe what the camera sees right now
python -m extensions.vision.vision_module --describe-once

# Run the full background loop
python -m extensions.vision.vision_module --run
```

**Source options:**

| Source | Config value |
|--------|-------------|
| USB / built-in webcam | `0`, `1`, `2` |
| DroidCam over WiFi | `"http://192.168.1.X:4747/video"` |
| RTSP network camera | `"rtsp://user:pass@IP/stream"` |
| Desktop screen (primary) | `"screen"` |
| Specific monitor | `"screen:2"` |
| Cropped screen region | `"screen:1:0,0,1280,720"` |

Set in `extensions/vision/config.yaml`:
```yaml
camera:
  source: "screen"             # or "http://192.168.1.X:4747/video" for DroidCam
```

**Use from JRVS orchestration code:**
```python
from extensions.vision import VisionModule

vision = VisionModule()
await vision.initialize()
await vision.start()                            # background loop

description = await vision.describe_frame()     # on-demand snapshot
alerts = await vision.get_alerts()             # anomalies for JRVS to reason about
```

Once running, ask JRVS naturally:
```
jarvis❯ What did you see in the last hour?
jarvis❯ Was there any unusual activity at 2am?
```
Vision observations are embedded and stored in JRVS's FAISS index so they show up in normal RAG retrieval.

**Config:** `extensions/vision/config.yaml`

| Key | Default | Description |
|-----|---------|-------------|
| `camera.source` | `0` | `0`=webcam, URL=DroidCam/RTSP |
| `inference.backend` | `"llava"` | `"llava"` or `"moondream"` |
| `inference.llava.model` | `"llava:7b"` | Ollama model name |
| `camera.motion_threshold` | `0.05` | Fraction of pixels changed to trigger inference |
| `camera.periodic_interval` | `30` | Always infer at least every N seconds |
| `anomaly.alert_threshold` | `0.85` | Score above which an alert is raised |
| `memory.log_level` | `"scene"` | `"all"` / `"scene"` / `"anomaly"` |

---

### Audio Extension

Full conversational voice I/O. Listens for a wake word ("hey jarvis"), records your speech, transcribes with Whisper, sends the text to JRVS, and speaks the response back using Piper or Kokoro TTS. Everything runs locally.

**Install dependencies:**

```bash
pip install -r extensions/audio/requirements.txt

# Piper binary (Linux x86_64 example)
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
tar -xzf piper_linux_x86_64.tar.gz
sudo mv piper/piper /usr/local/bin/

# Download a voice model
mkdir -p ~/.local/share/piper-voices
wget -P ~/.local/share/piper-voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget -P ~/.local/share/piper-voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

**Smoke tests:**

```bash
# Test TTS — hear JRVS speak
python -m extensions.audio.audio_module --say "Hello, I am JRVS."

# Test STT — speak and see transcription
python -m extensions.audio.audio_module --listen-once

# Run full wake-word conversation loop
python -m extensions.audio.audio_module --run
```

**Use from JRVS orchestration code:**
```python
from extensions.audio import AudioModule
import aiohttp

audio = AudioModule()
await audio.initialize()

async def jrvs_respond(user_text: str) -> str:
    async with aiohttp.ClientSession() as s:
        resp = await s.post(
            "http://localhost:8010/api/chat",
            json={"message": user_text, "session_id": "voice"}
        )
        data = await resp.json()
        return data["response"]

await audio.start_loop(jrvs_respond)   # say "hey jarvis" to begin
```

**Config:** `extensions/audio/config.yaml`

| Key | Default | Description |
|-----|---------|-------------|
| `input.device` | `null` | `null`=system default, or device name/index |
| `stt.model` | `"base"` | Whisper size: `tiny` / `base` / `small` / `medium` / `large-v3` |
| `tts.backend` | `"piper"` | `"piper"` or `"kokoro"` |
| `tts.piper.model` | `"en_US-lessac-medium"` | Voice model name |
| `conversation.wake_word` | `"hey jarvis"` | Trigger phrase (null = always-on) |
| `input.vad_aggressiveness` | `2` | VAD strictness 0–3 |
| `input.silence_timeout` | `1.5` | Seconds of silence to end utterance |

See [docs/EXTENSIONS.md](docs/EXTENSIONS.md) for full documentation on both modules.

---

## How It Works

### RAG Pipeline

```
User query
    │
    ▼
Hybrid Search ──── FAISS (semantic) + FTS5 (keyword) ──── RRF fusion
    │
    ▼
Cross-Encoder Reranker (ms-marco-MiniLM-L-6-v2)
    │
    ▼
MMR Diversity Filter
    │
    ▼
Context injected into LLM prompt → Response
```

1. **Ingestion**: URLs/files/vision observations → chunked → BGE embeddings → FAISS + FTS5
2. **Retrieval**: hybrid FAISS + keyword search → reranked → diverse context
3. **Memory**: every conversation turn is embedded and stored for cross-session recall

### Brave Search Integration

```bash
# Set your API key (one time)
export BRAVE_API_KEY="your_key_here"

# Or set at runtime
/brave-key your_key_here

# Search and auto-ingest results
/websearch what is FAISS used for
```

Results are automatically scraped (full page, not just snippets) and added to your knowledge base.

### File Uploads

Drop any text-based file into the `uploads/` folder:

```bash
cp my_notes.txt /path/to/JRVS/uploads/
```

Then ingest it:

```
jarvis❯ /upload ingest-all
```

Supports 30+ extensions: `.txt`, `.md`, `.py`, `.js`, `.json`, `.csv`, `.yaml`, `.pdf`, and more.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_DEFAULT_MODEL` | `deepseek-r1:14b` | Default Ollama model |
| `LMSTUDIO_BASE_URL` | `http://127.0.0.1:1234/v1` | LM Studio server URL |
| `LMSTUDIO_DEFAULT_MODEL` | *(auto-detect)* | LM Studio model |
| `BRAVE_API_KEY` | — | Brave Search API key |
| `BRAVE_MAX_REQUESTS_PER_SESSION` | `20` | Request budget per session |
| `BRAVE_SEARCH_RESULTS_PER_QUERY` | `5` | Results per search |
| `BRAVE_AUTO_SCRAPE` | `true` | Scrape full pages vs snippets only |
| `EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | Sentence-transformer model |
| `SIMILARITY_THRESHOLD` | `0.35` | Min cosine similarity for retrieval |
| `MAX_CONTEXT_LENGTH` | `12000` | Max chars of context injected |
| `CONVERSATION_HISTORY_TURNS` | `8` | In-session turns sent to LLM |
| **Vision Extension** | | |
| `JRVS_VISION_CAMERA_SOURCE` | `0` | Camera source override |
| `JRVS_VISION_INFERENCE_BACKEND` | `llava` | `llava` or `moondream` |
| `JRVS_VISION_ENABLED` | `true` | Enable/disable vision module |
| **Audio Extension** | | |
| `JRVS_AUDIO_INPUT_DEVICE` | system default | Microphone device name or index |
| `JRVS_AUDIO_STT_MODEL` | `base` | Whisper model size |
| `JRVS_AUDIO_TTS_BACKEND` | `piper` | `piper` or `kokoro` |
| `JRVS_AUDIO_CONVERSATION_WAKE_WORD` | `hey jarvis` | Wake phrase |

All variables can be set in your shell or a `.env` file.

**Example — remote Ollama + DroidCam:**
```bash
export OLLAMA_BASE_URL="http://192.168.1.100:11434"
export JRVS_VISION_CAMERA_SOURCE="http://192.168.1.50:4747/video"
python main.py
```

---

## MCP Integration

### MCP Client (connect JRVS to external tools)

Configure servers in `mcp_gateway/client_config.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
  }
}
```

JRVS auto-connects on startup. Use `/mcp-servers` and `/mcp-tools` to inspect.

**Available MCP servers:** filesystem, github, postgres, brave-search, memory, slack, and more.

### MCP Server (expose JRVS to Claude or other agents)

```bash
python mcp_gateway/server.py
```

17 tools exposed: RAG search, web scraping, calendar, model switching, and more.

See [docs/MCP_SETUP.md](docs/MCP_SETUP.md) for full configuration.

---

## UTCP Support

JRVS implements [UTCP](https://github.com/universal-tool-calling-protocol) — a lightweight protocol for AI agents to discover and call tools directly via their native protocols (HTTP, WebSocket, CLI).

```bash
# Start the API server
python api/server.py

# Discover available tools
curl http://localhost:8010/utcp

# Call a tool directly
curl -X POST http://localhost:8010/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello JRVS!"}'
```

| | UTCP | MCP |
|--|------|-----|
| Architecture | Direct API calls | Wrapper servers |
| Overhead | Zero | Proxy latency |
| Best for | REST APIs | Stdio tools, complex workflows |

See [docs/UTCP_GUIDE.md](docs/UTCP_GUIDE.md) for details.

---

## Project Structure

```
JRVS/
├── main.py                  # Entry point
├── config.py                # All configuration (env vars)
├── requirements.txt
│
├── extensions/              # Plug-and-play extension modules
│   ├── base.py              # BaseExtension ABC
│   ├── vision/              # Vision extension (camera + inference + anomaly)
│   │   ├── vision_module.py # PUBLIC: VisionModule class
│   │   ├── config.yaml      # User config (camera source, model, thresholds)
│   │   ├── camera/          # CameraManager (USB/DroidCam/RTSP), FrameProcessor
│   │   ├── inference/       # LLaVABackend (Ollama), MoondreamBackend (local)
│   │   ├── memory/          # VisionLogger (→ JRVS FAISS), AnomalyDetector
│   │   └── alerts/          # AlertManager (→ JRVS events table)
│   └── audio/               # Audio extension (STT + TTS + wake word)
│       ├── audio_module.py  # PUBLIC: AudioModule class
│       ├── config.yaml      # User config (mic, model, voice, wake word)
│       ├── input/           # MicrophoneCapture, VoiceActivityDetector, WhisperBackend
│       └── output/          # PiperBackend, KokoroBackend, AudioPlayer
│
├── rag/
│   ├── embeddings.py        # BGE-base-en-v1.5 embeddings (768-dim)
│   ├── vector_store.py      # FAISS index (HNSW auto-upgrade at 200k vectors)
│   ├── retriever.py         # Hybrid search + MMR pipeline
│   └── reranker.py          # Cross-encoder reranker
│
├── core/
│   ├── database.py          # SQLite (aiosqlite) + FTS5
│   ├── file_handler.py      # File upload ingestion
│   └── calendar.py          # Calendar events (also used by vision alerts)
│
├── llm/
│   ├── ollama_client.py     # Ollama /api/chat integration
│   └── lmstudio_client.py   # LM Studio integration
│
├── cli/
│   ├── interface.py         # JarvisCLI main loop
│   ├── commands.py          # Command routing
│   └── themes.py            # Matrix / Cyberpunk / Minimal themes
│
├── scraper/
│   ├── web_scraper.py       # BeautifulSoup scraper
│   └── brave_search.py      # Brave Search API client
│
├── api/
│   └── server.py            # FastAPI server + UTCP endpoint
│
├── mcp_gateway/
│   ├── server.py            # MCP server (17 tools)
│   ├── client.py            # MCP client
│   └── client_config.json   # MCP server configuration
│
└── uploads/                 # Drop files here for ingestion
```

---

## API Integration

```python
from rag.retriever import rag_retriever
from llm.ollama_client import ollama_client

# Add a document to the knowledge base
doc_id = await rag_retriever.add_document(content, title, url)

# Retrieve relevant context
context = await rag_retriever.retrieve_context(query)

# Generate a response
response = await ollama_client.generate(query, context=context)
```

---

## Troubleshooting

**"Cannot connect to Ollama"**
```bash
ollama serve          # Start Ollama
ollama list           # Verify models are installed
ollama pull gemma3:12b  # Pull a model if list is empty
```
Or switch to LM Studio: `python main.py --use-lmstudio`

**"Cannot connect to LM Studio"**
- Open LM Studio → enable the local server → load a model

**Import errors / missing packages**
```bash
pip install -r requirements.txt
python --version   # Must be 3.8+
```

**Performance issues**
- Use a smaller model: `ollama pull phi3:mini` (for low-RAM devices, or set `JRVS_DEVICE_CLASS=sbc`)
- Reduce `MAX_CONTEXT_LENGTH` in `config.py`
- Clear the vector cache: `rm data/faiss_index.*`

**FAISS dimension mismatch after upgrading**
JRVS auto-detects and rebuilds the index if the embedding model changed. Old `.map` files are auto-migrated to SQLite.

**MCP servers not connecting**
- Install Node.js: `node --version` and `npm --version`
- Check paths in `mcp_gateway/client_config.json`

**Vision: "LLaVA model not found"**
```bash
ollama pull llava:7b
```

**Vision: camera not opening**
- Check device index: `python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"`
- For DroidCam: verify phone and PC are on the same WiFi, open the DroidCam app first

**Audio: no sound / mic not detected**
```bash
# List available audio devices
python -c "from extensions.audio.input.microphone import MicrophoneCapture; MicrophoneCapture.list_devices()"
```
Set the device name or index in `extensions/audio/config.yaml`.

**Audio: Piper binary not found**
- Download from [github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases) and put `piper` on your PATH
- Or set the full path in `extensions/audio/config.yaml` under `tts.piper.binary`

---

## Contributing

Contributions are welcome, especially:
- New extension modules (vision sources, STT/TTS backends)
- Tool protocol extensions (MCP/UTCP)
- Performance improvements to the RAG pipeline
- Documentation and design feedback

Please open an issue before large changes to align on direction.

---

## License

[Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](LICENSE)

Free to use, modify, and share for personal and non-commercial purposes. You must give credit. You may not use this project or derivatives of it for commercial purposes. Respect website terms of service when scraping.

## Acknowledgments

[Ollama](https://ollama.ai) · [FAISS](https://github.com/facebookresearch/faiss) · [BGE Embeddings](https://huggingface.co/BAAI/bge-base-en-v1.5) · [Sentence Transformers](https://sbert.net) · [Rich](https://github.com/Textualize/rich) · [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) · [Brave Search](https://brave.com/search/api/) · [LLaVA](https://llava-vl.github.io) · [Moondream](https://github.com/vikhyat/moondream) · [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [Piper TTS](https://github.com/rhasspy/piper) · [Kokoro TTS](https://github.com/hexgrad/kokoro) · [openwakeword](https://github.com/dscripka/openWakeWord)
