FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Node.js for MCP servers
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/mcp

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV OLLAMA_BASE_URL=http://ollama:11434
ENV OLLAMA_DEFAULT_MODEL=llama3.1

# Expose ports (8000 for API, 8080 for web server)
EXPOSE 8000 8080

# Healthcheck for API server
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command (can be overridden in docker-compose)
# Use "api" mode for web/API access, "cli" for interactive CLI
CMD ["python", "api/server.py"]
