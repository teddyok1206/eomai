"""Application transactions for immutable Codex control-plane records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal, cast

from eom_identifiers import canonical_json_bytes, content_sha256, new_worker_lease_id
from eom_workflow import (
    CodexAuthHealthView,
    CodexCapabilitySnapshot,
    ControlArtifactPointer,
    ExecutionPresetRevision,
    InstructionBundleManifest,
    ReferenceBundleManifest,
    ResolvedExecutionPlan,
    WorkerCapacityPolicy,
    WorkerLeaseView,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexAuthHealthEventRecord,
    CodexCapabilityEntryRecord,
    CodexCapabilitySnapshotRecord,
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetRolePolicyRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
    WorkerCapacityPoolRecord,
    WorkerCapacityPoolRoleRecord,
    WorkerCapacityPoolSlotRecord,
    WorkerLeaseEventRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    Base,
    JobRecord,
    ProtocolVersionRecord,
    WorkerSlotRecord,
)

MAX_CONTROL_DOCUMENT_BYTES = 512 * 1024
HELD_LEASE_STATES = ("ACTIVE", "RECONCILING")


class ControlPlaneError(RuntimeError):
    """Stable, sanitized failure at the execution control-plane boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedPlanDependencyEvidence:
    """Exact cross-component identities resolved before plan persistence."""

    workflow_id: str
    workflow_definition_key: str
    workflow_definition_version: str
    workflow_definition_sha256: str
    workflow_role_schema_version: str
    content_pack_release_id: str
    content_pack_sha256: str
    graph_snapshot_revision_id: str | None = None
    evidence_bundle_revision_id: str | None = None


def compute_control_document_hash(document: dict[str, Any], hash_field: str) -> str:
    """Hash a canonical control document without its self-referential digest field."""

    if hash_field not in document:
        raise ControlPlaneError("CONTROL_DOCUMENT_INVALID", "control document hash field is absent")
    body = {key: value for key, value in document.items() if key != hash_field}
    return content_sha256(body)


def _validated_document(
    schema_name: str,
    document: dict[str, Any],
    model_type: type[
        InstructionBundleManifest
        | ReferenceBundleManifest
        | WorkerCapacityPolicy
        | ExecutionPresetRevision
        | ResolvedExecutionPlan
        | CodexAuthHealthView
        | CodexCapabilitySnapshot
    ],
) -> tuple[
    InstructionBundleManifest
    | ReferenceBundleManifest
    | WorkerCapacityPolicy
    | ExecutionPresetRevision
    | ResolvedExecutionPlan
    | CodexAuthHealthView
    | CodexCapabilitySnapshot,
    dict[str, Any],
]:
    try:
        validate_control_contract(schema_name, document)
        model = model_type.model_validate(document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_DOCUMENT_INVALID", f"{schema_name} contract validation failed"
        ) from exc
    normalized = model.model_dump(mode="json")
    if len(canonical_json_bytes(normalized)) > MAX_CONTROL_DOCUMENT_BYTES:
        raise ControlPlaneError("CONTROL_DOCUMENT_TOO_LARGE", "control document exceeds size limit")
    return model, normalized


def _require_declared_hash(document: dict[str, Any], hash_field: str) -> None:
    if document[hash_field] != compute_control_document_hash(document, hash_field):
        raise ControlPlaneError("CONTROL_HASH_MISMATCH", "control document hash does not match")


