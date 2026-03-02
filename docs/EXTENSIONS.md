# JRVS Extensions

Extensions are standalone modules that attach to JRVS without modifying core code. They write directly into JRVS's SQLite database and FAISS vector store, so everything JRVS knows how to retrieve — past observations, anomaly alerts, voice transcripts — surfaces naturally in conversation.

---

## Architecture

```
extensions/
├── base.py              # BaseExtension ABC (initialize / stop / is_running / status)
├── vision/              # Camera → inference → memory → alerts
└── audio/               # Microphone → STT → JRVS → TTS → speaker
```

**Integration points (zero core modifications):**

| JRVS component | How extensions use it |
|---|---|
| `core/database.py` `db` | Write observations as documents (SQLite `documents` table) |
| `rag/vector_store.py` `vector_store` | Add embeddings to FAISS for RAG retrieval |
| `core/calendar.py` `calendar` | Write anomaly alerts to the events table |
| `OLLAMA_BASE_URL` env var | LLaVA inference reuses the same Ollama instance |

Extensions locate the JRVS root automatically via `Path(__file__).parent` traversal. You can override with `JRVS_ROOT=/path/to/jrvs`.

---

## Vision Extension

### What it does

1. Opens a camera (USB, DroidCam WiFi, RTSP, or HTTP MJPEG)
2. Uses MOG2 background subtraction to detect motion — only runs inference when something changes or on a periodic timer
3. Sends the frame to LLaVA (via Ollama) or Moondream (local HuggingFace) for a natural-language description
4. Logs the description into JRVS memory (SQLite + FAISS) with timestamp and metadata
5. Tracks a rolling embedding baseline and flags anomalies — scene shifts, objects at unusual hours, sudden changes
6. Pushes high-severity anomalies to the JRVS events table so they appear in `/calendar` and RAG context

### Install

```bash
pip install -r extensions/vision/requirements.txt

# LLaVA backend (recommended — reuses your existing Ollama)
ollama pull llava:7b

# Moondream backend (alternative — downloads ~1.9GB from HuggingFace on first run)
# No extra install needed; transformers is already in JRVS requirements.txt
```

### Camera sources

| Source | Config value | Notes |
|--------|-------------|-------|
| Built-in / USB webcam | `0`, `1`, `2` | Device index |
| DroidCam over WiFi | `"http://192.168.1.X:4747/video"` | Open DroidCam app first |
| Any HTTP MJPEG stream | `"http://IP:port/video"` | |
| RTSP network camera | `"rtsp://user:pass@IP/stream"` | |

Set in `extensions/vision/config.yaml`:
```yaml
camera:
  source: "http://192.168.1.50:4747/video"
```
Or via environment variable:
```bash
export JRVS_VISION_CAMERA_SOURCE="http://192.168.1.50:4747/video"
```

### Inference backends

**LLaVA (default)** — runs through your existing Ollama instance, same endpoint JRVS uses for text. Requires `ollama pull llava:7b` (or `llava:13b` for better accuracy).

**Moondream** — compact 1.9B vision-language model loaded locally via HuggingFace `transformers`. Downloads automatically on first use. Faster on CPU than LLaVA for short descriptions.

Switch backends in config:
```yaml
inference:
  backend: "moondream"   # or "llava"
```

### Smoke tests

```bash
# Capture one frame, describe it, exit
python -m extensions.vision.vision_module --describe-once

# Run the full background loop (Ctrl-C to stop)
python -m extensions.vision.vision_module --run
```

### Public API

```python
from extensions.vision import VisionModule

vision = VisionModule()
await vision.initialize()

# Start background capture loop
await vision.start()

# On-demand description of the current frame
desc = await vision.describe_frame()

# Consume pending anomaly alerts
alerts = await vision.get_alerts()
for alert in alerts:
    print(f"[{alert.severity.upper()}] {alert.title}")
    # alert.anomaly.score, .reason, .timestamp available

# Status snapshot
print(vision.status())
# {running, camera_source, frames_processed, alerts_pending, last_description, …}

await vision.stop()
```

### Anomaly detection

The `AnomalyDetector` maintains two signals:

**Embedding drift** — keeps a rolling window of the last N observation embeddings (default 100). Computes the mean as a "scene baseline". Cosine distance from the current embedding to the baseline above `similarity_threshold` (0.70) = anomaly.

**Hour-of-day frequency** — tracks which objects/scenes appear at each hour of the day. Something appearing at 3am that normally only appears at 2pm scores higher.

Combined score above `alert_threshold` (0.85) → alert written to JRVS events table.

