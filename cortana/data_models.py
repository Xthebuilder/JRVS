"""
Data models and structures
"""

from dataclasses import dataclass, field
from typing import List, Optional
from .config import TaskStatus, PlanStatus


@dataclass
class Task:
    """Represents a task in a plan"""
    id: str
    description: str
    status: TaskStatus
    created_at: str
    dependencies: List[str] = field(default_factory=list)
    result: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0


@dataclass
class Plan:
    """Represents a hierarchical plan"""
    id: str
    goal: str
    status: PlanStatus
    created_at: str
    tasks: List[Task] = field(default_factory=list)
    completed_at: Optional[str] = None
    reflection_score: Optional[int] = None
    error: Optional[str] = None


@dataclass
class Goal:
    """Represents a user goal"""
    id: str
    description: str
    created_at: str
    progress: float = 0.0
    deadline: Optional[str] = None
    last_worked_on: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    plan_id: Optional[str] = None
    archived: bool = False