def _safe_logical_name(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in value:
        raise ControlPlaneError("CONTROL_POINTER_UNSAFE", "artifact logical member is unsafe")


def _manifest_file_entry(
    revision: ArtifactRevisionRecord, logical_name: str
) -> dict[str, Any] | None:
    files = revision.manifest.get("files")
    if isinstance(files, list):
        matching = [
            entry
            for entry in files
            if isinstance(entry, dict) and entry.get("file_name") == logical_name
        ]
        return matching[0] if len(matching) == 1 else None
    if revision.manifest.get("file_name") == logical_name:
        return revision.manifest
    return None


def _validate_artifact_pointer(
    session: Session,
    pointer: ControlArtifactPointer,
    *,
    expected_schema_ref: str | None = None,
    expected_media_type: str | None = None,
) -> ArtifactRevisionRecord:
    _safe_logical_name(pointer.logical_name)
    artifact = session.get(ArtifactRecord, pointer.artifact_id)
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    if artifact is None or revision is None:
        raise ControlPlaneError("CONTROL_POINTER_MISSING", "artifact pointer target is missing")
    if not artifact.approved or not revision.approved:
        raise ControlPlaneError(
            "CONTROL_POINTER_NOT_APPROVED", "artifact pointer target is not approved"
        )
    if revision.logical_artifact_id != pointer.artifact_id:
        raise ControlPlaneError("CONTROL_POINTER_STALE", "artifact revision owner does not match")
    if revision.content_hash != pointer.sha256:
        raise ControlPlaneError("CONTROL_POINTER_HASH_MISMATCH", "artifact pointer hash differs")
    if expected_schema_ref is not None and pointer.schema_ref != expected_schema_ref:
        raise ControlPlaneError(
            "CONTROL_POINTER_SCHEMA_MISMATCH", "artifact schema is incompatible"
        )
    if expected_media_type is not None and pointer.media_type != expected_media_type:
        raise ControlPlaneError("CONTROL_POINTER_MEDIA_MISMATCH", "artifact media is incompatible")
    member = _manifest_file_entry(revision, pointer.logical_name)
    if (
        member is None
        or member.get("sha256") != pointer.sha256
        or member.get("media_type") != pointer.media_type
        or member.get("schema_ref") != pointer.schema_ref
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_MANIFEST_MISMATCH", "artifact member manifest does not match pointer"
        )
    return revision


def resolve_control_artifact_pointer(
    session: Session,
    pointer: ControlArtifactPointer,
    *,
    expected_schema_ref: str | None = None,
    expected_media_type: str | None = None,
) -> ArtifactRevisionRecord:
    """Resolve one approved immutable member pointer for an infrastructure adapter."""

    return _validate_artifact_pointer(
        session,
        pointer,
        expected_schema_ref=expected_schema_ref,
        expected_media_type=expected_media_type,
    )


def _logical_bundle(
    session: Session,
    *,
    bundle_id: str,
    bundle_kind: Literal["INSTRUCTION", "REFERENCE"],
    bundle_key: str,
    created_by: str,
) -> ExecutionBundleRecord:
    by_key = session.scalar(
        select(ExecutionBundleRecord).where(
            ExecutionBundleRecord.bundle_kind == bundle_kind,
            ExecutionBundleRecord.bundle_key == bundle_key,
        )
    )
    by_id = session.get(ExecutionBundleRecord, bundle_id)
    if by_key is not None and by_key.bundle_id != bundle_id:
        raise ControlPlaneError("CONTROL_LOGICAL_CONFLICT", "bundle key already has another ID")
    if by_id is not None and (by_id.bundle_kind != bundle_kind or by_id.bundle_key != bundle_key):
        raise ControlPlaneError("CONTROL_LOGICAL_CONFLICT", "bundle ID has another identity")
    if by_id is not None:
        return by_id
    record = ExecutionBundleRecord(
        bundle_id=bundle_id,
        bundle_kind=bundle_kind,
        bundle_key=bundle_key,
        current_revision_id=None,
        state="ACTIVE",
        created_by=created_by,
    )
    session.add(record)
    session.flush()
    return record


def record_bundle_revision(
    session: Session,
    *,
    bundle_key: str,
    manifest_artifact: ControlArtifactPointer,
    document: dict[str, Any],
    created_by: str,
) -> ExecutionBundleRevisionRecord:
    """Validate and insert one immutable Instruction or Reference Bundle Revision."""

    schema_name = (
        "instruction-bundle-manifest"
        if document.get("schema_version") == "instruction-bundle-manifest/1.0"
        else "reference-bundle-manifest"
    )
    model_type: type[InstructionBundleManifest | ReferenceBundleManifest]
    expected_ref: str
    bundle_kind: Literal["INSTRUCTION", "REFERENCE"]
    if schema_name == "instruction-bundle-manifest":
        model_type = InstructionBundleManifest
        expected_ref = "eom://schemas/workflow/instruction-bundle-manifest/1.0"
        bundle_kind = "INSTRUCTION"
    else:
        model_type = ReferenceBundleManifest
        expected_ref = "eom://schemas/workflow/reference-bundle-manifest/1.0"
        bundle_kind = "REFERENCE"
    model, normalized = _validated_document(schema_name, document, model_type)
    if not isinstance(model, (InstructionBundleManifest, ReferenceBundleManifest)):
        raise AssertionError("validated bundle model has the wrong type")
    _require_declared_hash(normalized, "content_sha256")
    _validate_artifact_pointer(
        session,
        manifest_artifact,
        expected_schema_ref=expected_ref,
        expected_media_type="application/json",
    )
    components = model.components if isinstance(model, InstructionBundleManifest) else model.entries
    for component in components:
        _validate_artifact_pointer(session, component.artifact)

    logical = _logical_bundle(
        session,
        bundle_id=model.bundle_id,
        bundle_kind=bundle_kind,
        bundle_key=bundle_key,
        created_by=created_by,
    )
    existing = session.get(ExecutionBundleRevisionRecord, model.bundle_revision_id)
    if existing is not None:
        if (
            existing.bundle_id != model.bundle_id
            or existing.bundle_kind != bundle_kind
            or existing.revision_number != model.revision_number
            or existing.state != model.state
            or existing.manifest_artifact_id != manifest_artifact.artifact_id
            or existing.manifest_artifact_revision_id != manifest_artifact.artifact_revision_id
            or existing.manifest_sha256 != manifest_artifact.sha256
            or existing.content_sha256 != model.content_sha256
            or existing.canonical_document != normalized
        ):
            raise ControlPlaneError(
                "CONTROL_REVISION_CONFLICT", "bundle revision ID has different immutable content"
            )
        return existing
    same_number = session.scalar(
        select(ExecutionBundleRevisionRecord).where(
            ExecutionBundleRevisionRecord.bundle_id == model.bundle_id,
            ExecutionBundleRevisionRecord.revision_number == model.revision_number,
        )
    )
    if same_number is not None:
        raise ControlPlaneError(
            "CONTROL_REVISION_CONFLICT", "bundle revision number is already occupied"
        )
    record = ExecutionBundleRevisionRecord(
        bundle_revision_id=model.bundle_revision_id,
        bundle_id=logical.bundle_id,
        bundle_kind=bundle_kind,
        revision_number=model.revision_number,
        schema_version=model.schema_version,
        state=model.state,
        manifest_artifact_id=manifest_artifact.artifact_id,
        manifest_artifact_revision_id=manifest_artifact.artifact_revision_id,
        manifest_sha256=manifest_artifact.sha256,
        content_sha256=model.content_sha256,
        canonical_document=normalized,
        created_by=created_by,
    )
    session.add(record)
    session.flush()
    return record


def publish_bundle_revision(
    session: Session, *, bundle_id: str, bundle_revision_id: str
) -> ExecutionBundleRevisionRecord:
    logical = session.execute(
        select(ExecutionBundleRecord)
        .where(ExecutionBundleRecord.bundle_id == bundle_id)
        .with_for_update()
    ).scalar_one_or_none()
    revision = session.get(ExecutionBundleRevisionRecord, bundle_revision_id)
    if logical is None or revision is None or revision.bundle_id != bundle_id:
        raise ControlPlaneError("CONTROL_POINTER_MISSING", "bundle revision is missing")
    if revision.state != "RELEASED":
        raise ControlPlaneError("CONTROL_REVISION_NOT_RELEASED", "bundle revision is not released")
    if logical.current_revision_id == bundle_revision_id:
        return revision
    if logical.current_revision_id is not None:
        current = session.get(ExecutionBundleRevisionRecord, logical.current_revision_id)
        if current is None or current.revision_number >= revision.revision_number:
            raise ControlPlaneError(
                "CONTROL_CURRENT_REVISION_STALE", "bundle publication cannot move backward"
            )
    logical.current_revision_id = bundle_revision_id
    session.flush()
    return revision


def record_capacity_policy_revision(
    session: Session,
    *,
    policy_key: str,
    document: dict[str, Any],
    created_by: str,
) -> WorkerCapacityPolicyRevisionRecord:
    model, normalized = _validated_document(
        "worker-capacity-policy", document, WorkerCapacityPolicy
    )
    if not isinstance(model, WorkerCapacityPolicy):
        raise AssertionError("validated capacity model has the wrong type")
    _require_declared_hash(normalized, "content_sha256")
    logical_by_key = session.scalar(
        select(WorkerCapacityPolicyRecord).where(
            WorkerCapacityPolicyRecord.policy_key == policy_key
        )
    )
    logical = session.get(WorkerCapacityPolicyRecord, model.capacity_policy_id)
    if logical_by_key is not None and logical_by_key.capacity_policy_id != model.capacity_policy_id:
        raise ControlPlaneError("CONTROL_LOGICAL_CONFLICT", "capacity key has another ID")
    if logical is not None and logical.policy_key != policy_key:
        raise ControlPlaneError("CONTROL_LOGICAL_CONFLICT", "capacity ID has another key")
    if logical is None:
        logical = WorkerCapacityPolicyRecord(
            capacity_policy_id=model.capacity_policy_id,
            policy_key=policy_key,
            current_revision_id=None,
            state="ACTIVE",
            created_by=created_by,
        )
        session.add(logical)
        session.flush()

    existing = session.get(WorkerCapacityPolicyRevisionRecord, model.capacity_policy_revision_id)
    if existing is not None:
        if (
            existing.canonical_document != normalized
            or existing.content_sha256 != model.content_sha256
        ):
            raise ControlPlaneError(
                "CONTROL_REVISION_CONFLICT", "capacity revision has different immutable content"
            )
        return existing
    same_number = session.scalar(
        select(WorkerCapacityPolicyRevisionRecord).where(
            WorkerCapacityPolicyRevisionRecord.capacity_policy_id == model.capacity_policy_id,
            WorkerCapacityPolicyRevisionRecord.revision_number == model.revision_number,
        )
    )
    if same_number is not None:
        raise ControlPlaneError(
            "CONTROL_REVISION_CONFLICT", "capacity revision number is already occupied"
        )

    configured_slots: dict[str, WorkerSlotRecord] = {}
    for pool in model.pools:
        for slot_key in pool.slot_keys:
            slot_id = slot_key.removeprefix("slot")
            slot = session.get(WorkerSlotRecord, slot_id)
            if slot is None:
                raise ControlPlaneError(
                    "CONTROL_CAPACITY_SLOT_MISSING", "capacity policy references an unknown slot"
                )
            configured_slots[slot_id] = slot
        actual_roles = {configured_slots[key.removeprefix("slot")].role for key in pool.slot_keys}
        if not actual_roles.issubset(set(pool.roles)) or not set(pool.roles).issubset(actual_roles):
            raise ControlPlaneError(
                "CONTROL_CAPACITY_ROLE_MISMATCH", "capacity pool roles do not match fixed slots"
            )
    if len(configured_slots) > model.max_configured_slots:
        raise ControlPlaneError(
            "CONTROL_CAPACITY_LIMIT_INVALID", "capacity policy exceeds configured slot limit"
        )

    record = WorkerCapacityPolicyRevisionRecord(
        capacity_policy_revision_id=model.capacity_policy_revision_id,
        capacity_policy_id=model.capacity_policy_id,
        revision_number=model.revision_number,
        schema_version=model.schema_version,
        state=model.state,
        max_configured_slots=model.max_configured_slots,
        max_active_codex=model.max_active_codex,
        max_active_per_slot=model.max_active_per_slot,
        max_active_gpu=model.max_active_gpu,
        max_active_knowledge_analysis=model.max_active_knowledge_analysis,
        content_sha256=model.content_sha256,
        canonical_document=normalized,
        created_by=created_by,
    )
    session.add(record)
    session.flush()
    for pool in model.pools:
        session.add(
            WorkerCapacityPoolRecord(
                capacity_policy_revision_id=model.capacity_policy_revision_id,
                pool_key=pool.pool_key,
                max_active=pool.max_active,
            )
        )
        for role in pool.roles:
            session.add(
                WorkerCapacityPoolRoleRecord(
                    capacity_policy_revision_id=model.capacity_policy_revision_id,
                    pool_key=pool.pool_key,
                    role=role,
                )
            )
        for slot_key in pool.slot_keys:
            session.add(
                WorkerCapacityPoolSlotRecord(
                    capacity_policy_revision_id=model.capacity_policy_revision_id,
                    pool_key=pool.pool_key,
                    slot_id=slot_key.removeprefix("slot"),
                )
            )
    session.flush()
    return record


def publish_capacity_policy_revision(
    session: Session, *, capacity_policy_id: str, capacity_policy_revision_id: str
) -> WorkerCapacityPolicyRevisionRecord:
    logical = session.execute(
        select(WorkerCapacityPolicyRecord)
        .where(WorkerCapacityPolicyRecord.capacity_policy_id == capacity_policy_id)
        .with_for_update()
    ).scalar_one_or_none()
    revision = session.get(WorkerCapacityPolicyRevisionRecord, capacity_policy_revision_id)
    if logical is None or revision is None or revision.capacity_policy_id != capacity_policy_id:
        raise ControlPlaneError("CONTROL_POINTER_MISSING", "capacity policy revision is missing")
    if revision.state != "RELEASED":
        raise ControlPlaneError("CONTROL_REVISION_NOT_RELEASED", "capacity policy is not released")
    if logical.current_revision_id == capacity_policy_revision_id:
        return revision
    if logical.current_revision_id is not None:
        current = session.get(WorkerCapacityPolicyRevisionRecord, logical.current_revision_id)
        if current is None or current.revision_number >= revision.revision_number:
            raise ControlPlaneError(
                "CONTROL_CURRENT_REVISION_STALE", "capacity publication cannot move backward"
            )
    logical.current_revision_id = capacity_policy_revision_id
    session.flush()
    return revision


def _validate_bundle_pointer(
    session: Session,
    pointer: Any,
    *,
    expected_kind: Literal["INSTRUCTION", "REFERENCE"],
) -> ExecutionBundleRevisionRecord:
    record = session.get(ExecutionBundleRevisionRecord, pointer.bundle_revision_id)
    if (
        record is None
        or record.bundle_id != pointer.bundle_id
        or record.bundle_kind != expected_kind
        or record.state != "RELEASED"
        or record.manifest_artifact_id != pointer.manifest_artifact.artifact_id
        or record.manifest_artifact_revision_id != pointer.manifest_artifact.artifact_revision_id
        or record.manifest_sha256 != pointer.manifest_sha256
        or record.manifest_sha256 != pointer.manifest_artifact.sha256
    ):
        raise ControlPlaneError(
            "CONTROL_BUNDLE_POINTER_INVALID", "preset or plan bundle pointer is stale"
        )
    _validate_artifact_pointer(session, pointer.manifest_artifact)
    return record


def record_execution_preset_revision(
    session: Session,
    *,
    preset_key: str,
    document: dict[str, Any],
    created_by: str,
) -> ExecutionPresetRevisionRecord:
    model, normalized = _validated_document(
        "execution-preset-revision", document, ExecutionPresetRevision
    )
    if not isinstance(model, ExecutionPresetRevision):
        raise AssertionError("validated preset model has the wrong type")
    _require_declared_hash(normalized, "content_sha256")
    capacity = session.get(WorkerCapacityPolicyRevisionRecord, model.capacity_policy_revision_id)
    if capacity is None or capacity.state != "RELEASED":
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "preset capacity policy is not released"
        )
    pools = {
        pool.pool_key
        for pool in session.scalars(
            select(WorkerCapacityPoolRecord).where(
                WorkerCapacityPoolRecord.capacity_policy_revision_id
                == model.capacity_policy_revision_id
            )
        )
    }
    pool_roles = {
        (row.pool_key, row.role)
        for row in session.scalars(
            select(WorkerCapacityPoolRoleRecord).where(
                WorkerCapacityPoolRoleRecord.capacity_policy_revision_id
                == model.capacity_policy_revision_id
            )
        )
    }
    for policy in model.role_policies:
        _validate_bundle_pointer(session, policy.instruction_bundle, expected_kind="INSTRUCTION")
        if policy.reference_bundle is not None:
            _validate_bundle_pointer(session, policy.reference_bundle, expected_kind="REFERENCE")
        if (
            policy.worker_pool_key not in pools
            or (
                policy.worker_pool_key,
                policy.role,
            )
            not in pool_roles
        ):
            raise ControlPlaneError(
                "CONTROL_PRESET_POOL_INVALID", "preset role is not admitted by its worker pool"
            )
    for version in model.compatible_workflow_protocols:
        if session.get(ProtocolVersionRecord, version) is None:
            raise ControlPlaneError(
                "CONTROL_PROTOCOL_POINTER_MISSING", "preset workflow protocol is not registered"
            )

    by_key = session.scalar(
        select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == preset_key)
    )
    logical = session.get(ExecutionPresetRecord, model.preset_id)
    if by_key is not None and by_key.preset_id != model.preset_id:
        raise ControlPlaneError("CONTROL_LOGICAL_CONFLICT", "preset key has another ID")
    if logical is not None and logical.preset_key != preset_key:
        raise ControlPlaneError("CONTROL_LOGICAL_CONFLICT", "preset ID has another key")
    if logical is None:
        logical = ExecutionPresetRecord(
            preset_id=model.preset_id,
            preset_key=preset_key,
            current_revision_id=None,
            state="ACTIVE",
            created_by=created_by,
        )
        session.add(logical)
        session.flush()
    existing = session.get(ExecutionPresetRevisionRecord, model.preset_revision_id)
    if existing is not None:
        if (
            existing.canonical_document != normalized
            or existing.content_sha256 != model.content_sha256
        ):
            raise ControlPlaneError(
                "CONTROL_REVISION_CONFLICT", "preset revision has different immutable content"
            )
        return existing
    same_number = session.scalar(
        select(ExecutionPresetRevisionRecord).where(
            ExecutionPresetRevisionRecord.preset_id == model.preset_id,
            ExecutionPresetRevisionRecord.revision_number == model.revision_number,
        )
    )
    if same_number is not None:
        raise ControlPlaneError(
            "CONTROL_REVISION_CONFLICT", "preset revision number is already occupied"
        )
    record = ExecutionPresetRevisionRecord(
        preset_revision_id=model.preset_revision_id,
        preset_id=model.preset_id,
        revision_number=model.revision_number,
        schema_version=model.schema_version,
        state=model.state,
        display_name=model.display_name,
        description=model.description,
        capacity_policy_revision_id=model.capacity_policy_revision_id,
        general_knowledge_policy=model.general_knowledge_policy,
        compatible_workflow_protocols=list(model.compatible_workflow_protocols),
        content_sha256=model.content_sha256,
        canonical_document=normalized,
        created_by=created_by,
    )
    session.add(record)
    session.flush()
    for policy in model.role_policies:
        session.add(
            ExecutionPresetRolePolicyRecord(
                preset_revision_id=model.preset_revision_id,
                role=policy.role,
                model_candidates=[
                    candidate.model_dump(mode="json") for candidate in policy.model_candidates
                ],
                instruction_bundle_revision_id=policy.instruction_bundle.bundle_revision_id,
                reference_bundle_revision_id=(
                    policy.reference_bundle.bundle_revision_id
                    if policy.reference_bundle is not None
                    else None
                ),
                worker_pool_key=policy.worker_pool_key,
                timeout_seconds=policy.timeout_seconds,
                sandbox=policy.sandbox,
                network=policy.network,
            )
        )
    session.flush()
    return record


