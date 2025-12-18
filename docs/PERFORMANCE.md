# Performance Guide for JRVS

## Overview

This document provides performance benchmarks, optimization tips, and load testing results for the JRVS AI Agent framework.

## Performance Targets

### Response Times (P95)
- **Chat Endpoint**: < 2 seconds (without LLM)
- **RAG Context Retrieval**: < 500ms
- **Document Ingestion**: < 1 second per document
- **Web Scraping**: < 3 seconds per page

### Throughput
- **API Requests**: > 100 req/s
- **Concurrent Users**: Support 50+ simultaneous users
- **Database Operations**: > 1000 ops/s

### Resource Usage
- **Memory**: < 500MB base usage
- **CPU**: < 50% under normal load
- **Storage**: Efficient vector index management

## Load Testing

### Setup

```bash
# Install Locust
pip install locust

# Start JRVS API
python api/server.py

# Run load tests
locust -f tests/load_test.py --host=http://localhost:8000
```

### Test Scenarios

#### 1. Normal Usage Pattern (JRVSUser)
Simulates typical user behavior:
- 50% chat queries
- 20% document search
- 20% health checks
- 10% other operations

```bash
# 10 users, 1 user/sec spawn rate, 5 minutes
locust -f tests/load_test.py --host=http://localhost:8000 \
    --users 10 --spawn-rate 1 --run-time 5m --headless
```

#### 2. High Intensity (IntenseUser)
Rapid-fire requests for stress testing:

```bash
# 50 users, aggressive spawn rate
locust -f tests/load_test.py --host=http://localhost:8000 \
    --users 50 --spawn-rate 5 --run-time 2m --headless \
    --class-picker IntenseUser
```

#### 3. RAG-Focused (RAGFocusedUser)
Heavy RAG operations:

```bash
# Focus on search and context retrieval
locust -f tests/load_test.py --host=http://localhost:8000 \
    --users 20 --spawn-rate 2 --run-time 10m --headless \
    --class-picker RAGFocusedUser
```

### Benchmark Results

*Example results from load testing on a typical developer machine:*

#### Configuration
- **Hardware**: 8 core CPU, 16GB RAM, SSD
- **Model**: llama3.1:8b (local)
- **Document Count**: 100 documents indexed

#### Results

| Scenario | Users | RPS | Avg Response | P95 | Error Rate |
|----------|-------|-----|--------------|-----|------------|
| Normal | 10 | 45 | 850ms | 1.2s | 0.1% |
| Normal | 25 | 98 | 1.1s | 2.0s | 0.5% |
| Intense | 50 | 145 | 1.8s | 3.5s | 2.1% |
| RAG-Focused | 20 | 72 | 650ms | 1.0s | 0.2% |

#### Bottlenecks Identified
1. **LLM Generation**: Primary bottleneck (CPU-bound)
2. **Vector Search**: Scales well up to 10k documents
3. **Database**: Not a bottleneck for typical usage
4. **Network I/O**: Minimal impact with local deployment

## Optimization Tips

### 1. Model Selection

**Use Smaller Models for Faster Response**
```python
# Faster models
ollama pull llama3.1:8b    # 8 billion parameters
ollama pull mistral:7b     # 7 billion parameters

# Slower but more capable
ollama pull llama3.1:70b   # 70 billion parameters
```

### 2. RAG Configuration

**Optimize Chunk Size**
```python
# config.py
CHUNK_SIZE = 512           # Smaller chunks = faster search
MAX_RETRIEVED_CHUNKS = 3   # Fewer chunks = less context processing
```

**Vector Store Optimization**
```python
# Use IVF index for large datasets
# In rag/vector_store.py
if len(embeddings) > 10000:
    index = faiss.IndexIVFFlat(quantizer, dimension, nlist=100)
    index.train(embeddings)
else:
    index = faiss.IndexFlatL2(dimension)
```

### 3. Database Performance

**Enable WAL Mode**
```python
# For better concurrent access
async with aiosqlite.connect(db_path) as db:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
```

**Use Indexes**
```sql
-- Already implemented in database.py
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url);
```

### 4. HTTP Session Management

**Reuse Sessions**
```python
# Already implemented - sessions are reused
# Avoid creating new session for each request
async with client._get_session() as session:
    # Reuses existing session
    response = await session.get(url)
```

### 5. Caching

**Implement Response Caching**
```python
from functools import lru_cache

# Cache expensive operations
@lru_cache(maxsize=1000)
def get_embedding_cached(text):
    return embedding_manager.get_embedding(text)
```

