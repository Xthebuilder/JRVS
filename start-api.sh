#!/bin/bash
# Start Jarvis API Server

echo "🚀 Starting Jarvis API Server..."
cd "$(dirname "$0")"

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "❌ Ollama is not running!"
    echo "Start it with: ollama serve"
    exit 1
fi

# Install dependencies if needed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing API dependencies..."
    pip install fastapi uvicorn websockets pydantic
fi

# Start the API server
echo "✅ Starting API on http://localhost:8000"
python api/server.py
