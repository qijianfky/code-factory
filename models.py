"""Data models for code factory."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class TaskStatus(enum.Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    REVIEWING = "reviewing"
    MERGED = "merged"
    FAILED = "failed"


class ModuleStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"


class AgentType(enum.Enum):
    CLAUDE = "claude"
    CODEX = "codex"


class TaskKind(enum.Enum):
    NORMAL = "normal"
    SCOPE_CHECK = "scope_check"  # judges out-of-scope files, no code change
    OWNER_HANDOFF = "owner_handoff"  # shared-file follow-up before retrying original lane
    RERUN = "rerun"              # retry with adjusted scope


class FailureKind(enum.Enum):
    NONE = "none"
    RETRYABLE = "retryable"
    SCOPE_VIOLATION = "scope_violation"
    OWNER_HANDOFF_REQUIRED = "owner_handoff_required"
    PLANNING_FAILED = "planning_failed"
    REVIEW_REJECTED = "review_rejected"
    MERGE_CONFLICT = "merge_conflict"
    QUICK_CHECK_FAILED = "quick_check_failed"
    SCOPE_CHECK_FAILED = "scope_check_failed"
    DEADLOCK = "deadlock"


MAX_SCOPE_ROUNDS = 2  # 3rd violation = planning_failed


@dataclass
class Task:
    id: str
    title: str
    description: str
    module_id: str = ""
    files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    agent_type: AgentType = AgentType.CLAUDE
    kind: TaskKind = TaskKind.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    branch: str = ""
    worktree: str = ""
    retries: int = 0
    max_retries: int = 3
    review_feedback: str = ""
    error: str = ""
    failure_kind: FailureKind = FailureKind.NONE
    # Scope resolution fields
    parent_task_id: str = ""       # original task that triggered scope check
    discovered_files: list[str] = field(default_factory=list)  # out-of-scope files
    scope_round: int = 0           # how many scope validations so far
    owner_lane: str = ""           # lane that owns the shared follow-up


@dataclass
class Module:
    id: str
    name: str
    phase: int  # 0 = foundation, 1+ = business modules
    owned_paths: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    status: ModuleStatus = ModuleStatus.PENDING
    e2e_issues: list[str] = field(default_factory=list)
