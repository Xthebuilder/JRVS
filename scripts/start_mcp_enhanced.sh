#!/bin/bash
# Quick start script for JRVS Enhanced MCP Server

set -e

echo "================================================================"
echo "  JRVS Enhanced MCP Server - Quick Start"
echo "================================================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check Python version
echo -n "Checking Python version... "
PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
if python -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)"; then
    echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION"
else
    echo -e "${RED}✗${NC} Python 3.11+ required, found $PYTHON_VERSION"
    exit 1
fi

# Check if Ollama is running
echo -n "Checking Ollama service... "
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Ollama is running"
else
    echo -e "${YELLOW}⚠${NC} Ollama not detected"
    echo "  Start Ollama with: ollama serve"
    echo "  Then pull a model: ollama pull deepseek-r1:14b"
fi

# Check dependencies
echo -n "Checking dependencies... "
if python -c "import mcp, faiss, sentence_transformers, aiohttp" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} All dependencies installed"
else
    echo -e "${YELLOW}⚠${NC} Missing dependencies"
    echo "  Installing dependencies..."
    pip install -r requirements.txt
fi

# Create required directories
echo -n "Creating directories... "
mkdir -p data logs mcp/tests
echo -e "${GREEN}✓${NC}"

# Create default config if doesn't exist
if [ ! -f "mcp/config.json" ]; then
    echo -n "Creating default configuration... "
    python -c "from mcp.config_manager import create_default_config; create_default_config('mcp/config.json')"
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${GREEN}✓${NC} Configuration exists"
fi

echo ""
echo "================================================================"
echo "  Starting JRVS Enhanced MCP Server"
echo "================================================================"
echo ""
echo "  Config: mcp/config.json"
echo "  Logs:   logs/jrvs-mcp-enhanced.log"
echo ""
echo "  Press Ctrl+C to stop the server"
echo ""
echo "================================================================"
echo ""

# Start the server
python mcp/server_enhanced.py
