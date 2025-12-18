# Testing Guide for JRVS

## Overview

This document describes how to run tests, measure coverage, and contribute test cases to the JRVS project.

## Test Structure

```
tests/
├── test_database.py          # Database operations tests (100% coverage)
├── test_calendar.py          # Calendar functionality tests
├── test_ollama_client.py     # LLM client tests
├── test_retriever.py         # RAG retriever tests
├── test_web_scraper.py       # Web scraping tests
├── test_mcp_connection_cleanup.py  # MCP cleanup tests
├── load_test.py              # Load testing with Locust
└── ...
```

## Running Tests

### Prerequisites

Install testing dependencies:

```bash
pip install pytest pytest-asyncio pytest-cov pytest-timeout pytest-mock
```

### Run All Tests

```bash
# Run all tests with coverage
pytest

# Run tests verbosely
pytest -v

# Run specific test file
pytest tests/test_database.py

# Run specific test class
pytest tests/test_database.py::TestDatabase

# Run specific test
pytest tests/test_database.py::TestDatabase::test_add_conversation
```

### Run Tests by Marker

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"

# Run security tests
pytest -m security
```

### Timeout Control

Tests have a 300-second (5-minute) timeout by default. Override for specific tests:

```bash
# Run with 60-second timeout
pytest --timeout=60

# Disable timeout
pytest --timeout=0
```

## Code Coverage

### Generate Coverage Report

```bash
# Generate terminal coverage report
pytest --cov=core --cov=llm --cov=rag --cov=scraper --cov=api --cov=cli

# Generate HTML coverage report
pytest --cov=core --cov=llm --cov=rag --cov-report=html

# Open HTML report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Coverage Goals

- **Target**: 80%+ overall coverage
- **Current**: Check `.coveragerc` for excluded files
- **Critical modules**: core/, llm/, rag/, api/ should have >90% coverage

### Coverage Configuration

Coverage settings are in `.coveragerc`:

```ini
[run]
source = core, llm, rag, scraper, api, cli
omit = */tests/*, */__pycache__/*

[report]
precision = 2
show_missing = True
```

## Writing Tests

### Test File Naming

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test functions: `test_<functionality>`

### Example Unit Test

```python
import pytest
from core.database import Database

class TestDatabase:
    @pytest.fixture
    async def temp_db(self):
        """Create temporary database for testing"""
        db = Database(":memory:")
        await db.initialize()
        yield db
    
    @pytest.mark.asyncio
    async def test_add_conversation(self, temp_db):
        """Test adding a conversation"""
        conv_id = await temp_db.add_conversation(
            session_id="test",
            user_message="Hello",
            ai_response="Hi!",
            model_used="test_model"
        )
        assert conv_id > 0
```

### Example Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_rag_pipeline():
    """Test complete RAG workflow"""
    await rag_retriever.initialize()
    
    # Add document
    doc_id = await rag_retriever.add_document(
        content="Python is a programming language",
        title="Python Guide",
        url="https://example.com"
    )
    
    # Retrieve context
    context = await rag_retriever.retrieve_context("What is Python?")
    
    assert "Python" in context
```

### Async Test Best Practices

1. Always use `@pytest.mark.asyncio` for async tests
2. Use fixtures for setup/teardown
3. Clean up resources (close sessions, delete temp files)
4. Use timeouts for long-running operations

### Mocking External Dependencies

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_with_mock():
    """Test with mocked HTTP client"""
    with patch('aiohttp.ClientSession') as mock_session:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"data": "test"}
        
        mock_session.return_value.get.return_value = mock_response
        
        # Your test code here
```

## Load Testing

### Setup

```bash
pip install locust
```

### Run Load Tests

```bash
# Start JRVS API server
python api/server.py

# Run load test with UI
locust -f tests/load_test.py --host=http://localhost:8000

# Open browser
open http://localhost:8089

# Run headless load test
locust -f tests/load_test.py --host=http://localhost:8000 \
    --users 10 --spawn-rate 1 --run-time 5m --headless
```

### Load Test Scenarios

- **JRVSUser**: Normal usage pattern (chat, search, scraping)
- **IntenseUser**: High-frequency requests for stress testing
- **RAGFocusedUser**: RAG-heavy workload

### Performance Targets

- **Response Time**: P95 < 2 seconds for chat
- **Throughput**: >100 requests/second
- **Error Rate**: <1%

## Test Maintenance

### Before Committing

```bash
# Run all tests
pytest

# Check coverage
pytest --cov --cov-fail-under=80

# Run linting
eslint . --ext .js,.jsx,.ts,.tsx
```

### Adding New Tests

1. Create test file in `tests/` directory
2. Add appropriate markers (`@pytest.mark.unit`, etc.)
3. Ensure tests are independent and isolated
4. Add docstrings explaining what's being tested
5. Run tests and verify coverage increases

### Debugging Failing Tests

```bash
# Show print statements
pytest -s

# Drop into debugger on failure
pytest --pdb

# Show local variables on failure
pytest -l

# Verbose output
pytest -vv

# Show slowest tests
pytest --durations=10
```

## Continuous Integration

Tests run automatically on:

- Every push to main branch
- All pull requests
- Nightly builds

CI checks:

- All tests must pass
- Coverage must be ≥80%
- No security vulnerabilities (Bandit)
- Code style (Black, isort)

## Common Issues

### Import Errors

```bash
# Ensure PYTHONPATH includes project root
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Async Tests Not Running

- Ensure `pytest-asyncio` is installed
- Add `@pytest.mark.asyncio` decorator
- Check `pytest.ini` has `asyncio_mode = auto`

### Coverage Not Measured

- Ensure modules are in `source` list in `.coveragerc`
- Run with `--cov` flag
- Check that code is actually executed

### Slow Tests

- Use `@pytest.mark.slow` to mark slow tests
- Skip with `pytest -m "not slow"`
- Consider mocking external services

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
- [Locust Documentation](https://docs.locust.io/)
- [Coverage.py](https://coverage.readthedocs.io/)

## Getting Help

- Check existing test examples in `tests/` directory
- Review pytest documentation
- Ask in project discussions
- Open an issue for test-related bugs