### Asking JRVS about what it saw

Once the vision loop is running, observations land in JRVS's FAISS index with `content_type: vision_observation`. Ask naturally:

```
jarvis❯ What did you see in the living room this morning?
jarvis❯ Has anyone been at my desk today?
jarvis❯ Were there any alerts while I was away?
```

### Full config reference

`extensions/vision/config.yaml`:

```yaml
enabled: true

camera:
  source: 0                    # int=device index, string=URL
  fps_capture: 2               # capture attempts per second
  motion_threshold: 0.05       # 0–1 fraction of pixels changed to trigger inference
  periodic_interval: 30        # always infer at least every N seconds
  max_width: 512               # resize frames before inference (speed)

inference:
  backend: "llava"             # "llava" | "moondream"
  llava:
    model: "llava:7b"
    ollama_url: "http://localhost:11434"
    timeout: 60
  moondream:
    model_id: "vikhyatk/moondream2"
    revision: "2025-01-09"
    model_path: null            # null = HuggingFace default cache
  prompt: >
    Briefly describe what you see in this image.
    Focus on: people present, objects, activities, and the general scene.
    Be concise (1–3 sentences).

memory:
  db_path: null                # null = auto-detect JRVS database
  log_level: "scene"           # "all" | "scene" | "anomaly"

anomaly:
  enabled: true
  window_size: 100             # rolling baseline over last N observations
  similarity_threshold: 0.70   # cosine distance above this = anomaly
  alert_threshold: 0.85        # anomaly score above this = alert written to events

alerts:
  queue_size: 50
  write_to_jrvs_events: true
  min_severity: "medium"       # "low" | "medium" | "high"
```

Environment variable overrides use the prefix `JRVS_VISION_`:
```bash
JRVS_VISION_CAMERA_SOURCE=0
JRVS_VISION_INFERENCE_BACKEND=moondream
JRVS_VISION_ANOMALY_ALERT_THRESHOLD=0.9
JRVS_VISION_ENABLED=false
```

---

## Audio Extension

### What it does

1. Passively listens for the wake word ("hey jarvis") via openwakeword — runs on 80ms audio windows, negligible CPU
2. Plays a brief acknowledgment tone when triggered
3. Records your utterance until silence is detected (webrtcvad)
4. Transcribes with faster-whisper locally (int8 quantized, no internet)
5. Calls your JRVS response function (typically `POST /api/chat`)
6. Speaks the response back using Piper TTS (subprocess) or Kokoro (local model)

### Install

```bash
pip install -r extensions/audio/requirements.txt
```

**Piper binary** (required for default TTS):
```bash
# Linux x86_64
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
tar -xzf piper_linux_x86_64.tar.gz
sudo mv piper/piper /usr/local/bin/

# Download a voice model
mkdir -p ~/.local/share/piper-voices
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
wget -P ~/.local/share/piper-voices $BASE/en_US-lessac-medium.onnx
wget -P ~/.local/share/piper-voices $BASE/en_US-lessac-medium.onnx.json
```

**Kokoro TTS** (alternative, higher quality):
```bash
pip install kokoro soundfile
# Model downloads automatically from HuggingFace (~330MB) on first use
```

### Smoke tests

```bash
# Hear JRVS speak
python -m extensions.audio.audio_module --say "Hello, I am JRVS."

# Speak and see your words transcribed
python -m extensions.audio.audio_module --listen-once

# Full wake-word loop (say "hey jarvis" to start each turn)
python -m extensions.audio.audio_module --run
```

### Public API

```python
from extensions.audio import AudioModule

audio = AudioModule()
await audio.initialize()

# One-shot transcription (blocks until utterance complete)
text = await audio.listen(timeout=10.0)   # None = wait forever

# One-shot TTS
await audio.speak("I found three items in your calendar today.")

# Full conversational loop
async def jrvs_respond(user_text: str) -> str:
    # plug in your JRVS API call here
    async with aiohttp.ClientSession() as s:
        r = await s.post("http://localhost:8000/api/chat",
                         json={"message": user_text, "session_id": "voice"})
        return (await r.json())["response"]

await audio.start_loop(jrvs_respond)  # non-blocking; runs as background task

# Status snapshot
print(audio.status())
# {running, mic_device, stt_model, tts_engine, wake_word, conversation_count, …}

await audio.stop()
```

### Wake word

The default wake phrase is **"hey jarvis"** using a pre-trained openwakeword model. The model runs locally with no internet connection required.

Other built-in phrases supported by openwakeword:
- `"hey mycroft"`
- `"alexa"`
- `"hey siri"`

