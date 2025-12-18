# Contributing to JRVS

Thank you for your interest in contributing to JRVS! This document provides guidelines for contributing to the project.

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help make JRVS better for everyone

## Getting Started

### Development Setup

1. **Clone the repository**
```bash
git clone https://github.com/Xthebuilder/JRVS.git
cd JRVS
```

2. **Create a virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Run tests**
```bash
pytest
```

## Development Workflow

### Before Starting Work

1. Check existing issues and PRs to avoid duplicate work
2. Open an issue to discuss major changes
3. Fork the repository and create a feature branch
4. Keep changes focused and atomic

### Making Changes

1. **Write Tests First** (TDD recommended)
```bash
# Create test file
touch tests/test_your_feature.py

# Run tests
pytest tests/test_your_feature.py -v
```

2. **Implement Feature**
- Follow existing code style
- Add docstrings to public functions
- Keep functions small and focused
- Use type hints where appropriate

3. **Run Tests and Coverage**
```bash
# Run all tests
pytest

# Check coverage
pytest --cov --cov-report=html

# View coverage report
open htmlcov/index.html
```

4. **Security Check**
```bash
bandit -r core/ llm/ rag/ scraper/ api/ cli/
```

5. **Format Code** (if using formatters)
```bash
# Using black (optional)
black core/ llm/ rag/ scraper/ api/ cli/

# Using isort (optional)
isort core/ llm/ rag/ scraper/ api/ cli/
```

### Commit Messages

Use clear, descriptive commit messages:

```
Short summary (50 chars or less)

Detailed explanation if needed. Explain what and why,
not how. Wrap at 72 characters.

- Bullet points are okay
- Use present tense: "Add feature" not "Added feature"
- Reference issues: "Fixes #123"
```

Examples:
```
Add user authentication to API endpoints

Add tests for database connection pooling

Fix memory leak in HTTP session management

Improve RAG context retrieval performance
```

## Code Style

### Python

- Follow PEP 8
- Use 4 spaces for indentation
- Max line length: 100 characters
- Use docstrings for modules, classes, and functions

```python
"""
Module docstring explaining the module's purpose
"""

class MyClass:
    """Class docstring"""
    
    def my_method(self, param: str) -> bool:
        """
        Method docstring
        
        Args:
            param: Description of parameter
            
        Returns:
            Description of return value
        """
        # Implementation
        pass
```

### Async Code

- Use async/await for I/O operations
- Always clean up resources
- Use context managers where appropriate

```python
async def fetch_data():
    """Fetch data with proper cleanup"""
    async with session.get(url) as response:
        return await response.json()
```

## Testing Guidelines

### Test Structure

```python
class TestMyFeature:
    """Test suite for MyFeature"""
    
    @pytest.fixture
    async def setup(self):
        """Setup test dependencies"""
        # Setup code
        yield resource
        # Teardown code
    
    @pytest.mark.asyncio
    async def test_basic_functionality(self, setup):
        """Test basic functionality"""
        result = await my_function()
        assert result == expected
    
    @pytest.mark.asyncio
    async def test_error_handling(self, setup):
        """Test error handling"""
        with pytest.raises(ValueError):
            await my_function(invalid_input)
```

### Test Coverage

- Aim for >80% coverage on new code
- Test happy path and error cases
- Test edge cases and boundary conditions
- Use mocks for external dependencies

### Running Specific Tests

```bash
# Run specific file
pytest tests/test_database.py

# Run specific test
pytest tests/test_database.py::TestDatabase::test_add_conversation

# Run by marker
pytest -m unit
pytest -m "not slow"
```

## Pull Request Process

1. **Update Documentation**
   - Update README if adding features
   - Add docstrings to new functions
   - Update CHANGELOG if significant

2. **Ensure Tests Pass**
```bash
pytest --cov --cov-fail-under=80
```

3. **Create Pull Request**
   - Use descriptive title
   - Reference related issues
   - Explain what and why
   - Include screenshots for UI changes

4. **PR Checklist**
   - [ ] Tests added and passing
   - [ ] Coverage ≥ 80%
   - [ ] Documentation updated
   - [ ] Security scan passed
   - [ ] Code style followed
   - [ ] No merge conflicts

## Areas for Contribution

### High Priority
- Increase test coverage to 80%+
- Performance optimizations
- Bug fixes
- Security improvements

### Medium Priority
- Additional LLM providers
- Enhanced RAG algorithms
- UI/UX improvements
- Documentation improvements

### Ideas Welcome
- New MCP servers
- Tool integrations
- Example use cases
- Tutorial content

## Reporting Bugs

### Before Reporting

1. Check existing issues
2. Try latest version
3. Gather error messages and logs
4. Create minimal reproduction

### Bug Report Template

```markdown
**Description**
Clear description of the bug

**To Reproduce**
Steps to reproduce:
1. Go to '...'
2. Click on '...'
3. See error

**Expected Behavior**
What should happen

**Actual Behavior**
What actually happens

**Environment**
- OS: [e.g., Windows 10, macOS 14, Ubuntu 22.04]
- Python version: [e.g., 3.11.5]
- JRVS version: [e.g., 0.1.0]
- Ollama version: [if applicable]

**Logs**
```
Paste relevant logs here
```

**Screenshots**
If applicable
```

## Feature Requests

Feature requests are welcome! Please:

1. Check if already requested
2. Describe the use case
3. Explain the benefit
4. Propose implementation (optional)

## Questions?

- Open a GitHub Discussion
- Check documentation in `docs/`
- Review existing issues

## Recognition

Contributors will be recognized in:
- CONTRIBUTORS.md file
- Release notes for significant contributions
- Project README

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Thank You!

Every contribution, no matter how small, is valued and appreciated!
