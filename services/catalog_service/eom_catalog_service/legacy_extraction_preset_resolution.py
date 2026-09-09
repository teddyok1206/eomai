"""Exact pointer resolution for legacy extraction preset recovery."""

from __future__ import annotations

from eom_catalog_contracts import LegacyExtractionPresetPointer
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    resolve_control_artifact_pointer,
)
from eom_orchestrator.models import ProtocolVersionRecord
from eom_orchestrator.preset_lifecycle import execution_preset_policy_sha256
from eom_workflow import ExecutionPresetRevision, InstructionBundleManifest
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import WorkflowDefinitionRecord
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session


class LegacyExtractionPresetResolutionError(RuntimeError):
    """Stable content-free failure from exact extraction preset resolution."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_legacy_extraction_preset_pointer(
    session: Session,
    pointer: LegacyExtractionPresetPointer,
    *,
    require_current: bool,
) -> ExecutionPresetRevision:
    """Resolve every pinned dependency without substituting a latest revision."""

    logical = session.get(ExecutionPresetRecord, pointer.preset_id)
    revision = session.get(ExecutionPresetRevisionRecord, pointer.preset_revision_id)
    bundle = session.get(ExecutionBundleRecord, pointer.instruction_bundle_id)
    bundle_revision = session.get(
        ExecutionBundleRevisionRecord,
        pointer.instruction_bundle_revision_id,
    )
    capacity = session.get(
        WorkerCapacityPolicyRevisionRecord,
        pointer.capacity_policy_revision_id,
    )
    protocol = session.get(ProtocolVersionRecord, pointer.role_schema_version)
    workflow = session.get(WorkflowDefinitionRecord, pointer.workflow_definition_id)
    if (
        logical is None
        or logical.state != "ACTIVE"
        or logical.preset_key != "legacy-item-extraction"
        or revision is None
        or revision.preset_id != pointer.preset_id
        or revision.state != "RELEASED"
        or revision.revision_number != pointer.preset_revision_number
        or revision.content_sha256 != pointer.preset_sha256
        or execution_preset_policy_sha256(revision.canonical_document)
        != pointer.preset_policy_sha256
        or bundle is None
        or bundle.bundle_kind != "INSTRUCTION"
        or bundle.bundle_key != "legacy-item-extraction-support"
        or bundle.state != "ACTIVE"
        or bundle_revision is None
        or bundle_revision.bundle_id != pointer.instruction_bundle_id
        or bundle_revision.bundle_kind != "INSTRUCTION"
        or bundle_revision.state != "RELEASED"
        or bundle_revision.revision_number != pointer.instruction_revision_number
        or bundle_revision.manifest_sha256 != pointer.instruction_manifest_sha256
        or bundle_revision.content_sha256 != pointer.instruction_content_sha256
        or capacity is None
        or capacity.state != "RELEASED"
        or capacity.content_sha256 != pointer.capacity_policy_sha256
        or protocol is None
        or protocol.schema_sha256 != pointer.role_schema_sha256
        or role_schema_bundle_hash(pointer.role_schema_version) != pointer.role_schema_sha256
        or workflow is None
        or not workflow.active
        or workflow.definition_key != "legacy-item-extraction"
        or workflow.definition_version != pointer.workflow_definition_version
        or workflow.definition_hash != pointer.workflow_definition_sha256
    ):
        raise LegacyExtractionPresetResolutionError(
            "LEGACY_EXTRACTION_PRESET_POINTER_STALE",
            "legacy extraction preset pointer graph differs",
        )
    if require_current and (
        logical.current_revision_id != pointer.preset_revision_id
        or bundle.current_revision_id != pointer.instruction_bundle_revision_id
    ):
        raise LegacyExtractionPresetResolutionError(
            "LEGACY_EXTRACTION_PRESET_CURRENT_MISMATCH",
            "legacy extraction current pointer differs from the required revision",
        )

    try:
        preset = ExecutionPresetRevision.model_validate(revision.canonical_document)
        instruction = InstructionBundleManifest.model_validate(bundle_revision.canonical_document)
    except PydanticValidationError as exc:
        raise LegacyExtractionPresetResolutionError(
            "LEGACY_EXTRACTION_PRESET_DOCUMENT_INVALID",
            "legacy extraction preset dependency document is invalid",
        ) from exc
    if preset.content_sha256 != compute_control_document_hash(
        preset.model_dump(mode="json"), "content_sha256"
    ) or instruction.content_sha256 != compute_control_document_hash(
        instruction.model_dump(mode="json"), "content_sha256"
    ):
        raise LegacyExtractionPresetResolutionError(
            "LEGACY_EXTRACTION_PRESET_HASH_MISMATCH",
            "legacy extraction preset dependency self-hash differs",
        )
    policies = tuple(preset.role_policies)
    components = {component.layer: component for component in instruction.components}
    platform = components.get("PLATFORM")
    role = components.get("ROLE")
    if (
        preset.preset_id != pointer.preset_id
        or preset.preset_revision_id != pointer.preset_revision_id
        or preset.revision_number != pointer.preset_revision_number
        or preset.capacity_policy_revision_id != pointer.capacity_policy_revision_id
        or pointer.role_schema_version not in preset.compatible_workflow_protocols
        or len(policies) != 1
        or policies[0].role != "support"
        or policies[0].instruction_bundle.bundle_id != pointer.instruction_bundle_id
        or policies[0].instruction_bundle.bundle_revision_id
        != pointer.instruction_bundle_revision_id
        or policies[0].instruction_bundle.manifest_sha256 != pointer.instruction_manifest_sha256
        or policies[0].instruction_bundle.manifest_artifact.artifact_id
        != bundle_revision.manifest_artifact_id
        or policies[0].instruction_bundle.manifest_artifact.artifact_revision_id
        != bundle_revision.manifest_artifact_revision_id
        or policies[0].reference_bundle is not None
        or policies[0].worker_pool_key != "legacy-extraction"
        or policies[0].sandbox != "read-only"
        or policies[0].network != "disabled"
        or instruction.bundle_id != pointer.instruction_bundle_id
        or instruction.bundle_revision_id != pointer.instruction_bundle_revision_id
        or instruction.revision_number != pointer.instruction_revision_number
        or len(components) != 2
        or platform is None
        or platform.relative_path != "instructions/platform.md"
        or role is None
        or role.relative_path != "instructions/legacy-item-extraction.md"
    ):
        raise LegacyExtractionPresetResolutionError(
            "LEGACY_EXTRACTION_PRESET_POLICY_MISMATCH",
            "legacy extraction preset policy differs from its pointer graph",
        )
    pointers = (
        (
            policies[0].instruction_bundle.manifest_artifact,
            "eom://schemas/workflow/instruction-bundle-manifest/1.0",
            "application/json",
        ),
        (
            platform.artifact,
            "eom://schemas/workflow/instruction-member/1.0",
            "text/markdown",
        ),
        (
            role.artifact,
            "eom://schemas/workflow/instruction-member/1.0",
            "text/markdown",
        ),
    )
    try:
        for artifact_pointer, schema_ref, media_type in pointers:
            resolve_control_artifact_pointer(
                session,
                artifact_pointer,
                expected_schema_ref=schema_ref,
                expected_media_type=media_type,
            )
    except ControlPlaneError as exc:
        raise LegacyExtractionPresetResolutionError(
            "LEGACY_EXTRACTION_PRESET_ARTIFACT_STALE",
            "legacy extraction preset Artifact pointer differs",
        ) from exc
    return preset


__all__ = [
    "LegacyExtractionPresetResolutionError",
    "resolve_legacy_extraction_preset_pointer",
]
