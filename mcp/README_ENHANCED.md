# JRVS Enhanced MCP Server 🚀

**Production-ready Model Context Protocol server with enterprise-grade reliability, performance, and monitoring.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

---

## 🌟 Features

### Core Capabilities
- **🧠 RAG System**: FAISS vector search with BERT embeddings
- **🤖 Ollama Integration**: Local LLM inference with multiple model support
- **📅 Calendar Management**: Event scheduling and tracking
- **🌐 Web Scraping**: Automatic content extraction and indexing
- **💾 Conversation History**: Persistent chat storage

### Production Features
- **🛡️ Robust Error Handling**: Circuit breakers, retry mechanisms, fallback strategies
- **⚡ Performance**: Multi-level caching, connection pooling, async operations
- **🔒 Security**: API key authentication, RBAC, rate limiting
- **📊 Monitoring**: Real-time metrics, health checks, structured logging
- **🎯 Resource Management**: Request quotas, concurrency limits, memory tracking
- **🔄 Graceful Shutdown**: Clean state persistence, connection draining
- **📈 Observability**: JSON logs, Prometheus metrics, performance tracking

---

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Deployment](#deployment)
- [Monitoring](#monitoring)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Ollama** ([Install Ollama](https://ollama.ai))
- **Docker** (optional, for containerized deployment)

### Installation

1. **Clone the repository**:
   ```bash
   cd JRVS
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start Ollama**:
   ```bash
   ollama serve
   ```

4. **Pull a model**:
   ```bash
   ollama pull deepseek-r1:14b
   ```

5. **Run the enhanced MCP server**:
   ```bash
   python mcp/server_enhanced.py
   ```

### Docker Deployment

```bash
# Build and start all services
docker-compose -f docker-compose.mcp.yml up -d

# View logs
docker-compose -f docker-compose.mcp.yml logs -f jrvs-mcp

# Stop services
docker-compose -f docker-compose.mcp.yml down
```

---

## 🏗️ Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  JRVS Enhanced MCP Server                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Rate       │  │   Circuit    │  │   Request    │      │
│  │   Limiter    │  │   Breakers   │  │   Tracking   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Caching    │  │   Metrics    │  │   Health     │      │
│  │   Layer      │  │   Collector  │  │   Checks     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              MCP Tool Handlers                       │    │
│  ├─────────────────────────────────────────────────────┤    │
│  │  RAG • Ollama • Calendar • Scraper • History        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              JRVS Core Components                    │    │
│  ├─────────────────────────────────────────────────────┤    │
│  │  Vector Store • Database • Embeddings • Web Client  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. **Resilience Layer** (`mcp/resilience.py`)
- **Circuit Breakers**: Prevent cascading failures
- **Retry Logic**: Exponential backoff with jitter
- **Timeouts**: Prevent hung requests
- **Bulkheads**: Limit concurrent operations

#### 2. **Caching Layer** (`mcp/cache.py`)
- **LRU Cache**: Memory-efficient eviction
- **TTL Support**: Automatic expiration
- **Multi-Cache**: Separate caches for different use cases
- **Background Cleanup**: Periodic expired entry removal

#### 3. **Rate Limiting** (`mcp/rate_limiter.py`)
- **Token Bucket Algorithm**: Smooth rate limiting
- **Per-Client Limits**: Customizable quotas
- **Resource Management**: Concurrent request limits
- **Request Duration Tracking**: Timeout enforcement

#### 4. **Monitoring** (`mcp/metrics.py`, `mcp/health.py`)
- **Request Metrics**: Latency, success rate, throughput
- **Health Checks**: Component status monitoring
- **Resource Tracking**: CPU, memory, threads
- **Structured Logging**: JSON format for easy parsing

#### 5. **Authentication** (`mcp/auth.py`)
- **API Key Management**: Secure key generation
- **RBAC**: Role-based access control
- **Key Expiration**: Time-based key invalidation
- **Usage Tracking**: Per-key statistics

---

## ⚙️ Configuration

### Environment Variables

```bash
# Server
JRVS_HOST=0.0.0.0
JRVS_PORT=3000
JRVS_LOG_LEVEL=INFO

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=deepseek-r1:14b

# Database
JRVS_DB_PATH=data/jarvis.db

# Cache
JRVS_CACHE_ENABLED=true

# Rate Limiting
JRVS_RATE_LIMIT_ENABLED=true
JRVS_RATE_LIMIT_PER_MINUTE=60

# Authentication
JRVS_AUTH_ENABLED=false
JRVS_REQUIRE_API_KEY=false
```

### Configuration File

Create `mcp/config.json`:

```json
{
  "server": {
    "host": "localhost",
    "port": 3000,
    "log_level": "INFO",
    "log_file": "logs/jrvs-mcp.log",
    "json_logs": true
  },
  "ollama": {
    "base_url": "http://localhost:11434",
    "default_model": "deepseek-r1:14b",
    "timeout_seconds": 300,
    "max_retries": 3
  },
  "cache": {
    "enabled": true,
    "max_size": 1000,
    "default_ttl_seconds": 300
  },
  "rate_limit": {
    "enabled": true,
    "default_rate_per_minute": 60,
    "default_burst": 10
  },
  "resource": {
    "max_memory_mb": 2048,
    "max_concurrent_requests": 100,
    "max_request_duration_seconds": 300
  },
  "monitoring": {
    "enabled": true,
    "metrics_interval_seconds": 30,
    "health_check_interval_seconds": 60
  }
}
```

---

## 📚 API Reference

### RAG & Knowledge Base Tools

#### `search_knowledge_base(query: str, limit: int = 5)`
Search the vector database using semantic similarity.

**Features**: Caching, retry logic, timeout protection

```python
# Example
results = await search_knowledge_base(
    query="machine learning algorithms",
    limit=5
)
```

#### `get_context_for_query(query: str, session_id: Optional[str])`
Retrieve enriched context from RAG system and conversation history.

#### `add_document_to_knowledge_base(content: str, title: str, url: str, metadata: dict)`
Index a new document in the knowledge base.

**Features**: Bulkhead limiting for embedding generation

#### `scrape_and_index_url(url: str)`
Scrape website and automatically index content.

**Features**: Retry with backoff, circuit breaker, timeout

#### `get_rag_stats()`
Get RAG system statistics (vector count, cache stats, etc.)

### Ollama LLM Tools

#### `list_ollama_models()`
List all available Ollama models.

**Features**: Response caching (60s TTL)

#### `get_current_model()`
Get the currently active model.

#### `switch_ollama_model(model_name: str)`
Switch to a different Ollama model.

#### `generate_with_ollama(prompt: str, context: Optional[str], system_prompt: Optional[str])`
Generate text using the current Ollama model.

**Features**: Auto RAG context injection, bulkhead limiting, timeout

### Calendar Tools

#### `get_calendar_events(days: int = 7)`
Retrieve upcoming events.

**Features**: Response caching (300s TTL)

#### `create_calendar_event(title: str, event_date: str, description: str, reminder_minutes: int)`
Create a new calendar event.

#### `delete_calendar_event(event_id: int)`
Delete an event.

#### `mark_event_completed(event_id: int)`
Mark an event as completed.

### Monitoring Tools

#### `get_health_status()`
Get comprehensive health report for all components.

```json
{
  "status": "healthy",
  "components": {
    "ollama": {
      "status": "healthy",
      "message": "Connected - 3 models available"
    },
    "database": {
      "status": "healthy",
      "message": "Database operational"
    }
  }
}
```

#### `get_metrics()`
Get performance metrics and statistics.

```json
{
  "uptime_seconds": 3600,
  "requests": {
    "total_requests": 1250,
    "success_rate": 98.4,
    "performance": {
      "avg_duration_ms": 245.3,
      "p95_duration_ms": 1200.5
    }
  }
}
```

#### `get_cache_stats()`
Get cache hit rates and sizes.

#### `get_rate_limit_stats()`
Get rate limiting statistics.

### Admin Tools

#### `clear_cache(cache_type: Optional[str])`
Clear cache (all or specific type: rag, ollama, scraper, general).

---

## 🐳 Deployment

### Docker Compose (Recommended)

The `docker-compose.mcp.yml` file provides a complete deployment with:
- Ollama service with persistent storage
- JRVS MCP server with health checks
- Automatic network configuration
- Volume management for data persistence

```bash
# Start services
docker-compose -f docker-compose.mcp.yml up -d

# Scale JRVS instances (if needed)
docker-compose -f docker-compose.mcp.yml up -d --scale jrvs-mcp=3

# View logs
docker-compose -f docker-compose.mcp.yml logs -f

# Stop services
docker-compose -f docker-compose.mcp.yml down
```

### Kubernetes Deployment

Example K8s manifests coming soon...

### Production Checklist

- [ ] Enable authentication (`JRVS_AUTH_ENABLED=true`)
- [ ] Set up proper API keys (disable development mode)
- [ ] Configure appropriate rate limits
- [ ] Set up log aggregation (ELK, Splunk, etc.)
- [ ] Configure metrics export (Prometheus)
- [ ] Set up alerting (based on health checks)
- [ ] Use external cache (Redis) for multi-instance deployments
- [ ] Configure backup for database and vector store
- [ ] Set up SSL/TLS termination
- [ ] Implement request authentication/authorization

---

## 📊 Monitoring

### Structured Logging

All logs are in JSON format for easy parsing:

```json
{
  "timestamp": "2025-11-27T12:34:56.789Z",
  "service": "jrvs-mcp",
  "level": "INFO",
  "logger": "mcp.server_enhanced",
  "message": "Request completed: search_knowledge_base",
  "request_id": "abc-123",
  "tool_name": "search_knowledge_base",
  "duration_ms": 145.3,
  "success": true
}
```

### Health Check Endpoint

Monitor component health:

```bash
# Using MCP tool
get_health_status()

# Returns status for:
# - Ollama connection
# - Database
# - RAG system
# - Calendar
# - Cache
```

### Metrics

Key metrics tracked:
- **Request Metrics**: Total, success/failure, latency (avg, p50, p95, p99)
- **Per-Tool Metrics**: Request count, error rate, performance
- **Resource Metrics**: CPU%, memory, thread count
- **Cache Metrics**: Hit rate, size, evictions
- **Rate Limit Metrics**: Utilization, throttled requests

### Alerts

Set up alerts for:
- Overall health status != healthy
- Success rate < 95%
- P95 latency > threshold
- Cache hit rate < 50%
- Memory usage > 80%
- Circuit breakers open

---

## 🧪 Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest mcp/tests/test_enhanced_server.py -v

# Run specific test
pytest mcp/tests/test_enhanced_server.py::test_cache_basic -v

# Run with coverage
pytest mcp/tests/test_enhanced_server.py --cov=mcp --cov-report=html
```

### Development Mode

```bash
# Enable debug logging
export JRVS_LOG_LEVEL=DEBUG

# Run with auto-reload (for development)
python mcp/server_enhanced.py
```

### Adding New Tools

1. Create tool function in `server_enhanced.py`
2. Add `@mcp.tool()` decorator
3. Add `@track_request("tool_name")` for metrics
4. Add caching, retry, timeout as needed
5. Update tests in `test_enhanced_server.py`

Example:

```python
@mcp.tool()
@track_request("my_new_tool")
@cached(cache_type="general", ttl=300)
@retry(max_attempts=3)
@timeout(30)
async def my_new_tool(param: str) -> Dict[str, Any]:
    """
    My new tool description.

    Features: caching, retry, timeout
    """
    # Implementation
    return {"result": "success"}
```

---

## 🔧 Troubleshooting

### Common Issues

#### Ollama Connection Errors

```
OllamaConnectionError: Cannot connect to Ollama at http://localhost:11434
```

**Solution**:
- Ensure Ollama is running: `ollama serve`
- Check Ollama URL in config/env
- Verify firewall rules

#### Rate Limit Exceeded

```
RateLimitExceededError: Rate limit exceeded: 60 requests per minute
```

**Solution**:
- Increase rate limit in config
- Set custom limit for client: `rate_limiter.set_custom_limit("client_id", rate=120, burst=20)`
- Implement backoff in client

#### Circuit Breaker Open

```
Exception: Circuit breaker is OPEN. Service unavailable.
```

**Solution**:
- Check health of downstream service (Ollama, database, etc.)
- Wait for recovery timeout (default 60s)
- Check logs for root cause

#### Memory Issues

```
ResourceExhaustedError: memory exhausted: 2048/2048
```

**Solution**:
- Increase `max_memory_mb` in config
- Reduce cache sizes
- Check for memory leaks
- Scale horizontally

### Debug Mode

Enable detailed logging:

```bash
export JRVS_LOG_LEVEL=DEBUG
python mcp/server_enhanced.py
```

### Performance Tuning

- **Increase cache sizes** for better hit rates
- **Adjust rate limits** based on traffic patterns
- **Tune concurrency limits** for optimal throughput
- **Configure timeout values** based on actual latencies
- **Enable/disable features** based on requirements

---

## 📄 License

This project is for educational and personal use.

---

## 🙏 Acknowledgments

- **MCP**: Model Context Protocol specification
- **Ollama**: Local LLM inference
- **FAISS**: Vector similarity search
- **FastMCP**: Python MCP framework

---

## 📞 Support

For issues and questions:
- Check [Troubleshooting](#troubleshooting) section
- Review logs in `logs/jrvs-mcp-enhanced.log`
- Check health status: `get_health_status()`
- Check metrics: `get_metrics()`

---

**Built with ❤️ for production reliability** 🚀
