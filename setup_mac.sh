#!/bin/bash
# JRVS Mac Setup Script
# This script installs and configures prerequisites for running JRVS on macOS

set -e

echo "========================================"
echo "   JRVS Mac Setup Script"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_ok() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo "[INFO] $1"
}

# Check if Homebrew is installed
echo "[1/7] Checking Homebrew installation..."
if ! command -v brew &> /dev/null; then
    print_warning "Homebrew is not installed."
    print_info "Homebrew is recommended for managing dependencies on macOS."
    read -p "Would you like to install Homebrew? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add Homebrew to PATH for Apple Silicon Macs
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        print_ok "Homebrew installed successfully"
    else
        print_info "Skipping Homebrew installation. Some features may require manual setup."
    fi
else
    print_ok "Homebrew is installed"
fi
echo ""

# Check Python installation
echo "[2/7] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed."
    if command -v brew &> /dev/null; then
        print_info "Installing Python 3 via Homebrew..."
        brew install python@3.11
        print_ok "Python 3 installed successfully"
    else
        print_info "Please install Python 3.8+ from https://python.org/downloads/"
        exit 1
    fi
else
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    print_ok "Python $PYTHON_VERSION found"
fi
echo ""

# Check pip installation
echo "[3/7] Checking pip installation..."
if ! command -v pip3 &> /dev/null; then
    print_warning "pip is not installed."
    print_info "Installing pip..."
    python3 -m ensurepip --upgrade
else
    print_ok "pip is available"
fi
echo ""

# Check Node.js installation
echo "[4/7] Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    print_warning "Node.js is not installed."
    print_info "Node.js is required for MCP server functionality."
    if command -v brew &> /dev/null; then
        read -p "Would you like to install Node.js via Homebrew? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installing Node.js..."
            brew install node
            print_ok "Node.js installed successfully"
        fi
    else
        print_info "Please install Node.js from https://nodejs.org/"
    fi
else
    NODE_VERSION=$(node --version 2>&1)
    print_ok "Node.js $NODE_VERSION found"
fi
echo ""

# Install Python dependencies
echo "[5/7] Installing Python dependencies..."
if [ ! -f "requirements.txt" ]; then
    print_error "requirements.txt not found!"
    print_info "Make sure you are running this script from the JRVS directory."
    exit 1
fi
print_info "This may take a few minutes..."
if pip3 install -r requirements.txt; then
    print_ok "Python dependencies installed successfully"
else
    print_error "Failed to install Python dependencies."
    print_info "Try running: pip3 install -r requirements.txt manually"
    exit 1
fi
echo ""

# Check for Ollama
echo "[6/7] Checking Ollama installation..."
if ! command -v ollama &> /dev/null; then
    print_warning "Ollama is not installed."
    print_info "Ollama is required to run AI models locally."
    if command -v brew &> /dev/null; then
        read -p "Would you like to install Ollama via Homebrew? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installing Ollama..."
            brew install ollama
            print_ok "Ollama installed successfully"
            print_info "After setup, run: ollama serve"
            print_info "Then pull a model: ollama pull llama3.1"
        fi
    else
        print_info "Please install Ollama from https://ollama.ai/download"
    fi
else
    print_ok "Ollama is installed"
    print_info "Make sure Ollama is running with: ollama serve"
fi
echo ""

# Install npm dependencies (if package.json exists)
echo "[7/7] Installing npm dependencies for frontend..."
if [ -f "package.json" ]; then
    if command -v npm &> /dev/null; then
        if npm install; then
            print_ok "npm dependencies installed successfully"
        else
            print_warning "Failed to install npm dependencies."
        fi
    else
        print_warning "npm is not available. Skipping frontend dependencies."
        print_info "Install Node.js to enable frontend features."
    fi
else
    print_info "No package.json found. Skipping npm dependencies."
fi
echo ""

# Create data directory if it doesn't exist
mkdir -p data
print_ok "Data directory ready"
echo ""

# Make scripts executable (if they exist)
print_info "Making scripts executable..."
for script in start_jrvs.sh start-api.sh setup_mac.sh; do
    if [ -f "$script" ]; then
        chmod +x "$script"
    fi
done
print_ok "Scripts configured"

echo "========================================"
echo "   Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Start Ollama:     ollama serve"
echo "  2. Pull a model:     ollama pull llama3.1"
echo "  3. Run JRVS:         python3 main.py"
echo ""
echo "For the web interface:"
echo "  1. Start API:        python3 api/server.py"
echo "  2. Start frontend:   npm run dev"
echo "  3. Open browser:     http://localhost:3000"
echo ""
echo "See README.md for more information."
echo ""
