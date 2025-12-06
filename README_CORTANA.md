# CORTANA_JRVS - Hybrid AI Assistant

Enterprise-grade AI assistant combining JRVS's modular architecture with Cortana's cognitive capabilities.

## Two Versions Available

### Version 1.0 - Monolithic (READY TO USE ✅)

**File:** `cortana_jrvs.py` (2,371 lines)

**Status:** ✅ Fully functional, production-ready

**Use when:** You want a complete, working system immediately

```bash
python cortana_jrvs.py
```

**Features:**
- ✅ Self-reflection with quality scoring
- ✅ Hierarchical task planning
- ✅ Proactive goal monitoring
- ✅ Memory fusion (ChromaDB + RAG)
- ✅ Circuit breakers & resilience
- ✅ Security & input validation
- ✅ Metrics & health checks
- ✅ Rich terminal UI

**Limitations:**
- Single 2,371-line file
- Harder to maintain/extend
- Difficult to unit test individual components

### Version 2.0 - Modular (IN DEVELOPMENT 🔄)

**Directory:** `cortana/`
**Entry point:** `cortana_jrvs_v2.py`

**Status:** 🔄 Foundation complete, cognitive modules in progress

**Completed Modules:**
- ✅ `config.py` - Configuration & validation
- ✅ `resilience.py` - Circuit breakers, retries
- ✅ `security.py` - Input sanitization
- ✅ `metrics.py` - Performance monitoring
- ✅ `file_ops.py` - Safe file operations
- ✅ `data_models.py` - Data structures

**In Progress:**
- 🔄 `memory_fusion.py` - Memory systems
- 🔄 `reflection.py` - Self-evaluation
- 🔄 `planning.py` - Task planning
- 🔄 `proactive.py` - Goal monitoring
- 🔄 `health.py` - Health checks
- 🔄 `assistant.py` - Main orchestration

## Quick Start

### Using v1.0 (Recommended for now)

```bash
# Navigate to JRVS directory
cd ~/JRVS

# Run the monolithic version
python cortana_jrvs.py
```

### Using v2.0 (For development/testing)

```bash
# Once cognitive modules are complete
python cortana_jrvs_v2.py
```

## Architecture Comparison

### v1.0 Architecture
```
cortana_jrvs.py (2371 lines)
├── All code in one file
├── Hard to test individual components
└── Fast to deploy, slower to maintain
```

### v2.0 Architecture
```
cortana/
├── __init__.py
├── config.py (configuration)
├── resilience.py (fault tolerance)
├── security.py (input validation)
├── metrics.py (monitoring)
├── file_ops.py (safe I/O)
├── memory_fusion.py (memory systems)
├── reflection.py (self-evaluation)
├── planning.py (task planning)
├── proactive.py (goal tracking)
├── health.py (health checks)
├── assistant.py (main class)
└── ui.py (terminal UI)
```

## Enterprise Features (Both Versions)

### Resilience
- Circuit breaker pattern
- Retry logic with exponential backoff
- Timeout guards on all operations
- Graceful degradation

### Security
- Input sanitization
- Dangerous pattern detection
- Length limits
- Validation

### Observability
- Structured logging with correlation IDs
- Metrics collection (counters, timers, histograms)
- Health checks
- Performance monitoring

### Data Safety
- Atomic file writes
- Automatic backups
- Backup recovery
- Thread-safe operations

## Commands

Both versions support:

```
/help              - Show commands
/plan <goal>       - Create hierarchical plan
/execute <plan_id> - Execute plan
/goal <desc>       - Add trackable goal
/goals             - View goals
/reflect on|off    - Toggle self-reflection
/health            - System health check
/metrics           - Performance metrics
/status            - Quick overview
```

## Configuration

Edit `cortana/config.py` or modify `CONFIG` dict in `cortana_jrvs.py`

```python
CONFIG = {
    "models": {
        "primary": "jarvis",
        "reflection": "gemma3:12b"
    },
    "memory": {
        "chromadb_path": "./data/cortana_memory",
        "max_memories": 5
    },
    "reflection": {
        "enabled_by_default": False,
        "max_iterations": 2,
        "quality_threshold": 8
    },
    # ... more settings
}
```

## Migration Path

1. **Now:** Use v1.0 monolithic version (fully working)
2. **Soon:** v2.0 cognitive modules completed
3. **Then:** Test v2.0 thoroughly
4. **Finally:** Deprecate v1.0, use v2.0 as standard

## Development

### Running Tests (v2.0)

```bash
pytest cortana/tests/
```

### Adding Custom Modules (v2.0)

```python
# In cortana/custom_module.py
from .config import CONFIG
import logging

logger = logging.getLogger("CORTANA.custom")

class CustomFeature:
    def __init__(self):
        self.enabled = True

    async def do_something(self):
        logger.info("Custom feature running")
        # Your code here
```

## Roadmap

- [x] v1.0 monolithic implementation
- [x] v2.0 foundation modules
- [ ] v2.0 cognitive modules
- [ ] Comprehensive test suite
- [ ] Performance benchmarks
- [ ] Plugin system
- [ ] Web UI integration

## Support

- **Issues:** https://github.com/Xthebuilder/JRVS/issues
- **Discussions:** https://github.com/Xthebuilder/JRVS/discussions
- **Docs:** See `cortana/README.md`

## License

MIT - See LICENSE file

## Credits

- **JRVS:** VctOrtega & contributors
- **Cortana:** Original cognitive architecture
- **Integration:** JRVS Community
