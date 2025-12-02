# JRVS Enhanced MCP Server - Architecture Guide

## System Architecture

### High-Level Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        Client Applications                          │
│                   (Claude Code, MCP Clients)                        │
└────────────────┬───────────────────────────────────────────────────┘
                 │
                 │ MCP Protocol (stdio/HTTP)
                 │
┌────────────────▼───────────────────────────────────────────────────┐
│                   Middleware Layer                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ Request      │  │ Rate         │  │ Auth         │            │
│  │ Tracking     │  │ Limiting     │  │ Manager      │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
└────────────────────────────────────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────────────────┐
│                   Resilience Layer                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ Circuit      │  │ Retry        │  │ Timeout      │            │
│  │ Breakers     │  │ Logic        │  │ Handlers     │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │ Cache        │  │ Bulkheads    │                              │
│  │ Manager      │  │ (Concurrency)│                              │
│  └──────────────┘  └──────────────┘                              │
└────────────────────────────────────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────────────────┐
│                   MCP Tool Layer                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ RAG Tools    │  │ Ollama Tools │  │ Calendar     │            │
│  │ (17 tools)   │  │ (4 tools)    │  │ (5 tools)    │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │ Monitoring   │  │ Admin Tools  │                              │
│  │ (4 tools)    │  │ (1 tool)     │                              │
│  └──────────────┘  └──────────────┘                              │
└────────────────────────────────────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────────────────┐
│                   JRVS Core Layer                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ RAG          │  │ Database     │  │ Ollama       │            │
│  │ Retriever    │  │ Manager      │  │ Client       │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │ Web Scraper  │  │ Calendar     │                              │
│  │              │  │ Manager      │                              │
│  └──────────────┘  └──────────────┘                              │
└────────────────────────────────────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────────────────┐
│                   External Dependencies                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ FAISS        │  │ SQLite       │  │ Ollama       │            │
│  │ Vector DB    │  │ Database     │  │ LLM Service  │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
└────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Middleware Layer

#### Request Tracking (`metrics.py`)
- **Purpose**: Track all requests with timing, success/failure, error types
- **Data Collected**: Duration, tool name, timestamp, error type, client ID
- **Storage**: In-memory with configurable retention
- **Features**: Per-tool stats, percentile calculations (p50, p95, p99)

#### Rate Limiting (`rate_limiter.py`)
- **Algorithm**: Token bucket with configurable rate and burst
- **Scope**: Per-client rate limits
- **Features**: Custom limits per client, async wait support
- **Integration**: Automatic rejection with RateLimitExceededError

#### Authentication (`auth.py`)
- **Method**: API key-based authentication
- **Features**: RBAC, key expiration, usage tracking
- **Storage**: In-memory (can be extended to Redis/DB)
- **Security**: SHA-256 key hashing, no plaintext storage

### 2. Resilience Layer

#### Circuit Breakers (`resilience.py`)
- **Pattern**: Fail-fast to prevent cascading failures
- **States**: CLOSED → OPEN → HALF_OPEN → CLOSED
- **Configuration**: Failure threshold, recovery timeout
- **Coverage**: Ollama, RAG, Web Scraper services

#### Retry Logic
- **Strategy**: Exponential backoff with jitter
- **Configuration**: Max attempts, initial delay, backoff multiplier
- **Exceptions**: Configurable exception types to retry
- **Callback**: Optional on_retry callback for logging

#### Timeouts
- **Implementation**: AsyncIO wait_for with timeout
- **Scope**: Per-function timeout limits
- **Behavior**: Raises TimeoutError on expiration

#### Caching (`cache.py`)
- **Implementation**: LRU cache with TTL
- **Levels**: Multiple caches (RAG, Ollama, Scraper, General)
- **Features**: Hit/miss tracking, automatic cleanup, stats
- **Eviction**: LRU + TTL based

#### Bulkheads
- **Purpose**: Limit concurrent operations
- **Implementation**: AsyncIO Semaphore
- **Scope**: Embedding generation, scraping, Ollama requests
- **Benefit**: Prevent resource exhaustion

### 3. Tool Layer

#### RAG Tools (5 tools)
1. `search_knowledge_base` - Vector similarity search
2. `get_context_for_query` - RAG context retrieval
3. `add_document_to_knowledge_base` - Document indexing
4. `scrape_and_index_url` - Web scraping + indexing
5. `get_rag_stats` - System statistics

**Enhancements**: All have caching, retry, timeout, circuit breaker

#### Ollama Tools (4 tools)
1. `list_ollama_models` - Model discovery
2. `get_current_model` - Current model info
3. `switch_ollama_model` - Model switching
4. `generate_with_ollama` - Text generation

