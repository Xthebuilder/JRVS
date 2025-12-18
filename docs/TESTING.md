# Testing Documentation for JRVS

## Overview

JRVS uses pytest for testing with coverage tracking, load testing with Locust, and security scanning with CodeQL.

## Test Structure

```
tests/
├── test_database.py          # Core database tests
├── test_calendar.py          # Calendar functionality tests
├── test_rag.py               # RAG system tests
├── test_ollama_client.py     # LLM client tests
├── test_web_scraper.py       # Web scraping tests
├── test_cli.py               # CLI interface tests
├── test_lmstudio_client.py   # LM Studio client tests
├── test_mcp_client.py        # MCP client tests
├── test_mcp_connection_cleanup.py  # MCP cleanup tests
├── test_integration.py       # Integration tests
└── load_test.py              # Load testing with Locust
```

## Running Tests

### Install Test Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `pytest` - Testing framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Coverage reporting
- `coverage` - Coverage tracking
- `locust` - Load testing

### Run All Tests

```bash
# Run all tests with coverage
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_database.py

# Run specific test
pytest tests/test_database.py::test_database_initialization
```

### Run Tests by Marker

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run slow tests
pytest -m slow

# Skip tests requiring external services
pytest -m "not requires_ollama and not requires_lmstudio"
```

### Coverage Reports

```bash
# Generate coverage report
pytest --cov=. --cov-report=html

# View HTML report
open htmlcov/index.html

# Generate terminal report
pytest --cov=. --cov-report=term-missing

# Generate XML report for CI/CD
pytest --cov=. --cov-report=xml
```

### Coverage Goals

- **Target:** 80%+ overall coverage
- **Core modules:** 90%+ coverage
- **Integration tests:** 70%+ coverage

## Load Testing

### Start Load Test

```bash
# Start Locust web interface
locust -f tests/load_test.py --host=http://localhost:8080

# Open browser to http://localhost:8089
```

### Headless Load Testing

```bash
# Light load (10 users)
locust -f tests/load_test.py --users 10 --spawn-rate 1 \
  --host=http://localhost:8080 --headless --run-time 2m

# Medium load (50 users)
locust -f tests/load_test.py --users 50 --spawn-rate 5 \
  --host=http://localhost:8080 --headless --run-time 5m

# Heavy load (200 users)
locust -f tests/load_test.py --users 200 --spawn-rate 10 \
  --host=http://localhost:8080 --headless --run-time 5m

# Stress test (500 users)
locust -f tests/load_test.py --users 500 --spawn-rate 50 \
  --host=http://localhost:8080 --headless --run-time 10m
```

### Load Test User Classes

1. **JRVSApiUser** - General API operations (chat, search, models)
2. **JRVSRagUser** - RAG-heavy operations (context retrieval, document addition)
3. **JRVSStressUser** - Rapid-fire requests for stress testing

### Interpreting Load Test Results

Key metrics to monitor:
- **Response Time (ms)**: Target < 1000ms for 95th percentile
- **Requests/sec**: Throughput capacity
- **Failure Rate (%)**: Target < 1%
- **CPU/Memory Usage**: Monitor system resources

## Memory Leak Testing

### Manual Memory Testing

```bash
# Monitor memory usage during tests
python -m memory_profiler tests/test_integration.py

# Use pytest-monitor for automatic memory tracking
pytest --collect-only
```

### Memory Leak Prevention

All modules now implement proper cleanup:

1. **Embeddings Manager** (`rag/embeddings.py`)
   - `cleanup()` method clears cache and model
   - Context manager support
   - Automatic CUDA cache clearing

2. **Vector Store** (`rag/vector_store.py`)
   - `cleanup()` method saves and clears index
   - Context manager support
   - Document map clearing

3. **Database** (`core/database.py`)
   - Connection pooling with aiosqlite
   - Automatic connection cleanup

4. **MCP Client** (`mcp_gateway/client.py`)
   - Proper async context cleanup
   - CancelledError handling
   - Connection cleanup on exit

### Testing for Memory Leaks

```python
import pytest
import gc

@pytest.mark.asyncio
async def test_no_memory_leak():
    """Test that resources are properly cleaned up"""
    from rag.embeddings import EmbeddingManager
    
    # Create and use manager
    async with EmbeddingManager() as manager:
        await manager.encode_text(["test"] * 100)
    
    # Force garbage collection
    gc.collect()
    
    # Verify cleanup (implementation specific)
    assert True  # Add specific checks
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
    
    - name: Run tests with coverage
      run: |
        pytest --cov=. --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
      with:
        file: ./coverage.xml
```

## Best Practices

### Writing Tests

1. **Use fixtures for setup/teardown**
   ```python
   @pytest.fixture
   async def temp_db():
       db = Database(":memory:")
       await db.initialize()
       yield db
       # Cleanup happens automatically
   ```

2. **Mock external dependencies**
   ```python
   @patch('requests.get')
   def test_with_mock(mock_get):
       mock_get.return_value.status_code = 200
       # Test implementation
   ```

3. **Test edge cases**
   - Empty inputs
   - Large inputs
   - Invalid inputs
   - Concurrent operations

4. **Use markers for organization**
   ```python
   @pytest.mark.unit
   @pytest.mark.asyncio
   async def test_something():
       pass
   ```

### Testing Async Code

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected
```

### Testing Error Handling

```python
def test_error_handling():
    with pytest.raises(ValueError):
        function_that_should_raise()
```

## Troubleshooting

### Common Issues

1. **"RuntimeError: Event loop is closed"**
   - Use `@pytest.mark.asyncio` decorator
   - Check pytest-asyncio configuration

2. **"ModuleNotFoundError"**
   - Ensure PYTHONPATH includes project root
   - Install all dependencies

3. **"Coverage too low"**
   - Add tests for uncovered code
   - Check `.coveragerc` exclusions

4. **"Locust not starting"**
   - Ensure API server is running
   - Check host/port configuration
   - Verify firewall settings

### Debug Mode

```bash
# Run tests with debug output
pytest -v --log-cli-level=DEBUG

# Run single test with debugging
pytest -v -s tests/test_database.py::test_specific_function

# Use pytest debugging
pytest --pdb  # Drop into debugger on failure
```

## Performance Benchmarks

### Target Performance

| Operation | Target Time |
|-----------|-------------|
| Embedding generation (single) | < 100ms |
| Embedding generation (batch 10) | < 500ms |
| Vector search (k=5) | < 50ms |
| Database query | < 10ms |
| RAG context retrieval | < 1s |

### Measuring Performance

```python
import time

start = time.time()
await operation()
elapsed = time.time() - start
assert elapsed < 1.0  # Should be under 1 second
```

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [Locust Documentation](https://docs.locust.io/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
