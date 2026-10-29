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
    WorkflowAdmission("generic-item-development", "1.9.0", "workflow-role/1.19.0"),
    WorkflowAdmission("generic-item-development", "1.10.0", "workflow-role/1.20.0"),
    WorkflowAdmission("generic-item-development", "1.11.0", "workflow-role/1.23.0"),
    WorkflowAdmission("generic-item-development", "1.12.0", "workflow-role/1.23.0"),
    WorkflowAdmission("generic-item-development", "1.13.0", "workflow-role/1.24.0"),
    WorkflowAdmission("generic-item-development", "1.14.0", "workflow-role/1.24.0"),
    WorkflowAdmission("generic-item-development", "1.15.0", "workflow-role/1.24.0"),
    WorkflowAdmission("generic-item-development", "1.16.0", "workflow-role/1.24.0"),
    WorkflowAdmission("knowledge-analysis", "1.0.0", "workflow-role/1.4.0"),
    WorkflowAdmission("knowledge-analysis", "4.0.0", "workflow-role/1.7.0"),
    WorkflowAdmission("knowledge-analysis", "8.0.0", "workflow-role/1.11.0"),
    WorkflowAdmission("knowledge-analysis", "9.0.0", "workflow-role/1.18.0"),
    WorkflowAdmission("knowledge-analysis", "10.0.0", "workflow-role/1.21.0"),
    WorkflowAdmission("customer-support", "1.0.0", "workflow-role/1.22.0"),
    WorkflowAdmission("pdf-document-review", "1.0.0", "workflow-role/1.25.0"),
    WorkflowAdmission("pdf-document-review", "1.1.0", "workflow-role/1.26.0"),
    WorkflowAdmission("pdf-document-review", "1.2.0", "workflow-role/1.27.0"),
    WorkflowAdmission("pdf-document-review", "1.3.0", "workflow-role/1.28.0"),
    WorkflowAdmission("pdf-document-review", "1.4.0", "workflow-role/1.31.0"),
    WorkflowAdmission("pdf-document-review", "1.5.0", "workflow-role/1.32.0"),
    WorkflowAdmission("item-inference-transfer-comparison", "1.0.0", "workflow-role/1.29.0"),
    WorkflowAdmission("item-inference-transfer-comparison", "1.1.0", "workflow-role/1.30.0"),
    # Historical column name is not a Codex role or native execution grant.
    WorkflowAdmission("local-embedding-index", "1.0.0", "local-embedding/1.0"),
    WorkflowAdmission("local-embedding-index", "2.0.0", "local-embedding/1.0"),
    WorkflowAdmission("local-embedding-reference-query", "1.0.0", "reference-query/1.0"),
    WorkflowAdmission("local-embedding-private-chat-query", "1.0.0", "private-chat-query/1.0"),
    WorkflowAdmission("legacy-item-extraction", "1.0.0", "workflow-role/1.14.0"),
    WorkflowAdmission("external-item-learning", "1.0.0", "workflow-role/1.33.0"),
    WorkflowAdmission("external-item-learning", "2.0.0", "workflow-role/1.34.0"),
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
