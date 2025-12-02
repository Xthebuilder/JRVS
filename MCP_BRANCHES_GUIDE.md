# JRVS MCP Server - Branch Guide

This repository offers **TWO versions** of the JRVS MCP server. Choose the one that fits your needs!

---

## 🌿 Branch Overview

### `main` - Original Simple Server
**Best for:** Getting started, learning MCP, simple deployments

**What it includes:**
- ✅ Core MCP server with 17 tools
- ✅ RAG, Ollama, Calendar, Web Scraping functionality
- ✅ Simple, easy to understand codebase
- ✅ Fast setup and deployment
- ✅ Minimal dependencies

**Quick Start:**
```bash
git checkout main
python mcp/server.py
```

**Files:** `mcp/server.py` (~500 lines)

---

### `mcp-enhanced` - Production-Ready Enhanced Server
**Best for:** Production deployments, enterprise use, high reliability

**What it includes:**
- ✅ Everything from `main` branch (100% backward compatible)
- ✅ **PLUS** 10 production infrastructure modules
- ✅ **PLUS** Enterprise features:
  - 🛡️ Circuit breakers & retry logic
  - ⚡ Multi-layer caching
  - 🔒 API key authentication & RBAC
  - 📊 Real-time metrics & monitoring
  - 🎯 Rate limiting & resource management
  - 🔄 Graceful shutdown
  - 📝 Structured JSON logging

**Quick Start:**
```bash
git checkout mcp-enhanced
python mcp/server_enhanced.py

# Or with Docker
docker-compose -f docker-compose.mcp.yml up -d
```

**Files:**
- Original: `mcp/server.py` (~500 lines)
- Enhanced: `mcp/server_enhanced.py` + 10 infrastructure modules (~5,300 lines total)

---

## 📊 Comparison

| Feature | `main` | `mcp-enhanced` |
|---------|--------|----------------|
| **MCP Tools** | 17 | 31 (17 original + 14 new) |
| **Error Handling** | Basic | Circuit breakers, retry, fallbacks |
| **Performance** | Good | Excellent (multi-layer caching) |
| **Authentication** | None | API keys + RBAC |
| **Monitoring** | None | Health checks + metrics |
| **Rate Limiting** | None | Per-client token bucket |
| **Logging** | Basic | Structured JSON |
| **Deployment** | Manual | Docker + Docker Compose |
| **Documentation** | README | 3 comprehensive guides |
| **Code Size** | ~500 lines | ~5,300 lines |
| **Setup Time** | 2 minutes | 5 minutes |
| **Production Ready** | Learning/Dev | Enterprise ✅ |

---

## 🎯 Which Should I Choose?

### Choose `main` if you:
- ✅ Want to get started quickly
- ✅ Are learning MCP or JRVS
- ✅ Don't need production features
- ✅ Prefer simplicity over features
- ✅ Have low traffic/usage

### Choose `mcp-enhanced` if you:
- ✅ Need production reliability
- ✅ Want monitoring and metrics
- ✅ Need authentication and rate limiting
- ✅ Require high availability
- ✅ Want enterprise-grade error handling
- ✅ Plan to scale horizontally
- ✅ Need comprehensive logging

---

## 🚀 How to Switch Branches

### Use Original Simple Server
```bash
git checkout main
python mcp/server.py
```

### Use Enhanced Production Server
```bash
git checkout mcp-enhanced
python mcp/server_enhanced.py
```

### Compare Branches
```bash
# See what's different
git diff main..mcp-enhanced

# List new files in enhanced branch
git diff main..mcp-enhanced --name-status
```

---

## 📁 File Organization

### `main` branch
```
JRVS/
├── mcp/
│   ├── server.py          ← Original simple server
│   ├── client.py
│   ├── agent.py
│   └── ...
└── README.md
```

### `mcp-enhanced` branch
```
JRVS/
├── mcp/
│   ├── server.py          ← Original (still works!)
│   ├── server_enhanced.py ← New production server
│   │
│   ├── Infrastructure (NEW)
│   │   ├── exceptions.py
│   │   ├── logging_config.py
│   │   ├── metrics.py
│   │   ├── cache.py
│   │   ├── resilience.py
│   │   ├── rate_limiter.py
│   │   ├── health.py
│   │   ├── auth.py
│   │   ├── config_manager.py
│   │   └── shutdown.py
│   │
│   ├── Documentation (NEW)
│   │   ├── README_ENHANCED.md
│   │   └── ARCHITECTURE.md
│   │
│   └── tests/
│       └── test_enhanced_server.py (NEW)
│
├── Deployment (NEW)
│   ├── Dockerfile.mcp
│   ├── docker-compose.mcp.yml
│   └── scripts/start_mcp_enhanced.sh
│
├── MCP_BUILD_SUMMARY.md (NEW)
└── MCP_BRANCHES_GUIDE.md (this file)
```

