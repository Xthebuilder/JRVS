"""
Configuration and validation for CORTANA_JRVS
"""

from pathlib import Path
from typing import Dict, List, Tuple, Any
from enum import Enum


class ComponentStatus(Enum):
    """Component health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanStatus(Enum):
    """Plan execution status"""
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Default configuration
DEFAULT_CONFIG = {
    "models": {
        "primary": "jarvis",
        "reflection": "gemma3:12b",
        "fallback": "llama3:8b"
    },
    "memory": {
        "chromadb_path": "./data/cortana_memory",
        "embedding_model": "all-MiniLM-L6-v2",
        "relevance_threshold": 0.35,
        "max_memories": 5,
        "cache_size": 1000
    },
    "reflection": {
        "enabled_by_default": False,
        "max_iterations": 2,
        "quality_threshold": 8,
        "timeout": 60
    },
    "proactive": {
        "check_interval": 300,
        "goal_reminder_days": 3,
        "deadline_warning_days": 7,
        "enabled_by_default": True
    },
    "planning": {
        "max_tasks_per_plan": 10,
        "auto_save": True,
        "backup_on_save": True
    },
    "ui": {
        "theme": "cyberpunk",
        "show_thinking": True,
        "emoji_indicators": True,
        "markdown_output": True
    },
    "data": {
        "plans_file": "./data/cortana_plans.json",
        "goals_file": "./data/cortana_goals.json",
        "log_file": "./logs/cortana.log",
        "metrics_file": "./logs/cortana_metrics.json"
    },
    "resilience": {
        "timeouts": {
            "llm_call": 300,
            "embedding": 30,
            "memory_search": 10,
            "mcp_call": 60,
            "rag_retrieval": 30
        },
        "retries": {
            "llm_call": 2,
            "embedding": 3,
            "memory_search": 2,
            "file_operation": 3
        },
        "circuit_breaker": {
            "failure_threshold": 5,
            "recovery_timeout": 60
        }
    },
    "security": {
        "max_input_length": 10000,
        "max_output_length": 50000,
        "dangerous_patterns": [
            r'rm\s+-rf',
            r'eval\(',
            r'exec\(',
            r'__import__',
            r'os\.system',
            r'subprocess\.'
        ],
        "sanitize_inputs": True
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s",
        "file_level": "DEBUG",
        "console_level": "INFO",
        "max_bytes": 10485760,
        "backup_count": 5
    }
}

CONFIG = DEFAULT_CONFIG.copy()


def validate_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate configuration structure and values

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    # Check required sections
    required_sections = [
        "models", "memory", "reflection", "proactive",
        "planning", "ui", "data", "resilience", "security", "logging"
    ]
    for section in required_sections:
        if section not in config:
            errors.append(f"Missing required config section: {section}")

    # Validate timeouts are positive
    if "resilience" in config and "timeouts" in config["resilience"]:
        for key, value in config["resilience"]["timeouts"].items():
            if not isinstance(value, (int, float)) or value <= 0:
                errors.append(f"Invalid timeout value for {key}: {value}")

    # Validate retry counts
    if "resilience" in config and "retries" in config["resilience"]:
        for key, value in config["resilience"]["retries"].items():
            if not isinstance(value, int) or value < 0:
                errors.append(f"Invalid retry count for {key}: {value}")

    # Validate paths can be created
    if "data" in config:
        for key in ["plans_file", "goals_file", "log_file", "metrics_file"]:
            if key in config["data"]:
                path = Path(config["data"][key])
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    errors.append(f"Cannot create directory for {key}: {e}")

    # Validate memory settings
    if "memory" in config:
        if "cache_size" in config["memory"]:
            if not isinstance(config["memory"]["cache_size"], int) or config["memory"]["cache_size"] < 0:
                errors.append("cache_size must be a positive integer")
        if "max_memories" in config["memory"]:
            if not isinstance(config["memory"]["max_memories"], int) or config["memory"]["max_memories"] < 1:
                errors.append("max_memories must be a positive integer")

    # Validate reflection settings
    if "reflection" in config:
        if "max_iterations" in config["reflection"]:
            if not isinstance(config["reflection"]["max_iterations"], int) or config["reflection"]["max_iterations"] < 1:
                errors.append("reflection max_iterations must be >= 1")
        if "quality_threshold" in config["reflection"]:
            threshold = config["reflection"]["quality_threshold"]
            if not isinstance(threshold, int) or threshold < 1 or threshold > 10:
                errors.append("reflection quality_threshold must be between 1-10")

    return (len(errors) == 0, errors)


def get_config() -> Dict[str, Any]:
    """Get the current configuration"""
    return CONFIG.copy()


def update_config(updates: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Update configuration with validation

    Args:
        updates: Dictionary of configuration updates

    Returns:
        Tuple of (success, list_of_errors)
    """
    global CONFIG

    # Deep merge updates into config
    new_config = CONFIG.copy()

    def deep_merge(base: dict, updates: dict):
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                deep_merge(base[key], value)
            else:
                base[key] = value

    deep_merge(new_config, updates)

    # Validate new config
    valid, errors = validate_config(new_config)

    if valid:
        CONFIG = new_config
        return (True, [])
    else:
        return (False, errors)