def publish_execution_preset_revision(
    session: Session, *, preset_id: str, preset_revision_id: str
) -> ExecutionPresetRevisionRecord:
    logical = session.execute(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_id == preset_id)
        .with_for_update()
    ).scalar_one_or_none()
    revision = session.get(ExecutionPresetRevisionRecord, preset_revision_id)
    if logical is None or revision is None or revision.preset_id != preset_id:
        raise ControlPlaneError("CONTROL_POINTER_MISSING", "preset revision is missing")
    if revision.state != "RELEASED":
        raise ControlPlaneError("CONTROL_REVISION_NOT_RELEASED", "preset revision is not released")
    if logical.current_revision_id == preset_revision_id:
        return revision
    if logical.current_revision_id is not None:
        current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if current is None or current.revision_number >= revision.revision_number:
            raise ControlPlaneError(
                "CONTROL_CURRENT_REVISION_STALE", "preset publication cannot move backward"
            )
    logical.current_revision_id = preset_revision_id
    session.flush()
    return revision


def record_resolved_execution_plan(
    session: Session,
    *,
    document: dict[str, Any],
    dependencies: ResolvedPlanDependencyEvidence,
) -> ResolvedExecutionPlanRecord:
    model, normalized = _validated_document(
        "resolved-execution-plan", document, ResolvedExecutionPlan
    )
    if not isinstance(model, ResolvedExecutionPlan):
        raise AssertionError("validated execution plan has the wrong type")
    _require_declared_hash(normalized, "plan_sha256")
    if (
        dependencies.workflow_id != model.workflow_id
        or dependencies.workflow_definition_key != model.workflow_definition_key
        or dependencies.workflow_definition_version != model.workflow_definition_version
        or dependencies.workflow_definition_sha256 != model.workflow_definition_sha256
        or dependencies.content_pack_release_id != model.content_pack_release_id
        or dependencies.content_pack_sha256 != model.content_pack_sha256
        or dependencies.graph_snapshot_revision_id != model.graph_snapshot_revision_id
        or dependencies.evidence_bundle_revision_id != model.evidence_bundle_revision_id
    ):
        raise ControlPlaneError(
            "CONTROL_PLAN_DEPENDENCY_MISMATCH", "resolved plan dependencies changed"
        )
    preset = session.get(ExecutionPresetRevisionRecord, model.preset_revision_id)
    if (
        preset is None
        or preset.preset_id != model.preset_id
        or preset.state != "RELEASED"
        or preset.content_sha256 != model.preset_sha256
        or preset.capacity_policy_revision_id != model.capacity_policy_revision_id
        or dependencies.workflow_role_schema_version not in preset.compatible_workflow_protocols
    ):
        raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "resolved preset is stale")
    role_policies = {
        row.role: row
        for row in session.scalars(
            select(ExecutionPresetRolePolicyRecord).where(
                ExecutionPresetRolePolicyRecord.preset_revision_id == model.preset_revision_id
            )
        )
    }
    for step in model.steps:
        policy = role_policies.get(step.role)
        candidates = [] if policy is None else policy.model_candidates
        if (
            policy is None
            or {"model": step.model, "reasoning_effort": step.reasoning_effort} not in candidates
            or policy.instruction_bundle_revision_id != step.instruction_bundle.bundle_revision_id
            or policy.reference_bundle_revision_id
            != (
                step.reference_bundle.bundle_revision_id
                if step.reference_bundle is not None
                else None
            )
            or policy.worker_pool_key != step.worker_pool_key
            or policy.timeout_seconds != step.timeout_seconds
            or policy.sandbox != step.sandbox
            or policy.network != step.network
            or (
                preset.general_knowledge_policy == "DENY"
                and step.general_knowledge_mode != "DENIED"
            )
        ):
            raise ControlPlaneError(
                "CONTROL_PLAN_POLICY_MISMATCH", "resolved plan step differs from preset"
            )
        _validate_bundle_pointer(session, step.instruction_bundle, expected_kind="INSTRUCTION")
        if step.reference_bundle is not None:
            _validate_bundle_pointer(session, step.reference_bundle, expected_kind="REFERENCE")

    existing = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == model.workflow_id
        )
    )
    if existing is not None:
        if existing.plan_sha256 != model.plan_sha256 or existing.canonical_document != normalized:
            raise ControlPlaneError(
                "CONTROL_PLAN_CONFLICT", "workflow already has a different execution plan"
            )
        return existing
    if session.get(ResolvedExecutionPlanRecord, model.plan_id) is not None:
        raise ControlPlaneError("CONTROL_PLAN_CONFLICT", "execution plan ID is already used")
    record = ResolvedExecutionPlanRecord(
        plan_id=model.plan_id,
        workflow_id=model.workflow_id,
        preset_id=model.preset_id,
        preset_revision_id=model.preset_revision_id,
        capacity_policy_revision_id=model.capacity_policy_revision_id,
        graph_snapshot_revision_id=model.graph_snapshot_revision_id,
        evidence_bundle_revision_id=model.evidence_bundle_revision_id,
        plan_sha256=model.plan_sha256,
        resolver_version=model.resolver_version,
        canonical_document=normalized,
        resolved_at=model.resolved_at,
    )
    session.add(record)
    session.flush()
    for step in model.steps:
        session.add(
            ResolvedExecutionPlanStepRecord(
                plan_id=model.plan_id,
                step_key=step.step_key,
                role=step.role,
                model=step.model,
                reasoning_effort=step.reasoning_effort,
                instruction_bundle_revision_id=step.instruction_bundle.bundle_revision_id,
                reference_bundle_revision_id=(
                    step.reference_bundle.bundle_revision_id
                    if step.reference_bundle is not None
                    else None
                ),
                worker_pool_key=step.worker_pool_key,
                timeout_seconds=step.timeout_seconds,
                sandbox=step.sandbox,
                network=step.network,
                general_knowledge_mode=step.general_knowledge_mode,
            )
        )
    session.flush()
    return record


