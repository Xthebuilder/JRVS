# JARCORE - JARVIS Autonomous Reasoning & Coding Engine

AI-powered coding assistant integrated into JRVS MCP server, using local Ollama models for autonomous code generation, analysis, and execution.

## Overview

JARCORE (JARVIS Autonomous Reasoning & Coding Engine) brings professional coding capabilities to your AI assistant using locally-run Ollama models. It provides nanocoder-inspired functionality while maintaining complete privacy and control over your code.

## Features

### 🤖 Code Generation
- **Natural Language to Code**: Describe what you want in plain English, get working code
- **Multi-Language Support**: Python, JavaScript, TypeScript, Go, Rust, Java, C/C++, and more
- **Context-Aware**: Uses RAG to understand your project context
- **Test Generation**: Automatically generate unit tests

### 🔍 Code Analysis
- **Comprehensive Analysis**: Bugs, security, performance, style
- **Security Scanning**: Identify vulnerabilities and security issues
- **Performance Optimization**: Suggestions for better efficiency
- **Best Practices**: Style and maintainability recommendations

### ♻️ Code Refactoring
- **AI-Powered Refactoring**: Improve readability and maintainability
- **Metrics Tracking**: Before/after complexity metrics
- **Change Explanation**: Detailed reasoning for each change

### 📝 Code Explanation
- **Natural Language**: Understand complex code in plain English
- **Multiple Detail Levels**: Brief, medium, or detailed explanations
- **Educational**: Learn from existing code

### 🛠️ Error Fixing
- **Automatic Debugging**: Fix code based on error messages
- **Prevention Tips**: Learn how to avoid similar issues
- **Explanation**: Understand what went wrong

### 📁 File Operations
- **Read/Write**: Syntax-aware file handling
- **Auto-Backup**: Automatic backups before editing
- **Language Detection**: Automatic syntax detection

### ▶️ Code Execution
- **Safe Execution**: Run code with timeout protection
- **Output Capture**: Get stdout, stderr, exit codes
- **Multi-Language**: Python, Bash, JavaScript support

### 💡 Code Completion
- **Intelligent Suggestions**: Context-aware completions
- **Multi-Option**: Multiple suggestions per request

## Architecture

```
JRVS/
├── mcp_gateway/
│   ├── server.py           # MCP server with coding tools
│   ├── jarcore.py     # Core JARCORE implementation
│   └── agent.py            # Intelligent tool orchestration
├── llm/
│   └── ollama_client.py    # Ollama integration
└── rag/
    └── retriever.py        # Context retrieval for coding
```

## MCP Tools

The JARCORE exposes 11 MCP tools that can be used via any MCP client:

### 1. `generate_code`
```python
generate_code(
    task: str,                    # What the code should do
    language: str = "python",     # Programming language
    context: Optional[str] = None,# Additional requirements
    include_tests: bool = False   # Generate tests too?
)
```

**Example:**
```python
result = await generate_code(
    task="Create a REST API endpoint for user authentication",
    language="python",
    include_tests=True
)
print(result["code"])
print(result["tests"])
```

### 2. `analyze_code`
```python
analyze_code(
    code: str,                              # Code to analyze
    language: str = "python",               # Language
    analysis_type: str = "comprehensive"    # Type of analysis
)
# analysis_type: "comprehensive", "security", "performance", "style"
```

**Returns:**
- Issues (with severity, type, line number, fixes)
- Metrics (complexity, maintainability score)
- Suggestions for improvement
- Positive aspects

### 3. `refactor_code`
```python
refactor_code(
    code: str,                    # Code to refactor
    language: str = "python",     # Language
    refactor_goal: str = "..."    # Optimization goal
)
```

**Returns:**
- Refactored code
- List of changes with reasoning
- Before/after metrics

### 4. `explain_code`
```python
explain_code(
    code: str,                         # Code to explain
    language: str = "python",          # Language
    detail_level: str = "medium"       # Detail level
)
# detail_level: "brief", "medium", "detailed"
```

### 5. `fix_code_errors`
```python
fix_code_errors(
    code: str,              # Broken code
    error_message: str,     # Error from execution
    language: str = "python"
)
```

**Returns:**
- Fixed code
- Issue identified
- Fix explanation
- Prevention tip

### 6. `read_code_file`
```python
read_code_file(file_path: str)
```

**Returns:**
- File content
- Detected language
- Lines, size, modification time
- Relative path

### 7. `write_code_file`
```python
write_code_file(
    file_path: str,
    content: str,
    create_dirs: bool = True,    # Create parent dirs
    backup: bool = True           # Backup existing file
)
```

### 8. `execute_code`
```python
execute_code(
    code: str,
    language: str = "python",
    timeout: int = 30  # seconds
)
```

**Returns:**
- Success status
- Exit code
- stdout/stderr
- Execution duration

### 9. `generate_tests`
```python
generate_tests(
    code: str,
    language: str = "python",
    test_framework: Optional[str] = None
)
# Auto-detects best framework: pytest, jest, junit, etc.
```

**Returns:**
- Test code
- Test cases (normal, edge, error)
- Setup instructions
- Dependencies

### 10. `get_code_completion`
```python
get_code_completion(
    partial_code: str,
    language: str = "python",
    cursor_position: Optional[int] = None
)
```

**Returns:** List of completion suggestions

### 11. `get_edit_history`
```python
get_edit_history(limit: int = 10)
```

**Returns:** Recent file operations with timestamps

## Supported Languages

