#!/bin/bash
# Create JARVIS Custom Ollama Model

echo "🤖 Creating JARVIS Custom Model..."
echo ""

# Check if DeepSeek-R1:14B is available
echo "📥 Checking for DeepSeek-R1:14B..."
if ! ollama list | grep -q "deepseek-r1:14b"; then
    echo "⚠️  DeepSeek-R1:14B not found. Pulling now..."
    echo "   This may take a while (14B model is ~8GB)..."
    ollama pull deepseek-r1:14b
    echo "✅ DeepSeek-R1:14B downloaded!"
else
    echo "✅ DeepSeek-R1:14B found!"
fi

echo ""
echo "🔨 Building JARVIS model from Modelfile..."
cd /home/xmanz/JRVS

ollama create jarvis -f Modelfile.jarvis

if [ $? -eq 0 ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ JARVIS Model Created Successfully!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📋 Model Info:"
    ollama show jarvis
    echo ""
    echo "🚀 To use JARVIS:"
    echo "   Chat:     ollama run jarvis"
    echo "   In JRVS:  Switch to 'jarvis' model in settings"
    echo ""
    echo "💡 Test it now:"
    echo "   ollama run jarvis 'Hello JARVIS, introduce yourself'"
    echo ""
else
    echo "❌ Failed to create JARVIS model"
    exit 1
fi
