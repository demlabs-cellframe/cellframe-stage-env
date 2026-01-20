"""
Pydantic models for SLC Tasks.
Uses base classes and mixins for DRY principle.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.models.base import (
    BaseAPIModel,
    FilterParams,
    IdentifierMixin,
    TimestampMixin
)


class TaskStatus(str, Enum):
    """Task status enum. Centralized definition."""
    ACTIVE = "active"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskPriority(str, Enum):
    """Task priority enum. Centralized definition."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskMetadata(BaseAPIModel, IdentifierMixin, TimestampMixin):
    """
    Task metadata.
    Reuses IdentifierMixin and TimestampMixin for DRY.
    """
    
    task_id: str  # Aliased to 'id' from IdentifierMixin
    title: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    priority: TaskPriority
    status: TaskStatus
    estimated_complexity: Optional[str] = Field(
        default=None,
        description="Complexity estimate (e.g., 'low', 'medium', 'high')"
    )
    tags: List[str] = Field(default_factory=list, max_length=20)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "task_id": "example_task_20260119",
                "title": "Example Task",
                "category": "development",
                "priority": "HIGH",
                "status": "active",
                "created_at": "2026-01-19T15:00:00Z",
                "updated_at": "2026-01-19T15:00:00Z",
                "tags": ["example", "test"]
            }
        }
    }


class TaskDescription(BaseAPIModel):
    """Task description and goals."""
    
    summary: str = Field(..., min_length=1, max_length=1000)
    context: Optional[str] = Field(default=None, max_length=5000)
    goals: List[str] = Field(default_factory=list, max_length=50)
    constraints: List[str] = Field(default_factory=list, max_length=50)


class TaskPhase(BaseAPIModel):
    """Single task phase."""
    
    title: str = Field(..., min_length=1, max_length=200)
    status: TaskStatus
    priority: int = Field(..., ge=1, description="Phase priority order")
    tasks: List[str] = Field(default_factory=list, max_length=100)
    depends_on: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="List of phase IDs this phase depends on"
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        max_length=50,
        description="Criteria for phase completion"
    )


class ProgressEntry(BaseAPIModel, TimestampMixin):
    """
    Single progress log entry.
    Reuses TimestampMixin for DRY.
    """
    
    phase: Optional[str] = Field(default=None, description="Phase ID")
    status: TaskStatus
    summary: str = Field(..., min_length=1, max_length=500)
    details: Optional[str] = Field(default=None, max_length=5000)
    next_steps: Optional[str] = Field(default=None, max_length=2000)


class Task(BaseAPIModel):
    """
    Complete SLC Task model.
    Main domain entity.
    """
    
    metadata: TaskMetadata
    description: TaskDescription
    phases: Dict[str, TaskPhase] = Field(default_factory=dict)
    progress_tracking: Dict[str, Any] = Field(default_factory=dict)
    progress_log: List[ProgressEntry] = Field(default_factory=list)
    navigation_system: Optional[Dict[str, Any]] = Field(default=None)
    
    def add_progress_entry(
        self,
        status: TaskStatus,
        summary: str,
        phase: Optional[str] = None,
        details: Optional[str] = None,
        next_steps: Optional[str] = None
    ) -> None:
        """
        Add a progress log entry.
        Helper method for common operation (DRY).
        """
        entry = ProgressEntry(
            phase=phase,
            status=status,
            summary=summary,
            details=details,
            next_steps=next_steps
        )
        self.progress_log.append(entry)
        self.metadata.touch()  # Update timestamp
    
    def get_active_phases(self) -> List[tuple[str, TaskPhase]]:
        """Get list of active/in-progress phases."""
        return [
            (phase_id, phase)
            for phase_id, phase in self.phases.items()
            if phase.status in (TaskStatus.ACTIVE, TaskStatus.IN_PROGRESS)
        ]
    
    def get_completion_percentage(self) -> float:
        """Calculate task completion percentage based on phases."""
        if not self.phases:
            return 0.0
        
        completed = sum(
            1 for phase in self.phases.values()
            if phase.status == TaskStatus.COMPLETED
        )
        return (completed / len(self.phases)) * 100.0
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "metadata": {
                    "task_id": "example_task_20260119",
                    "title": "Example Task",
                    "category": "development",
                    "priority": "HIGH",
                    "status": "active",
                    "created_at": "2026-01-19T15:00:00Z",
                    "updated_at": "2026-01-19T15:00:00Z",
                    "tags": ["example"]
                },
                "description": {
                    "summary": "This is an example task",
                    "goals": ["Goal 1", "Goal 2"]
                },
                "phases": {},
                "progress_tracking": {},
                "progress_log": []
            }
        }
    }


# === Request/Response models ===

class TaskCreateRequest(BaseAPIModel):
    """Request model for creating a new task."""
    
    title: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    priority: TaskPriority = TaskPriority.MEDIUM
    summary: str = Field(..., min_length=1, max_length=1000)
    goals: List[str] = Field(default_factory=list, max_length=50)
    constraints: List[str] = Field(default_factory=list, max_length=50)
    tags: List[str] = Field(default_factory=list, max_length=20)


class TaskUpdateRequest(BaseAPIModel):
    """Request model for updating a task. All fields optional."""
    
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    summary: Optional[str] = Field(None, min_length=1, max_length=1000)
    goals: Optional[List[str]] = Field(None, max_length=50)
    constraints: Optional[List[str]] = Field(None, max_length=50)
    tags: Optional[List[str]] = Field(None, max_length=20)


class TaskFilterParams(FilterParams):
    """Filter parameters for task listing. Extends base FilterParams."""
    
    status: Optional[TaskStatus] = Field(default=None, description="Filter by status")
    priority: Optional[TaskPriority] = Field(default=None, description="Filter by priority")
    category: Optional[str] = Field(default=None, max_length=100, description="Filter by category")
    tags: Optional[List[str]] = Field(default=None, max_length=20, description="Filter by tags (OR)")


class TaskListItem(BaseAPIModel):
    """Lightweight task item for list views. Projection pattern."""
    
    task_id: str
    title: str
    category: str
    priority: TaskPriority
    status: TaskStatus
    tags: List[str]
    created_at: str
    updated_at: str
    completion_percentage: float = Field(ge=0.0, le=100.0)
    
    @classmethod
    def from_task(cls, task: Task) -> "TaskListItem":
        """Create list item from full task. Factory method."""
        return cls(
            task_id=task.metadata.task_id,
            title=task.metadata.title,
            category=task.metadata.category,
            priority=task.metadata.priority,
            status=task.metadata.status,
            tags=task.metadata.tags,
            created_at=task.metadata.created_at.isoformat(),
            updated_at=task.metadata.updated_at.isoformat(),
            completion_percentage=task.get_completion_percentage()
        )