def record_auth_health(session: Session, *, document: dict[str, Any]) -> CodexAuthBindingRecord:
    model, _ = _validated_document("codex-auth-health-view", document, CodexAuthHealthView)
    if not isinstance(model, CodexAuthHealthView):
        raise AssertionError("validated auth health model has the wrong type")
    slot_id = model.slot_key.removeprefix("slot")
    if session.get(WorkerSlotRecord, slot_id) is None:
        raise ControlPlaneError("CONTROL_AUTH_SLOT_MISSING", "authentication slot is unknown")
    binding = session.get(CodexAuthBindingRecord, model.binding_id)
    by_slot = session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == slot_id)
    )
    if by_slot is not None and by_slot.binding_id != model.binding_id:
        raise ControlPlaneError("CONTROL_AUTH_BINDING_CONFLICT", "slot has another auth binding")
    if binding is not None and (
        binding.worker_slot_id != slot_id or binding.account_label != model.account_label
    ):
        raise ControlPlaneError(
            "CONTROL_AUTH_BINDING_CONFLICT", "auth binding identity cannot change"
        )
    if binding is None:
        binding = CodexAuthBindingRecord(
            binding_id=model.binding_id,
            worker_slot_id=slot_id,
            account_label=model.account_label,
            state=model.state,
            reason_code=model.reason_code,
            codex_cli_version=model.codex_cli_version,
            observed_at=model.observed_at,
            valid_until=model.valid_until,
            resource_version=1,
        )
        session.add(binding)
    else:
        if (
            binding.state == model.state
            and binding.reason_code == model.reason_code
            and binding.codex_cli_version == model.codex_cli_version
            and binding.observed_at == model.observed_at
            and binding.valid_until == model.valid_until
        ):
            return binding
        if binding.observed_at is not None and model.observed_at <= binding.observed_at:
            raise ControlPlaneError(
                "CONTROL_AUTH_OBSERVATION_STALE", "auth observation is not newer"
            )
        binding.state = model.state
        binding.reason_code = model.reason_code
        binding.codex_cli_version = model.codex_cli_version
        binding.observed_at = model.observed_at
        binding.valid_until = model.valid_until
        binding.resource_version += 1
    sequence = session.scalar(
        select(func.coalesce(func.max(CodexAuthHealthEventRecord.sequence), 0)).where(
            CodexAuthHealthEventRecord.binding_id == model.binding_id
        )
    )
    session.add(
        CodexAuthHealthEventRecord(
            binding_id=model.binding_id,
            sequence=int(sequence or 0) + 1,
            state=model.state,
            reason_code=model.reason_code,
            codex_cli_version=model.codex_cli_version,
            observed_at=model.observed_at,
            valid_until=model.valid_until,
        )
    )
    session.flush()
    return binding