| Language   | Extension | Code Gen | Execution | Tests    |
|------------|-----------|----------|-----------|----------|
| Python     | .py       | ✓        | ✓         | pytest   |
| JavaScript | .js       | ✓        | ✓         | jest     |
| TypeScript | .ts       | ✓        | ✗         | jest     |
| Go         | .go       | ✓        | ✗         | testing  |
| Rust       | .rs       | ✓        | ✗         | cargo    |
| Java       | .java     | ✓        | ✗         | junit    |
| C/C++      | .c/.cpp   | ✓        | ✗         | gtest    |
| Bash       | .sh       | ✓        | ✓         | bats     |
| SQL        | .sql      | ✓        | ✗         | N/A      |
| HTML/CSS   | .html/.css| ✓        | ✗         | N/A      |

## Usage with Ollama

The JARCORE uses your local Ollama instance. Make sure you have coding-capable models:

### Recommended Models

```bash
# Install recommended coding models
ollama pull deepseek-coder:6.7b    # Best for code generation
ollama pull codellama:13b          # Alternative option
ollama pull qwen2.5-coder:7b       # Fast & efficient
```

### Model Configuration

JRVS automatically uses your configured Ollama model in `config.py`:

```python
# config.py
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "deepseek-coder:6.7b"  # Use a coding model
```

You can switch models at runtime:
```python
await switch_ollama_model("codellama:13b")
```

## Integration with MCP

### MCP Client Configuration

Add to your MCP client settings:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "python3",
      "args": ["/home/xmanz/JRVS/mcp_gateway/server.py"],
      "env": {}
    }
  }
}
```

Then in your MCP client:
```
> Use JRVS to generate a Python function for binary search
> Analyze this code for security issues
> Refactor my spaghetti code to be more readable
```

### Python API

```python
from mcp_gateway.coding_agent import jarcore

# Generate code
result = await jarcore.generate_code(
    task="Create a LRU cache implementation",
    language="python",
    include_tests=True
)

# Analyze code
analysis = await jarcore.analyze_code(
    code=my_code,
    language="python",
    analysis_type="security"
)

# Fix errors
fixed = await jarcore.fix_code_errors(
    code=broken_code,
    error_message=error_output,
    language="python"
)
```

## Privacy & Security

✓ **100% Local**: All code analysis runs on your machine
✓ **No Cloud**: Never sends code to external APIs
✓ **Offline Capable**: Works without internet
✓ **Auto-Backup**: Files backed up before editing
✓ **Sandboxed Execution**: Code runs in isolated subprocess

## Performance Tips

1. **Use Specialized Models**: Coding models (DeepSeek-Coder, CodeLlama) work better than general models
2. **Provide Context**: Use the `context` parameter to give examples
3. **Leverage RAG**: Add project docs to knowledge base for better context
4. **Batch Operations**: Generate, analyze, test in sequence
5. **Cache Results**: JRVS caches embeddings and RAG context

## Workflow Examples

### Full Development Workflow

```python
# 1. Generate initial code
code_result = await generate_code(
    task="Create user authentication system",
    language="python",
    include_tests=False
)

# 2. Analyze for issues
analysis = await analyze_code(
    code=code_result["code"],
    language="python",
    analysis_type="comprehensive"
)

# 3. Refactor if needed
if analysis["metrics"]["maintainability"] < 7:
    refactored = await refactor_code(
        code=code_result["code"],
        language="python"
    )
    code_result["code"] = refactored["refactored_code"]

# 4. Generate tests
tests = await generate_tests(
    code=code_result["code"],
    language="python"
)

# 5. Write to files
await write_code_file("auth.py", code_result["code"])
await write_code_file("test_auth.py", tests["test_code"])

# 6. Execute tests
test_result = await execute_code(
    code=tests["test_code"],
    language="python",
    timeout=60
)
```

### Debug Workflow

```python
# 1. Read failing code
file_info = await read_code_file("my_script.py")

# 2. Run and capture error
exec_result = await execute_code(
    code=file_info["content"],
    language="python"
)

# 3. Auto-fix the error
if not exec_result["success"]:
    fixed = await fix_code_errors(
        code=file_info["content"],
        error_message=exec_result["stderr"],
        language="python"
    )

    # 4. Write fixed code
    await write_code_file("my_script.py", fixed["fixed_code"])
```

## Comparison with Nanocoder

| Feature              | Nanocoder        | JARVIS JARCORE |
|---------------------|------------------|---------------------|
| LLM Backend         | OpenAI API       | Local Ollama        |
| Privacy             | Cloud-based      | 100% Local          |
| Cost                | Pay per token    | Free (local)        |
| MCP Integration     | Limited          | Full MCP server     |
| RAG Context         | Basic            | Advanced vector DB  |
| Multi-language      | ✓                | ✓                   |
| Code Execution      | Limited          | Python/Bash/JS      |
| Test Generation     | ✓                | ✓                   |
| File Operations     | Basic            | Full CRUD + backup  |
| Calendar/Tasks      | ✗                | ✓ (via JRVS)        |

## Troubleshooting

### Ollama Not Responding
```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# Start Ollama
systemctl start ollama  # or: ollama serve
```

### Model Not Found
```bash
# List available models
ollama list

# Pull a coding model
ollama pull deepseek-coder:6.7b
```

### Import Errors
```bash
# Ensure dependencies installed
cd /home/xmanz/JRVS
pip install -r requirements.txt
```

### Slow Code Generation
- Use smaller models (7B instead of 13B+)
- Reduce context length
- Enable GPU acceleration if available

## Future Enhancements

- [ ] Multi-file project generation
- [ ] Git integration for code commits
- [ ] CI/CD pipeline generation
- [ ] Code review agent with suggestions
- [ ] Automatic documentation generation
- [ ] Code search across knowledge base
- [ ] Collaborative coding sessions
- [ ] Code metrics dashboard

## Contributing

See main JRVS documentation for contribution guidelines.

## License

Part of the JRVS project - see main LICENSE file.