**Enhancements**: Caching (list), bulkhead (generate), circuit breaker

#### Calendar Tools (5 tools)
1. `get_calendar_events` - Retrieve events
2. `get_today_events` - Today's events
3. `create_calendar_event` - Create event
4. `delete_calendar_event` - Delete event
5. `mark_event_completed` - Mark completion

**Enhancements**: Caching for reads

#### Monitoring Tools (4 tools)
1. `get_health_status` - Component health checks
2. `get_metrics` - Performance metrics
3. `get_cache_stats` - Cache statistics
4. `get_rate_limit_stats` - Rate limit stats

#### Admin Tools (1 tool)
1. `clear_cache` - Cache management

### 4. Observability

#### Structured Logging (`logging_config.py`)
- **Format**: JSON for machine readability, colored for console
- **Fields**: timestamp, service, level, logger, message, context
- **Output**: stderr (console) + file (JSON)
- **Context**: Request ID, tool name, client ID, duration

#### Metrics Collection (`metrics.py`)
```python
{
  "uptime_seconds": 3600,
  "requests": {
    "total_requests": 1250,
    "successful_requests": 1230,
    "failed_requests": 20,
    "success_rate": 98.4,
    "performance": {
      "avg_duration_ms": 245.3,
      "p50_duration_ms": 180.5,
      "p95_duration_ms": 1200.5,
      "p99_duration_ms": 2500.0
    }
  },
  "tools": {
    "search_knowledge_base": { ... },
    "generate_with_ollama": { ... }
  },
  "resources": {
    "current": { "cpu_percent": 15.2, "memory_mb": 512 },
    "avg_cpu_percent": 12.5,
    "avg_memory_mb": 480
  }
}
```

#### Health Checks (`health.py`)
```python
{
  "status": "healthy",
  "timestamp": "2025-11-27T12:34:56Z",
  "components": {
    "ollama": {
      "status": "healthy",
      "message": "Connected - 3 models available",
      "response_time_ms": 45.2
    },
    "database": { "status": "healthy", ... },
    "rag": { "status": "healthy", ... },
    "calendar": { "status": "healthy", ... },
    "cache": { "status": "healthy", ... }
  }
}
```

### 5. Configuration Management

#### Config Structure (`config_manager.py`)
- **Format**: JSON with schema validation
- **Priority**: ENV vars > Config file > Defaults
- **Validation**: Type checking, range validation
- **Runtime**: Hot reload support (future)

#### Environment Variables
All config can be overridden via environment variables:
- `JRVS_*` - Server config
- `OLLAMA_*` - Ollama config
- `JRVS_CACHE_*` - Cache config
- `JRVS_RATE_LIMIT_*` - Rate limit config
- `JRVS_AUTH_*` - Auth config

### 6. Lifecycle Management

#### Startup Sequence
1. Load configuration (file + env)
2. Setup logging infrastructure
3. Initialize authentication (dev keys if enabled)
4. Initialize core components (DB, RAG, Calendar, Ollama)
5. Register health checks
6. Register cleanup tasks
7. Setup signal handlers (SIGTERM, SIGINT)
8. Start background tasks (metrics, health, cache cleanup)
9. Run MCP server

#### Shutdown Sequence
1. Receive SIGTERM/SIGINT
2. Mark shutdown requested
3. Run cleanup tasks (with timeouts):
   - Save metrics
   - Close database connections
   - Clear caches
   - Close Ollama client
   - Cleanup MCP client connections
4. Log shutdown summary
5. Exit

## Data Flow Examples

### Example 1: RAG Query with Full Middleware

```
Client Request: search_knowledge_base("machine learning")
    ↓
[Rate Limiter] Check token bucket → Allow (token consumed)
    ↓
[Resource Manager] Acquire request slot → Granted
    ↓
[Request Tracking] Create RequestContext (request_id, start_time)
    ↓
[Cache] Check cache → MISS
    ↓
[Retry Wrapper] Execute with retry logic
    ↓
[Timeout Wrapper] Execute with 30s timeout
    ↓
[Circuit Breaker] RAG circuit → CLOSED, allow
    ↓
[RAG Retriever] Vector search → Results
    ↓
[Cache] Store results (TTL=600s)
    ↓
[Metrics] Record request (success, duration=145ms)
    ↓
[Resource Manager] Release request slot
    ↓
[Request Tracking] Log completion
    ↓
Client Response: [...search results...]
```

### Example 2: Ollama Generation with Failures