def record_capability_snapshot(
    session: Session, *, document: dict[str, Any]
) -> CodexCapabilitySnapshotRecord:
    model, normalized = _validated_document(
        "codex-capability-snapshot", document, CodexCapabilitySnapshot
    )
    if not isinstance(model, CodexCapabilitySnapshot):
        raise AssertionError("validated capability model has the wrong type")
    _require_declared_hash(normalized, "snapshot_sha256")
    binding = session.get(CodexAuthBindingRecord, model.binding_id)
    if binding is None:
        raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "capability binding is missing")
    if binding.codex_cli_version != model.codex_cli_version:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_CLI_MISMATCH", "capability CLI version differs from binding"
        )
    existing = session.get(CodexCapabilitySnapshotRecord, model.capability_snapshot_id)
    if existing is not None:
        if (
            existing.snapshot_sha256 != model.snapshot_sha256
            or existing.canonical_document != normalized
        ):
            raise ControlPlaneError(
                "CONTROL_CAPABILITY_CONFLICT", "capability snapshot ID has different content"
            )
        return existing
    same_hash = session.scalar(
        select(CodexCapabilitySnapshotRecord).where(
            CodexCapabilitySnapshotRecord.binding_id == model.binding_id,
            CodexCapabilitySnapshotRecord.snapshot_sha256 == model.snapshot_sha256,
        )
    )
    if same_hash is not None:
        return same_hash
    record = CodexCapabilitySnapshotRecord(
        capability_snapshot_id=model.capability_snapshot_id,
        binding_id=model.binding_id,
        codex_cli_version=model.codex_cli_version,
        source=model.source,
        observed_at=model.observed_at,
        valid_until=model.valid_until,
        snapshot_sha256=model.snapshot_sha256,
        canonical_document=normalized,
    )
    session.add(record)
    session.flush()
    for capability in model.capabilities:
        for effort in capability.reasoning_efforts:
            session.add(
                CodexCapabilityEntryRecord(
                    capability_snapshot_id=model.capability_snapshot_id,
                    model=capability.model,
                    reasoning_effort=effort,
                    state=capability.state,
                )
            )
    session.flush()
    return record


