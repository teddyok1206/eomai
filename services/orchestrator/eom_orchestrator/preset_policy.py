"""Canonical executable-policy hash shared by lifecycle and validation use cases."""

from __future__ import annotations

from typing import Any

from eom_identifiers import content_sha256
from eom_workflow import ExecutionPresetRevision, ExecutionPresetRevisionV2
from pydantic import ValidationError as PydanticValidationError

from eom_orchestrator.control_service import ControlPlaneError


def execution_preset_policy_sha256(
    document: dict[str, Any] | ExecutionPresetRevision | ExecutionPresetRevisionV2,
) -> str:
    """Hash only executable policy, independent of revision lifecycle metadata."""

    try:
        if isinstance(document, (ExecutionPresetRevision, ExecutionPresetRevisionV2)):
            preset = document
        elif document.get("schema_version") == "execution-preset-revision/2.0":
            preset = ExecutionPresetRevisionV2.model_validate(document)
        else:
            preset = ExecutionPresetRevision.model_validate(document)
    except PydanticValidationError as exc:
        raise ControlPlaneError(
            "CONTROL_PRESET_DOCUMENT_INVALID", "preset policy document is invalid"
        ) from exc
    normalized = preset.model_dump(mode="json")
    policy = {
        "capacity_policy_revision_id": normalized["capacity_policy_revision_id"],
        "compatible_workflow_protocols": normalized["compatible_workflow_protocols"],
        "general_knowledge_policy": normalized["general_knowledge_policy"],
        "role_policies": normalized["role_policies"],
    }
    if isinstance(preset, ExecutionPresetRevisionV2):
        policy["retrieval_policy"] = normalized["retrieval_policy"]
    return content_sha256(policy)