```
Client Request: generate_with_ollama("Hello")
    ↓
[Rate Limiter] Check → Allow
    ↓
[Bulkhead] Check concurrency (current=5, max=10) → Allow
    ↓
[Circuit Breaker] Ollama circuit → CLOSED
    ↓
[Ollama Client] Call Ollama API → Connection Error
    ↓
[Circuit Breaker] Record failure (count=1/5)
    ↓
[Retry Logic] Wait 1s, retry (attempt 2/3)
    ↓
[Ollama Client] Call Ollama API → Connection Error
    ↓
[Circuit Breaker] Record failure (count=2/5)
    ↓
[Retry Logic] Wait 2s, retry (attempt 3/3)
    ↓
[Ollama Client] Call Ollama API → Success
    ↓
[Circuit Breaker] Reset failure count
    ↓
[Metrics] Record request (success, duration=3200ms)
    ↓
Client Response: "Hello! How can I help you?"
```

### Example 3: Circuit Breaker OPEN

```
... multiple Ollama failures ...
[Circuit Breaker] Failure count=5 → State=OPEN
    ↓
Client Request: generate_with_ollama("Hi")
    ↓
[Circuit Breaker] State=OPEN → Reject immediately
    ↓
[Metrics] Record request (failure, error=CircuitBreakerOpen, duration=1ms)
    ↓
Client Response: Error: "Circuit breaker is OPEN"

... wait recovery_timeout (60s) ...

Client Request: generate_with_ollama("Test")
    ↓
[Circuit Breaker] State=OPEN, timeout elapsed → HALF_OPEN
    ↓
[Ollama Client] Call Ollama API → Success
    ↓
[Circuit Breaker] Success in HALF_OPEN → CLOSED
    ↓
Client Response: Success
```

## Performance Characteristics

### Latency
- **Cache Hit**: ~0.1ms
- **Vector Search**: 50-200ms (depends on index size)
- **Ollama Generation**: 1-30s (depends on model and prompt)
- **Web Scraping**: 1-10s (depends on page size)

### Throughput
- **With Default Limits**: ~60 requests/min per client
- **Max Concurrent**: 100 simultaneous requests
- **Ollama Bulkhead**: 10 concurrent generations
- **Embedding Bulkhead**: 5 concurrent embedding operations

### Memory
- **Base Usage**: ~500MB
- **Cache Overhead**: ~100-500MB (depends on cache size)
- **Vector Store**: ~100MB per 10K documents
- **Per Request**: ~1-10MB

### Scalability
- **Horizontal**: Stateless design allows multiple instances
- **Vertical**: Limited by Ollama and FAISS capacity
- **Bottlenecks**: Ollama throughput, vector search latency

## Security Considerations

### Authentication
- API keys hashed with SHA-256
- No plaintext key storage
- Key expiration support
- Per-key usage tracking

### Rate Limiting
- Prevents abuse
- Per-client quotas
- Burst protection

### Input Validation
- URL validation for scraping
- Date format validation for calendar
- Parameter type checking

### Error Handling
- No sensitive data in error messages
- Stack traces only in debug mode
- Structured error responses

## Deployment Patterns

### Single Instance
```
Client → MCP Server → Ollama
                   → FAISS
                   → SQLite
```

### Multi-Instance with Load Balancer
```
         ┌→ MCP Server 1 ┐
Client → LB → MCP Server 2 → Shared Ollama
         └→ MCP Server 3 ┘    Shared FAISS
                               Shared DB (with locking)
```

### Containerized
```
Docker Network:
  - ollama (service)
  - jrvs-mcp-1 (service)
  - jrvs-mcp-2 (service)
  - jrvs-mcp-3 (service)

Volumes:
  - ollama_data (persistent models)
  - jrvs_data (shared DB + FAISS)
  - jrvs_logs (centralized logs)
```

## Extension Points

### Adding New Tools
1. Define tool function in `server_enhanced.py`
2. Add `@mcp.tool()` decorator
3. Add `@track_request("tool_name")` for metrics
4. Add resilience decorators (`@cached`, `@retry`, `@timeout`)
5. Implement tool logic
6. Add tests

### Adding New Health Checks
1. Define check function in `health.py`
2. Return `ComponentHealth` object
3. Register with `health_checker.register_check()`

### Custom Cache Backend
1. Implement cache interface in `cache.py`
2. Update `CacheManager` to use new backend
3. Configure via `config.json`

### Custom Authentication
1. Extend `AuthManager` in `auth.py`
2. Implement new auth method
3. Update `authenticate()` function
4. Configure via `config.json`
