"""Explicit material/task transitions, independent of persistence and adapters."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType


class MaterialLearningState(StrEnum):
    RECEIVED = "RECEIVED"
    PREPARING = "PREPARING"
    DISCOVERING = "DISCOVERING"
    PROCESSING = "PROCESSING"
    WAITING_FOR_CAPACITY = "WAITING_FOR_CAPACITY"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_EXCEPTIONS = "COMPLETED_WITH_EXCEPTIONS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MaterialTaskState(StrEnum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    READY = "READY"
    RUNNING = "RUNNING"
    RESULT_READY = "RESULT_READY"
    REGISTERED = "REGISTERED"
    ANALYZING = "ANALYZING"
    PUBLISHING = "PUBLISHING"
    GRAPH_READY = "GRAPH_READY"
    COMPLETED = "COMPLETED"
    EXCEPTION = "EXCEPTION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MaterialTaskKind(StrEnum):
    PREPARE = "PREPARE"
    DISCOVER = "DISCOVER"
    EXPLANATION = "EXPLANATION"
    QUESTION = "QUESTION"


_M = MaterialLearningState
MATERIAL_TRANSITIONS = MappingProxyType(
    {
        _M.RECEIVED: frozenset({_M.PREPARING, _M.CANCELLED}),
        _M.PREPARING: frozenset({_M.DISCOVERING, _M.FAILED, _M.CANCELLED}),
        _M.DISCOVERING: frozenset(
            {_M.PROCESSING, _M.WAITING_FOR_CAPACITY, _M.PAUSED, _M.FAILED, _M.CANCELLED}
        ),
        _M.PROCESSING: frozenset(
            {
                _M.WAITING_FOR_CAPACITY,
                _M.PAUSED,
                _M.COMPLETED,
                _M.COMPLETED_WITH_EXCEPTIONS,
                _M.FAILED,
                _M.CANCELLED,
            }
        ),
        _M.WAITING_FOR_CAPACITY: frozenset(
            {_M.DISCOVERING, _M.PROCESSING, _M.PAUSED, _M.CANCELLED}
        ),
        _M.PAUSED: frozenset({_M.DISCOVERING, _M.PROCESSING, _M.CANCELLED}),
        _M.COMPLETED: frozenset(),
        _M.COMPLETED_WITH_EXCEPTIONS: frozenset(),
        _M.FAILED: frozenset(),
        _M.CANCELLED: frozenset(),
    }
)

_T = MaterialTaskState
TASK_TRANSITIONS = MappingProxyType(
    {
        _T.PENDING: frozenset({_T.PREPARING, _T.EXCEPTION, _T.CANCELLED}),
        _T.PREPARING: frozenset({_T.READY, _T.EXCEPTION, _T.FAILED, _T.CANCELLED}),
        _T.READY: frozenset({_T.RUNNING, _T.EXCEPTION, _T.FAILED, _T.CANCELLED}),
        _T.RUNNING: frozenset({_T.RESULT_READY, _T.EXCEPTION, _T.FAILED, _T.CANCELLED}),
        _T.RESULT_READY: frozenset({_T.REGISTERED, _T.COMPLETED, _T.EXCEPTION, _T.FAILED}),
        _T.REGISTERED: frozenset({_T.ANALYZING, _T.EXCEPTION, _T.FAILED}),
        _T.ANALYZING: frozenset({_T.PUBLISHING, _T.EXCEPTION, _T.FAILED}),
        _T.PUBLISHING: frozenset({_T.GRAPH_READY, _T.EXCEPTION, _T.FAILED}),
        _T.GRAPH_READY: frozenset({_T.COMPLETED}),
        _T.COMPLETED: frozenset(),
        _T.EXCEPTION: frozenset(),
        _T.FAILED: frozenset(),
        _T.CANCELLED: frozenset(),
    }
)


# Conversion/rendering is durable CPU work, never a disguised Codex job.
PREPARATION_TASK_TRANSITIONS = MappingProxyType(
    {
        _T.PENDING: frozenset({_T.PREPARING, _T.EXCEPTION, _T.CANCELLED}),
        _T.PREPARING: frozenset({_T.RESULT_READY, _T.EXCEPTION, _T.FAILED, _T.CANCELLED}),
        _T.RESULT_READY: frozenset({_T.COMPLETED, _T.EXCEPTION, _T.FAILED}),
    }
)

KNOWLEDGE_TASK_TRANSITIONS = MappingProxyType(
    {
        _T.PENDING: frozenset({_T.PREPARING, _T.EXCEPTION, _T.CANCELLED}),
        _T.PREPARING: frozenset({_T.READY, _T.EXCEPTION, _T.FAILED, _T.CANCELLED}),
        _T.READY: frozenset({_T.ANALYZING, _T.EXCEPTION, _T.FAILED, _T.CANCELLED}),
        _T.ANALYZING: frozenset({_T.PUBLISHING, _T.EXCEPTION, _T.FAILED}),
        _T.PUBLISHING: frozenset({_T.GRAPH_READY, _T.EXCEPTION, _T.FAILED}),
        _T.GRAPH_READY: frozenset({_T.COMPLETED}),
    }
)


def require_material_transition(
    current: MaterialLearningState, target: MaterialLearningState
) -> None:
    if target not in MATERIAL_TRANSITIONS[current]:
        raise ValueError("MATERIAL_LEARNING_TRANSITION_INVALID")


def require_material_task_transition(
    current: MaterialTaskState, target: MaterialTaskState, *, kind: MaterialTaskKind | None = None
) -> None:
    specialized = {
        MaterialTaskKind.PREPARE: PREPARATION_TASK_TRANSITIONS,
        MaterialTaskKind.EXPLANATION: KNOWLEDGE_TASK_TRANSITIONS,
    }
    transitions = specialized.get(kind, TASK_TRANSITIONS) if kind is not None else TASK_TRANSITIONS
    if target not in transitions.get(current, frozenset()):
        raise ValueError("MATERIAL_LEARNING_TASK_TRANSITION_INVALID")