def _held_count(session: Session, *conditions: Any) -> int:
    return int(
        session.scalar(
            select(func.count(WorkerLeaseRecord.lease_id)).where(
                WorkerLeaseRecord.state.in_(HELD_LEASE_STATES), *conditions
            )
        )
        or 0
    )


def acquire_worker_lease(
    session: Session,
    *,
    plan_id: str,
    step_key: str,
    job_id: str,
    attempt: int,
    workload_class: Literal["CODEX", "KNOWLEDGE_ANALYSIS"],
    acquired_at: datetime,
    ttl: timedelta,
) -> WorkerLeaseRecord:
    """Atomically reserve one deterministic eligible fixed worker slot."""

    if acquired_at.tzinfo is None or acquired_at.utcoffset() != timedelta(0):
        raise ControlPlaneError("CONTROL_TIME_INVALID", "lease acquisition time must use UTC")
    if not timedelta(seconds=30) <= ttl <= timedelta(hours=2):
        raise ControlPlaneError("CONTROL_LEASE_TTL_INVALID", "lease TTL is outside bounds")
    plan = session.get(ResolvedExecutionPlanRecord, plan_id)
    step = session.get(ResolvedExecutionPlanStepRecord, (plan_id, step_key))
    job = session.get(JobRecord, job_id)
    if plan is None or step is None or job is None:
        raise ControlPlaneError("CONTROL_LEASE_POINTER_MISSING", "lease dependency is missing")
    existing = session.scalar(
        select(WorkerLeaseRecord).where(
            WorkerLeaseRecord.job_id == job_id,
            WorkerLeaseRecord.state.in_(HELD_LEASE_STATES),
        )
    )
    if existing is not None:
        if (
            existing.workflow_id != plan.workflow_id
            or existing.pool_key != step.worker_pool_key
            or existing.attempt != attempt
            or existing.workload_class != workload_class
        ):
            raise ControlPlaneError(
                "CONTROL_LEASE_JOB_MISMATCH", "held lease belongs to another execution"
            )
        return existing
    request = job.request
    step_runs = Base.metadata.tables.get("workflow_step_runs")
    if step_runs is None:
        raise ControlPlaneError(
            "CONTROL_MODEL_COMPOSITION_INVALID", "workflow step model is not registered"
        )
    step_run_id = request.get("step_run_id")
    stored_step = (
        session.execute(
            select(
                step_runs.c.workflow_id,
                step_runs.c.step_key,
                step_runs.c.attempt,
                step_runs.c.worker_role,
                step_runs.c.platform_job_id,
            ).where(step_runs.c.step_run_id == step_run_id)
        ).one_or_none()
        if isinstance(step_run_id, str)
        else None
    )
    if (
        job.status != "QUEUED"
        or request.get("workflow_id") != plan.workflow_id
        or request.get("role") != step.role
        or request.get("attempt") != attempt
        or stored_step is None
        or stored_step.workflow_id != plan.workflow_id
        or stored_step.step_key != step_key
        or stored_step.attempt != attempt
        or stored_step.worker_role != step.role
        or stored_step.platform_job_id != job_id
    ):
        raise ControlPlaneError("CONTROL_LEASE_JOB_MISMATCH", "job does not match plan step")
    policy = session.execute(
        select(WorkerCapacityPolicyRevisionRecord)
        .where(
            WorkerCapacityPolicyRevisionRecord.capacity_policy_revision_id
            == plan.capacity_policy_revision_id
        )
        .with_for_update()
    ).scalar_one_or_none()
    pool = session.get(
        WorkerCapacityPoolRecord,
        (plan.capacity_policy_revision_id, step.worker_pool_key),
    )
    if policy is None or policy.state != "RELEASED" or pool is None:
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "lease capacity policy is unavailable"
        )
    existing = session.scalar(
        select(WorkerLeaseRecord).where(
            WorkerLeaseRecord.job_id == job_id,
            WorkerLeaseRecord.state.in_(HELD_LEASE_STATES),
        )
    )
    if existing is not None:
        if (
            existing.workflow_id != plan.workflow_id
            or existing.pool_key != step.worker_pool_key
            or existing.attempt != attempt
            or existing.workload_class != workload_class
        ):
            raise ControlPlaneError(
                "CONTROL_LEASE_JOB_MISMATCH", "held lease belongs to another execution"
            )
        return existing
    pool_role = session.get(
        WorkerCapacityPoolRoleRecord,
        (plan.capacity_policy_revision_id, step.worker_pool_key, step.role),
    )
    if pool_role is None:
        raise ControlPlaneError(
            "CONTROL_CAPACITY_ROLE_MISMATCH", "plan role is absent from its capacity pool"
        )
    if (
        _held_count(
            session,
            WorkerLeaseRecord.capacity_policy_revision_id == plan.capacity_policy_revision_id,
        )
        >= policy.max_active_codex
    ):
        raise ControlPlaneError("CONTROL_CAPACITY_EXHAUSTED", "global worker capacity is full")
    if (
        _held_count(
            session,
            WorkerLeaseRecord.capacity_policy_revision_id == plan.capacity_policy_revision_id,
            WorkerLeaseRecord.pool_key == step.worker_pool_key,
        )
        >= pool.max_active
    ):
        raise ControlPlaneError("CONTROL_CAPACITY_EXHAUSTED", "worker pool is full")
    if (
        workload_class == "KNOWLEDGE_ANALYSIS"
        and _held_count(
            session,
            WorkerLeaseRecord.capacity_policy_revision_id == plan.capacity_policy_revision_id,
            WorkerLeaseRecord.workload_class == "KNOWLEDGE_ANALYSIS",
        )
        >= policy.max_active_knowledge_analysis
    ):
        raise ControlPlaneError(
            "CONTROL_KNOWLEDGE_CAPACITY_EXHAUSTED", "knowledge analysis capacity is full"
        )

    eligible = session.execute(
        select(
            WorkerSlotRecord,
            CodexAuthBindingRecord,
            CodexCapabilitySnapshotRecord,
        )
        .join(
            WorkerCapacityPoolSlotRecord,
            WorkerCapacityPoolSlotRecord.slot_id == WorkerSlotRecord.slot_id,
        )
        .join(
            CodexAuthBindingRecord,
            CodexAuthBindingRecord.worker_slot_id == WorkerSlotRecord.slot_id,
        )
        .join(
            CodexCapabilitySnapshotRecord,
            CodexCapabilitySnapshotRecord.binding_id == CodexAuthBindingRecord.binding_id,
        )
        .join(
            CodexCapabilityEntryRecord,
            and_(
                CodexCapabilityEntryRecord.capability_snapshot_id
                == CodexCapabilitySnapshotRecord.capability_snapshot_id,
                CodexCapabilityEntryRecord.model == step.model,
                CodexCapabilityEntryRecord.reasoning_effort == step.reasoning_effort,
                CodexCapabilityEntryRecord.state == "AVAILABLE",
            ),
        )
        .where(
            WorkerCapacityPoolSlotRecord.capacity_policy_revision_id
            == plan.capacity_policy_revision_id,
            WorkerCapacityPoolSlotRecord.pool_key == step.worker_pool_key,
            WorkerSlotRecord.enabled.is_(True),
            WorkerSlotRecord.role == step.role,
            CodexAuthBindingRecord.state == "READY",
            CodexAuthBindingRecord.valid_until > acquired_at,
            CodexCapabilitySnapshotRecord.valid_until > acquired_at,
            CodexCapabilitySnapshotRecord.codex_cli_version
            == CodexAuthBindingRecord.codex_cli_version,
        )
        .order_by(
            WorkerSlotRecord.slot_id,
            CodexCapabilitySnapshotRecord.observed_at.desc(),
        )
    ).all()
    selected: (
        tuple[WorkerSlotRecord, CodexAuthBindingRecord, CodexCapabilitySnapshotRecord] | None
    ) = None
    visited_slots: set[str] = set()
    for slot, binding, snapshot in eligible:
        if slot.slot_id in visited_slots:
            continue
        visited_slots.add(slot.slot_id)
        if _held_count(session, WorkerLeaseRecord.worker_slot_id == slot.slot_id):
            continue
        if (
            slot.gpu
            and _held_count(
                session,
                WorkerLeaseRecord.capacity_policy_revision_id == plan.capacity_policy_revision_id,
                WorkerLeaseRecord.worker_slot_id.in_(
                    select(WorkerSlotRecord.slot_id).where(WorkerSlotRecord.gpu.is_(True))
                ),
            )
            >= policy.max_active_gpu
        ):
            continue
        selected = (slot, binding, snapshot)
        break
    if selected is None:
        raise ControlPlaneError("CONTROL_ELIGIBLE_SLOT_UNAVAILABLE", "no eligible slot is ready")
    slot, binding, _ = selected
    lease = WorkerLeaseRecord(
        lease_id=new_worker_lease_id(),
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        pool_key=step.worker_pool_key,
        worker_slot_id=slot.slot_id,
        binding_id=binding.binding_id,
        workflow_id=plan.workflow_id,
        job_id=job_id,
        attempt=attempt,
        workload_class=workload_class,
        state="ACTIVE",
        acquired_at=acquired_at,
        expires_at=acquired_at + ttl,
        released_at=None,
        release_reason=None,
    )
    session.add(lease)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ControlPlaneError(
            "CONTROL_LEASE_RACE", "worker lease lost a concurrent race"
        ) from exc
    session.add(
        WorkerLeaseEventRecord(
            lease_id=lease.lease_id,
            sequence=1,
            event_type="LEASE_ACQUIRED",
            prior_state=None,
            new_state="ACTIVE",
            reason_code=None,
        )
    )
    session.flush()
    return lease


