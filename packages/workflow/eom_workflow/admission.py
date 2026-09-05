"""Authoritative admission policy for new workflow instances.

Historical definitions remain valid immutable snapshots. This module answers a
different question: which exact definition/protocol pairs may accept new work.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class WorkflowAdmission:
    definition_key: str
    definition_version: str
    role_protocol_version: str


_ADMISSIONS = (
    WorkflowAdmission("generic-item-development", "1.8.0", "workflow-role/1.17.0"),
    WorkflowAdmission("knowledge-analysis", "1.0.0", "workflow-role/1.4.0"),
    WorkflowAdmission("knowledge-analysis", "4.0.0", "workflow-role/1.7.0"),
    WorkflowAdmission("knowledge-analysis", "8.0.0", "workflow-role/1.11.0"),
    WorkflowAdmission("legacy-item-extraction", "1.0.0", "workflow-role/1.14.0"),
    WorkflowAdmission(
        "legacy-item-editorial-compatibility",
        "1.0.0",
        "workflow-role/1.16.0",
    ),
)

WORKFLOW_ADMISSION_BY_IDENTITY: Final = MappingProxyType(
    {(value.definition_key, value.definition_version): value for value in _ADMISSIONS}
)
MANAGED_WORKFLOW_DEFINITION_KEYS: Final = frozenset(value.definition_key for value in _ADMISSIONS)


def workflow_admission(
    definition_key: str,
    definition_version: str,
) -> WorkflowAdmission | None:
    """Return the O(1) admission rule for an exact immutable definition identity."""

    return WORKFLOW_ADMISSION_BY_IDENTITY.get((definition_key, definition_version))


def workflow_definition_is_admitted(definition_key: str, definition_version: str) -> bool:
    return workflow_admission(definition_key, definition_version) is not None
