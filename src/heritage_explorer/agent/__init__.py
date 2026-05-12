"""Agent orchestration package for the heritage RAG system."""

from ..agent_models import (  # noqa: F401 - re-export
    AgentDecision,
    AgentResult,
    TaskConfig,
    TaskResult,
    TaskType,
    task_type_from_str,
    task_type_label,
)
from ..agent_task_config import TASK_CONFIGS, _TASK_CONFIGS  # noqa: F401

# These will be imported once their modules are created in later tasks.
# For now, keep them as delayed imports or placeholders.
# The existing agent.py in the parent directory will handle these imports.

__all__ = [
    "Agent",
    "AgentDecision",
    "AgentResult",
    "IntentRouter",
    "TaskConfig",
    "TaskResult",
    "TaskType",
    "TASK_CONFIGS",
    "_TASK_CONFIGS",
    "task_type_from_str",
    "task_type_label",
]
