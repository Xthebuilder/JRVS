@echo off
REM JRVS Windows Setup Script
REM This script installs and configures prerequisites for running JRVS on Windows

echo ========================================
echo    JRVS Windows Setup Script
echo ========================================
echo.

REM Check for Administrator privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [WARNING] Not running as Administrator. Some installations may require elevated privileges.
    echo [INFO] Right-click this script and select "Run as administrator" if you encounter issues.
    echo.
)

REM Check Python installation
echo [1/6] Checking Python installation...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo [INFO] Please install Python 3.8+ from https://python.org/downloads/
    echo [INFO] Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
) else (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION_STR=%%i
    echo [OK] %PYTHON_VERSION_STR% found
)
echo.

REM Check pip installation
echo [2/6] Checking pip installation...
pip --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] pip is not installed.
    echo [INFO] Installing pip...
    python -m ensurepip --upgrade
) else (
    echo [OK] pip is available
)
echo.

REM Check Node.js installation (required for MCP servers)
echo [3/6] Checking Node.js installation...
node --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [WARNING] Node.js is not installed.
    echo [INFO] Node.js is required for MCP server functionality.
    echo [INFO] Please install Node.js from https://nodejs.org/
    echo.
) else (
    for /f "tokens=*" %%i in ('node --version 2^>^&1') do set NODE_VERSION=%%i
    echo [OK] Node.js %NODE_VERSION% found
)
echo.

REM Install Python dependencies
echo [4/6] Installing Python dependencies...
if not exist requirements.txt (
    echo [ERROR] requirements.txt not found!
    echo [INFO] Make sure you are running this script from the JRVS directory.
    pause
    exit /b 1
)
echo [INFO] This may take a few minutes...
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install Python dependencies.
    echo [INFO] Try running: pip install -r requirements.txt manually
    pause
    exit /b 1
) else (
    echo [OK] Python dependencies installed successfully
)
echo.

REM Check for Ollama
echo [5/6] Checking Ollama installation...
ollama --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [WARNING] Ollama is not installed or not in PATH.
    echo [INFO] Ollama is required to run AI models locally.
    echo [INFO] Please install Ollama from https://ollama.ai/download
    echo.
    echo [INFO] After installing Ollama, run these commands to get started:
    echo        ollama serve
    echo        ollama pull llama3.1
    echo.
) else (
    echo [OK] Ollama is installed
    echo [INFO] Make sure Ollama is running with: ollama serve
)
echo.

REM Install npm dependencies (if package.json exists)
echo [6/6] Installing npm dependencies for frontend...
if exist package.json (
    npm --version >nul 2>&1
    if %errorLevel% neq 0 (
        echo [WARNING] npm is not available. Skipping frontend dependencies.
        echo [INFO] Install Node.js to enable frontend features.
    ) else (
        npm install
        if %errorLevel% neq 0 (
            echo [WARNING] Failed to install npm dependencies.
        ) else (
            echo [OK] npm dependencies installed successfully
        )
    )
) else (
    echo [INFO] No package.json found. Skipping npm dependencies.
)
echo.

REM Create data directory if it doesn't exist
if not exist data mkdir data
echo [OK] Data directory ready
echo.

echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo Next steps:
echo   1. Start Ollama:     ollama serve
echo   2. Pull a model:     ollama pull llama3.1
echo   3. Run JRVS:         python main.py
echo.
echo For the web interface:
echo   1. Start API:        python api\server.py
echo   2. Start frontend:   npm run dev
echo   3. Open browser:     http://localhost:3000
echo.
echo See README.md for more information.
echo.
pause
