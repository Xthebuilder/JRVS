# CORTANA - Cognitive Layer for JRVS

Enterprise-grade modular AI system adding reflection, planning, and proactive intelligence.

## Architecture

```
cortana/
├── __init__.py           # Package exports
├── config.py             # Configuration & validation
├── data_models.py        # Data structures
├── resilience.py         # Circuit breakers, retries, timeouts
├── security.py           # Input sanitization
├── metrics.py            # Metrics collection
├── file_ops.py           # Safe file operations
├── memory_fusion.py      # Memory systems (ChromaDB + RAG)
├── reflection.py         # Self-evaluation engine
├── planning.py           # Hierarchical task planning
├── proactive.py          # Goal monitoring
├── health.py             # Health checks
├── assistant.py          # Main CortanaJRVS class
└── ui.py                 # Rich terminal UI
```

## Modules

### Core Infrastructure
- **config.py** - Configuration management with validation
- **resilience.py** - Fault tolerance (circuit breakers, retries)
- **security.py** - Input validation and sanitization
- **metrics.py** - Performance monitoring
- **file_ops.py** - Atomic file operations with backups

### Cognitive Systems
- **memory_fusion.py** - Episodic (ChromaDB) + Semantic (RAG) memory
- **reflection.py** - Self-evaluation and response improvement
- **planning.py** - Break goals into hierarchical tasks
- **proactive.py** - Background goal tracking with reminders

### Integration
- **health.py** - Component health monitoring
- **assistant.py** - Main orchestration class
- **ui.py** - Rich terminal interface

## Usage

```python
from cortana import CortanaJRVS
import asyncio

async def main():
    assistant = CortanaJRVS()
    await assistant.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## Entry Point

Use `cortana_jrvs.py` as the main entry point:

```bash
python cortana_jrvs.py
```

## Testing

```bash
python -m pytest cortana/tests/
```

## Version

**2.0.0** - Modular refactor from monolithic 1.0.0
