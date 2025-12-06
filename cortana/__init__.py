"""
CORTANA - Enterprise Cognitive Layer for JRVS
==============================================

Modular cognitive AI system adding reflection, planning, and proactive
intelligence to JRVS's RAG/MCP architecture.

Version: 2.0.0
License: MIT
"""

__version__ = "2.0.0"
__author__ = "JRVS Community"
__license__ = "MIT"

from .config import CONFIG, validate_config, ComponentStatus, TaskStatus, PlanStatus

# Import available modules (assistant and cognitive modules coming soon)
# from .assistant import CortanaJRVS
# from .memory_fusion import MemoryFusion
# from .reflection import ReflectionEngine
# from .planning import PlanningEngine
# from .proactive import ProactiveMonitor

__all__ = [
    # "CortanaJRVS",  # TODO: Implement
    "CONFIG",
    "validate_config",
    "ComponentStatus",
    "TaskStatus",
    "PlanStatus",
    # "MemoryFusion",  # TODO: Implement
    # "ReflectionEngine",  # TODO: Implement
    # "PlanningEngine",  # TODO: Implement
    # "ProactiveMonitor",  # TODO: Implement
]