**Vector Store Caching**
- FAISS index is memory-mapped for fast access
- No need to reload on every request
- Consider persistence for large indexes

### 6. Concurrency

**Increase Worker Processes**
```python
# api/server.py
if __name__ == "__main__":
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        workers=4  # Multi-process for CPU-bound tasks
    )
```

**Async Operations**
```python
# Use gather for parallel operations
results = await asyncio.gather(
    fetch_url(url1),
    fetch_url(url2),
    fetch_url(url3)
)
```

### 7. Memory Management

**Clean Up Old Data**
```python
# Periodic cleanup
await db.cleanup_old_data(days=30)

# Clear embedding cache
embedding_manager.clear_cache()
```

**Monitor Memory Usage**
```python
import psutil
process = psutil.Process()
memory_mb = process.memory_info().rss / 1024 / 1024
print(f"Memory usage: {memory_mb:.2f} MB")
```

## Profiling

### CPU Profiling

```python
import cProfile
import pstats

# Profile specific function
profiler = cProfile.Profile()
profiler.enable()

# Your code here
await rag_retriever.retrieve_context(query)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

### Memory Profiling

```python
from memory_profiler import profile

@profile
async def memory_intensive_function():
    # Your code here
    pass

# Run with: python -m memory_profiler script.py
```

### Line Profiling

```bash
# Install line_profiler
pip install line_profiler

# Add @profile decorator to functions
# Run with:
kernprof -l -v script.py
```

## Monitoring

### Application Metrics

```python
# Add to api/server.py
import time
from prometheus_client import Counter, Histogram

request_count = Counter('requests_total', 'Total requests')
request_duration = Histogram('request_duration_seconds', 'Request duration')

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    
    request_count.inc()
    request_duration.observe(duration)
    
    return response
```

### System Metrics

```bash
# Monitor system resources
htop                    # CPU, memory
iotop                   # Disk I/O
nethogs                 # Network usage
```

## Scaling Strategies

### Vertical Scaling
- **CPU**: More cores = better LLM performance
- **RAM**: 32GB+ for large models (70B+)
- **Storage**: SSD for faster vector index access

### Horizontal Scaling
- **Load Balancer**: Nginx/HAProxy
- **Multiple API Instances**: Different ports
- **Shared Database**: Central SQLite or PostgreSQL
- **Distributed Vector Store**: Consider Milvus/Qdrant for large scale

### Model Optimization
- **Quantization**: Use quantized models (GGUF format)
- **GPU Acceleration**: Enable GPU if available
- **Model Caching**: Keep models loaded in memory

## Troubleshooting

### Slow Response Times

```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# Check system load
uptime

# Check disk I/O
iostat -x 1

# Profile slow endpoint
python -m cProfile -s cumulative api/server.py
```

### High Memory Usage

```bash
# Check memory usage
free -h

# Find memory leaks
python -m memory_profiler script.py

# Run memory leak tests
pytest tests/test_memory_leaks.py -v
```

### High CPU Usage

- Reduce model size (use 7B/8B instead of 70B)
- Limit concurrent requests
- Enable response streaming
- Consider GPU acceleration

## Best Practices

1. **Always use async/await** for I/O operations
2. **Reuse connections** (HTTP, database)
3. **Implement timeouts** for all external calls
4. **Cache frequently accessed data**
5. **Monitor and profile regularly**
6. **Clean up resources** in finally blocks
7. **Use connection pools** for concurrent access
8. **Implement rate limiting** for public APIs

## Performance Checklist

- [ ] Load test with expected user count
- [ ] Profile memory usage under load
- [ ] Check database query performance
- [ ] Verify vector search scales
- [ ] Test with production-size dataset
- [ ] Monitor resource usage over time
- [ ] Implement appropriate caching
- [ ] Configure timeouts appropriately
- [ ] Enable connection reuse
- [ ] Clean up resources properly

## Resources

- [FastAPI Performance Tips](https://fastapi.tiangolo.com/deployment/)
- [FAISS Performance Guide](https://github.com/facebookresearch/faiss/wiki/Faster-search)
- [Ollama Performance](https://github.com/ollama/ollama/blob/main/docs/performance.md)
- [Locust Documentation](https://docs.locust.io/)

## Continuous Improvement

Run regular performance tests and track metrics over time:

```bash
# Automated performance testing
./scripts/run_performance_tests.sh

# Generate report
pytest tests/load_test.py --benchmark-only --benchmark-json=benchmark.json
```

Monitor trends and optimize as needed. Aim for consistent performance improvements with each release.