def _append_lease_event(
    session: Session,
    *,
    lease: WorkerLeaseRecord,
    event_type: str,
    prior_state: str,
    reason_code: str,
) -> None:
    sequence = session.scalar(
        select(func.coalesce(func.max(WorkerLeaseEventRecord.sequence), 0)).where(
            WorkerLeaseEventRecord.lease_id == lease.lease_id
        )
    )
    session.add(
        WorkerLeaseEventRecord(
            lease_id=lease.lease_id,
            sequence=int(sequence or 0) + 1,
            event_type=event_type,
            prior_state=prior_state,
            new_state=lease.state,
            reason_code=reason_code,
        )
    )


def begin_expired_lease_reconciliation(
    session: Session, *, lease_id: str, observed_at: datetime
) -> WorkerLeaseRecord:
    lease = session.execute(
        select(WorkerLeaseRecord).where(WorkerLeaseRecord.lease_id == lease_id).with_for_update()
    ).scalar_one_or_none()
    if lease is None:
        raise ControlPlaneError("CONTROL_LEASE_MISSING", "worker lease is missing")
    if lease.state == "RECONCILING":
        return lease
    if lease.state != "ACTIVE" or observed_at < lease.expires_at:
        raise ControlPlaneError(
            "CONTROL_LEASE_STATE_INVALID", "only an expired active lease can reconcile"
        )
    lease.state = "RECONCILING"
    _append_lease_event(
        session,
        lease=lease,
        event_type="LEASE_RECONCILIATION_STARTED",
        prior_state="ACTIVE",
        reason_code="LEASE_TTL_EXPIRED",
    )
    session.flush()
    return lease