Change in config:
```yaml
conversation:
  wake_word: "hey jarvis"
```

Set to `null` for always-on mode (no wake phrase needed — every utterance after silence is transcribed):
```yaml
conversation:
  wake_word: null
```

### STT models (Whisper sizes)

| Model | Size | Speed (CPU) | Accuracy | Recommended for |
|-------|------|------------|----------|----------------|
| `tiny` | 39M | Very fast | Lower | Fast machines, casual use |
| `base` | 74M | Fast | Good | **Default — good balance** |
| `small` | 244M | Moderate | Better | Quieter environments |
| `medium` | 769M | Slow | High | High accuracy requirement |
| `large-v3` | 1.5B | Very slow | Highest | GPU only |

### TTS options

**Piper** (default) — Rust binary, ~50ms latency, natural-sounding voices. Dozens of languages and voices. See [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) for the full list.

**Kokoro** — Pure Python, ~330MB model, streams audio in sentence chunks for a natural feel. Slightly slower first-sentence latency but higher quality prosody. Requires `pip install kokoro soundfile`.

### Microphone setup

List available input devices:
```bash
python -c "from extensions.audio.input.microphone import MicrophoneCapture; MicrophoneCapture.list_devices()"
```

Set in config by name substring or index:
```yaml
input:
  device: "USB Microphone"    # matched by substring
  # device: 2                 # or by index
  # device: null              # system default
```

### Full config reference

`extensions/audio/config.yaml`:

```yaml
enabled: true

input:
  device: null           # null=system default, string=name match, int=index
  sample_rate: 16000
  channels: 1
  chunk_ms: 30           # VAD frame size: 10 / 20 / 30 ms
  vad_aggressiveness: 2  # 0 (permissive) – 3 (strict)
  silence_timeout: 1.5   # seconds of silence to end utterance
  max_duration: 30       # max utterance length in seconds

stt:
  backend: "whisper"
  model: "base"          # tiny | base | small | medium | large-v3
  language: "en"         # ISO 639-1, or null for auto-detect
  device: "cpu"          # "cpu" or "cuda"
  compute_type: "int8"   # int8 (CPU) | float16 (GPU)

tts:
  backend: "piper"       # "piper" | "kokoro"
  piper:
    model: "en_US-lessac-medium"
    models_dir: "~/.local/share/piper-voices"
    binary: "piper"
    output_sample_rate: 22050
  kokoro:
    model_path: null     # null = auto download
    voice: "af_sky"
    lang_code: "a"       # "a" = American English
  speed: 1.0

conversation:
  wake_word: "hey jarvis"    # null = always-on VAD
  wake_word_threshold: 0.5   # openwakeword confidence 0–1
  ack_tone: true             # play beep after wake word
  response_prefix: ""        # optional string JRVS prepends to each reply
```

Environment variable overrides use the prefix `JRVS_AUDIO_`:
```bash
JRVS_AUDIO_STT_MODEL=small
JRVS_AUDIO_TTS_BACKEND=kokoro
JRVS_AUDIO_INPUT_DEVICE="USB Microphone"
JRVS_AUDIO_CONVERSATION_WAKE_WORD="hey jarvis"
```

---

## Troubleshooting

### Vision

| Problem | Fix |
|---------|-----|
| `LLaVA model not found` | `ollama pull llava:7b` |
| Camera won't open | Check index with `python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"` |
| DroidCam not connecting | Ensure phone and PC are on the same WiFi; open DroidCam app before starting |
| Moondream slow on first run | Downloading ~1.9GB model; subsequent runs use cache |
| No anomalies detected | Lower `anomaly.similarity_threshold` in config (try `0.5`) |
| Alerts not in `/calendar` | Set `alerts.write_to_jrvs_events: true` and ensure JRVS DB is initialized |

### Audio

| Problem | Fix |
|---------|-----|
| `Piper binary not found` | Download from github.com/rhasspy/piper/releases; add to PATH |
| No voice model found | Download `.onnx` + `.onnx.json` to `~/.local/share/piper-voices` |
| Mic not detected | Run `MicrophoneCapture.list_devices()` and set device name in config |
| Wake word never triggers | Lower `wake_word_threshold` (try `0.3`); check mic is picking up audio |
| Whisper transcribes wrong language | Set `stt.language` to your ISO 639-1 code, or `null` for auto |
| High CPU during STT | Use `model: "tiny"` or set `device: "cuda"` if GPU available |
| No audio output | Check system audio output device; `sounddevice` uses the system default |
