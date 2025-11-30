# JARCORE Quick Start

**JARCORE** = **J**ARVIS **A**utonomous **R**easoning & **C**oding **E**ngine

## 🚀 Quick Start

### 1. Make sure Ollama is running

```bash
# Check Ollama
curl http://localhost:11434/api/tags

# Install a coding model if needed
ollama pull deepseek-coder:6.7b
```

### 2. Run the Demo

```bash
cd /home/xmanz/JRVS
python3 demo_jarcore.py
```

The demo shows all 8 JARCORE capabilities:
- ✓ Code Generation
- ✓ Code Analysis
- ✓ Code Refactoring
- ✓ Test Generation
- ✓ Code Execution
- ✓ Error Fixing
- ✓ File Operations
- ✓ Code Explanation

### 3. Use the CLI

```bash
# Generate code
python3 jarcore_cli.py generate "create a binary search function" -l python -o search.py

# Analyze code for security issues
python3 jarcore_cli.py analyze myfile.py --type security

# Fix code errors
python3 jarcore_cli.py fix broken.py "NameError: name 'x' is not defined" --write

# Generate tests
python3 jarcore_cli.py test mycode.py -o test_mycode.py

# Explain code
python3 jarcore_cli.py explain complex.py --detail detailed

# Refactor code
python3 jarcore_cli.py refactor messy.py --write

# Run code
python3 jarcore_cli.py run script.py
```

### 4. Use via MCP

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "jrvs": {
      "command": "python3",
      "args": ["/home/xmanz/JRVS/mcp_gateway/server.py"]
    }
  }
}
```

Then in your MCP client:
```
> Use JARCORE to create a REST API for user authentication
> Analyze this code for security issues
> Fix the error in my Python script
```

### 5. Use in Python

```python
import asyncio
from mcp_gateway.coding_agent import jarcore

async def main():
    # Generate code
    result = await jarcore.generate_code(
        task="Create a function to validate email addresses",
        language="python"
    )
    print(result["code"])

    # Analyze it
    analysis = await jarcore.analyze_code(
        code=result["code"],
        language="python",
        analysis_type="security"
    )
    print(analysis)

asyncio.run(main())
```

## 🎯 Common Tasks

### Generate a complete module
```bash
python3 jarcore_cli.py generate "Create a user authentication system with password hashing" \
  --language python \
  --tests \
  --output auth.py
```

### Debug and fix code
```bash
# Run code and capture error
python3 mycode.py 2> error.txt

# Fix it
python3 jarcore_cli.py fix mycode.py "$(cat error.txt)" --write
```

### Complete workflow
```bash
# 1. Generate
python3 jarcore_cli.py generate "REST API for TODO items" -l python -o api.py

# 2. Analyze
python3 jarcore_cli.py analyze api.py --type comprehensive

# 3. Refactor if needed
python3 jarcore_cli.py refactor api.py --write

# 4. Generate tests
python3 jarcore_cli.py test api.py -o test_api.py

# 5. Run tests
python3 jarcore_cli.py run test_api.py
```

## 📚 Documentation

Full documentation: `docs/CODING_AGENT.md`

## 🔧 Troubleshooting

**Ollama not responding:**
```bash
systemctl status ollama
# or
ollama serve
```

**Import errors:**
```bash
cd /home/xmanz/JRVS
pip install -r requirements.txt
pip install rich  # For CLI colors
```

**Slow generation:**
- Use smaller models (7B instead of 13B+)
- Check `config.py` for model settings

## 🌟 Features

- **100% Local** - All code runs on your machine
- **Multi-Language** - Python, JS, Go, Rust, Java, C/C++, Bash
- **Context-Aware** - Uses RAG for project understanding
- **Safe Execution** - Sandboxed with timeout protection
- **Auto-Backup** - Files backed up before editing
- **Test Generation** - Automatic unit test creation
- **Error Fixing** - AI-powered debugging
- **Code Analysis** - Security, performance, style checks

## 🎓 Examples

See `demo_jarcore.py` for comprehensive examples of all features.

---

**JARCORE** - AI-Powered Coding with Local Ollama Models