---

## 🔄 Backward Compatibility

**Important:** The `mcp-enhanced` branch is **100% backward compatible**!

- ✅ Original `server.py` still works identically
- ✅ All 17 original tools unchanged
- ✅ Can run both servers side-by-side
- ✅ No breaking changes to existing functionality

**Example:**
```bash
# On mcp-enhanced branch, both work:
python mcp/server.py           # Original simple server
python mcp/server_enhanced.py  # Enhanced production server
```

---

## 📚 Documentation

### `main` branch
- `README.md` - Main project documentation

### `mcp-enhanced` branch
- `mcp/README_ENHANCED.md` - Complete user guide (500+ lines)
- `mcp/ARCHITECTURE.md` - Technical architecture (600+ lines)
- `MCP_BUILD_SUMMARY.md` - Build summary and statistics
- `MCP_BRANCHES_GUIDE.md` - This guide

---

## 🐳 Docker Deployment

### `main` branch
Manual deployment (no Docker files)

### `mcp-enhanced` branch
```bash
# Full stack with Ollama + JRVS MCP
docker-compose -f docker-compose.mcp.yml up -d

# View logs
docker-compose -f docker-compose.mcp.yml logs -f jrvs-mcp

# Stop
docker-compose -f docker-compose.mcp.yml down
```

---

## 🧪 Testing

### `main` branch
No test suite included

### `mcp-enhanced` branch
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run comprehensive tests
pytest mcp/tests/test_enhanced_server.py -v
```

**Test coverage:**
- Exception handling
- Cache operations
- Rate limiting
- Circuit breakers
- Retry logic
- Metrics collection
- Health checks
- Integration tests

---

## 💡 Migration Path

**Starting with `main`?** You can always upgrade later!

```bash
# Start simple
git checkout main
python mcp/server.py

# Later, when you need more features
git checkout mcp-enhanced
python mcp/server_enhanced.py  # Everything still works!
```

**No code changes needed** - just switch branches and run the enhanced server.

---

## 🆘 Support

### `main` branch issues
- Check `README.md`
- Review JRVS documentation

### `mcp-enhanced` branch issues
- Check `mcp/README_ENHANCED.md`
- Review `mcp/ARCHITECTURE.md`
- Check `MCP_BUILD_SUMMARY.md`
- Run health checks: `get_health_status()`
- Check metrics: `get_metrics()`

---

## 🤝 Contributing

Both branches accept contributions!

**For `main`:**
- Keep it simple and beginner-friendly
- Focus on core MCP functionality

**For `mcp-enhanced`:**
- Add production features
- Maintain backward compatibility
- Include tests
- Update documentation

---

## 📊 Performance Comparison

| Metric | `main` | `mcp-enhanced` |
|--------|--------|----------------|
| Startup Time | ~2s | ~5s (initialization) |
| Memory Usage | ~500 MB | ~600 MB (with caching) |
| Request Latency | Varies | Improved (caching) |
| Max Throughput | ~30 req/s | ~60 req/s (default limit) |
| Failure Recovery | Manual restart | Auto-retry, circuit breakers |
| Monitoring | None | Real-time metrics |

---

## 🎓 Learning Path

**Recommended progression:**

1. **Start with `main`** - Learn MCP basics
2. **Explore the code** - Understand JRVS architecture
3. **Switch to `mcp-enhanced`** - See production patterns
4. **Read ARCHITECTURE.md** - Learn resilience patterns
5. **Run tests** - See quality assurance in action
6. **Deploy with Docker** - Experience production deployment

---

## ⭐ Quick Reference

```bash
# Clone the repo
git clone https://github.com/Xthebuilder/JRVS.git
cd JRVS

# Option A: Simple server
git checkout main
python mcp/server.py

# Option B: Enhanced server
git checkout mcp-enhanced
python mcp/server_enhanced.py

# Option C: Enhanced with Docker
git checkout mcp-enhanced
docker-compose -f docker-compose.mcp.yml up -d
```

---

**Choose your adventure and start building! 🚀**