def terminalize_worker_lease(
    session: Session,
    *,
    lease_id: str,
    terminal_state: Literal["RELEASED", "EXPIRED"],
    reason_code: str,
    released_at: datetime,
) -> WorkerLeaseRecord:
    lease = session.execute(
        select(WorkerLeaseRecord).where(WorkerLeaseRecord.lease_id == lease_id).with_for_update()
    ).scalar_one_or_none()
    if lease is None:
        raise ControlPlaneError("CONTROL_LEASE_MISSING", "worker lease is missing")
    if lease.state in {"RELEASED", "EXPIRED"}:
        if (
            lease.state == terminal_state
            and lease.release_reason == reason_code
            and lease.released_at == released_at
        ):
            return lease
        raise ControlPlaneError("CONTROL_LEASE_STATE_INVALID", "lease is already terminal")
    if terminal_state == "EXPIRED" and lease.state != "RECONCILING":
        raise ControlPlaneError(
            "CONTROL_LEASE_STATE_INVALID", "lease must reconcile before expiring"
        )
    if released_at < lease.acquired_at:
        raise ControlPlaneError("CONTROL_TIME_INVALID", "lease release predates acquisition")
    prior = lease.state
    lease.state = terminal_state
    lease.released_at = released_at
    lease.release_reason = reason_code
    _append_lease_event(
        session,
        lease=lease,
        event_type="LEASE_RELEASED" if terminal_state == "RELEASED" else "LEASE_EXPIRED",
        prior_state=prior,
        reason_code=reason_code,
    )
    session.flush()
    return lease


def worker_lease_view(lease: WorkerLeaseRecord) -> WorkerLeaseView:
    return WorkerLeaseView(
        lease_id=lease.lease_id,
        capacity_policy_revision_id=lease.capacity_policy_revision_id,
        pool_key=lease.pool_key,
        slot_key=f"slot{lease.worker_slot_id}",
        binding_id=lease.binding_id,
        workflow_id=lease.workflow_id,
        job_id=lease.job_id,
        attempt=lease.attempt,
        state=cast(Literal["ACTIVE", "RELEASED", "EXPIRED", "RECONCILING"], lease.state),
        acquired_at=lease.acquired_at.astimezone(UTC),
        expires_at=lease.expires_at.astimezone(UTC),
        released_at=(lease.released_at.astimezone(UTC) if lease.released_at else None),
        release_reason=lease.release_reason,
    )
