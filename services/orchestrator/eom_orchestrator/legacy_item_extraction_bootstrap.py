"""Idempotent control-plane bootstrap for isolated legacy item extraction."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import yaml
from eom_identifiers import canonical_json_bytes
from eom_workflow import (
    ControlArtifactPointer,
    ExecutionPresetRevision,
    InstructionBundleManifest,
    WorkerCapacityPolicyV3,
    compile_definition_data,
)
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import WorkflowDefinitionRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_bootstrap import (
    MAX_BOOTSTRAP_MANIFEST_BYTES,
    _bootstrap_bindings,
    _publish_instruction_bundle,
    _publish_markdown,
    _read_file,
    _read_member,
    _require_artifact_source_commit,
    _safe_root,
    _stable_id,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    BundleRevisionCAS,
    ControlPlaneError,
    compute_control_document_artifact_hash,
    compute_control_document_hash,
    publish_capacity_policy_revision,
    record_capacity_policy_revision,
    resolve_control_artifact_pointer,
)
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ProtocolVersionRecord, WorkerSlotRecord
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    execution_preset_policy_sha256,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.repository import ensure_protocol_version, upsert_worker_slot
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerSlot

EXTRACTION_CAPACITY_CREATED_AT = datetime(2026, 9, 1, tzinfo=UTC)


class LegacyItemExtractionBootstrapPredecessor(BaseModel):
    """Exact released production identities that authorize the V2 successor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_revision_number: int = Field(ge=1)
    preset_content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    preset_policy_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    capacity_policy_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    instruction_bundle_id: str = Field(pattern=r"^instrbundle_[0-9a-f]{32}$")
    instruction_bundle_revision_id: str = Field(pattern=r"^instrrev_[0-9a-f]{32}$")
    instruction_revision_number: int = Field(ge=1)
    instruction_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    instruction_content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    platform_instruction_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    role_instruction_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    workflow_definition_id: str = Field(pattern=r"^wfdef_[0-9a-f]{32}$")
    workflow_definition_version: Literal["1.0.0"]
    workflow_definition_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    role_schema_version: Literal["workflow-role/1.14.0"]
    role_schema_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class LegacyItemExtractionBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[
        "legacy-item-extraction-control-bootstrap/1.0",
        "legacy-item-extraction-control-bootstrap/2.0",
    ]
    preset_key: Literal["legacy-item-extraction"]
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    created_at: datetime
    model: Literal["gpt-5.6-terra"]
    reasoning_effort: Literal["xhigh"]
    general_knowledge_policy: Literal["DENY"]
    compatible_workflow_protocols: tuple[Literal["workflow-role/1.14.0"], ...] = Field(
        min_length=1, max_length=1
    )
    platform_instruction_path: Literal["instructions/platform.md"]
    role_instruction_path: Literal["instructions/legacy-item-extraction.md"]
    slot_key: Literal["slot06"]
    worker_pool_key: Literal["legacy-extraction"]
    timeout_seconds: Literal[7200]
    instruction_revision_number: Literal[2] | None = None
    predecessor: LegacyItemExtractionBootstrapPredecessor | None = None

    @model_validator(mode="after")
    def exact_immutable_contract(self) -> LegacyItemExtractionBootstrapManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("legacy extraction bootstrap timestamp must use UTC")
        if self.compatible_workflow_protocols != ("workflow-role/1.14.0",):
            raise ValueError("legacy extraction bootstrap protocol must be exact")
        if self.schema_version == "legacy-item-extraction-control-bootstrap/1.0":
            if self.instruction_revision_number is not None or self.predecessor is not None:
                raise ValueError("legacy extraction V1 cannot declare successor pins")
        elif self.instruction_revision_number is None or self.predecessor is None:
            raise ValueError("legacy extraction V2 requires exact successor pins")
        elif self.instruction_revision_number != self.predecessor.instruction_revision_number + 1:
            raise ValueError("legacy extraction instruction successor must be adjacent")
        elif self.predecessor.role_schema_version not in self.compatible_workflow_protocols:
            raise ValueError("legacy extraction predecessor role schema differs")
        return self

    @model_serializer(mode="wrap")
    def serialize_versioned_manifest(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, object]:
        value = cast(dict[str, object], handler(self))
        if self.schema_version == "legacy-item-extraction-control-bootstrap/1.0":
            value.pop("instruction_revision_number", None)
            value.pop("predecessor", None)
        return value


class LegacyItemExtractionBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    preset_revision_id: str
    preset_revision_number: int
    preset_policy_sha256: str
    preset_content_sha256: str
    capacity_policy_revision_id: str
    capacity_policy_sha256: str
    instruction_bundle_id: str
    instruction_bundle_revision_id: str
    instruction_revision_number: int
    instruction_manifest_sha256: str
    instruction_content_sha256: str
    evaluation_id: str
    auth_binding_id: str
    source_commit: str


def load_legacy_item_extraction_bootstrap_manifest(
    config_directory: Path,
) -> LegacyItemExtractionBootstrapManifest:
    root = _safe_root(config_directory)
    raw = _read_file(root / "bootstrap.yaml", root=root, max_bytes=MAX_BOOTSTRAP_MANIFEST_BYTES)
    try:
        value: object = yaml.safe_load(raw.decode("utf-8"))
        if isinstance(value, dict) and isinstance(value.get("created_at"), datetime):
            value = dict(value)
            value["created_at"] = value["created_at"].isoformat().replace("+00:00", "Z")
        schema_version = value.get("schema_version") if isinstance(value, dict) else None
        schema_name = {
            "legacy-item-extraction-control-bootstrap/1.0": (
                "legacy-item-extraction-control-bootstrap"
            ),
            "legacy-item-extraction-control-bootstrap/2.0": (
                "legacy-item-extraction-control-bootstrap-v2"
            ),
        }.get(schema_version if isinstance(schema_version, str) else "")
        if schema_name is None:
            raise ValueError("legacy extraction bootstrap schema version is unsupported")
        validate_control_contract(schema_name, value)
        return LegacyItemExtractionBootstrapManifest.model_validate(value)
    except (UnicodeError, yaml.YAMLError, JsonSchemaValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "legacy item extraction bootstrap manifest is invalid"
        ) from exc


def _require_successor_preflight(
    session: Session,
    *,
    manifest: LegacyItemExtractionBootstrapManifest,
    platform_sha256: str,
    role_sha256: str,
) -> ControlArtifactPointer:
    """Resolve the exact V1 history before any successor Artifact is published."""

    predecessor = manifest.predecessor
    if predecessor is None or manifest.instruction_revision_number is None:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID",
            "legacy extraction successor pins are missing",
        )
    if platform_sha256 != predecessor.platform_instruction_sha256:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_PREDECESSOR_STALE",
            "legacy extraction platform instruction changed",
        )
    if role_sha256 == predecessor.role_instruction_sha256:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction successor instruction did not change",
        )
    if role_schema_bundle_hash(predecessor.role_schema_version) != predecessor.role_schema_sha256:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_PREDECESSOR_STALE",
            "legacy extraction installed role schema differs",
        )

    logical = session.scalar(
        select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == manifest.preset_key)
    )
    prior_preset = session.get(
        ExecutionPresetRevisionRecord,
        predecessor.preset_revision_id,
    )
    capacity = session.get(
        WorkerCapacityPolicyRevisionRecord,
        predecessor.capacity_policy_revision_id,
    )
    protocol = session.get(ProtocolVersionRecord, predecessor.role_schema_version)
    workflow = session.get(WorkflowDefinitionRecord, predecessor.workflow_definition_id)
    bundle = session.get(ExecutionBundleRecord, predecessor.instruction_bundle_id)
    prior_bundle = session.get(
        ExecutionBundleRevisionRecord,
        predecessor.instruction_bundle_revision_id,
    )
    if (
        logical is None
        or logical.state != "ACTIVE"
        or logical.preset_id != predecessor.preset_id
        or prior_preset is None
        or prior_preset.preset_revision_id != predecessor.preset_revision_id
        or prior_preset.preset_id != predecessor.preset_id
        or prior_preset.state != "RELEASED"
        or prior_preset.revision_number != predecessor.preset_revision_number
        or prior_preset.content_sha256 != predecessor.preset_content_sha256
        or capacity is None
        or capacity.capacity_policy_revision_id != predecessor.capacity_policy_revision_id
        or capacity.state != "RELEASED"
        or capacity.content_sha256 != predecessor.capacity_policy_sha256
        or protocol is None
        or protocol.version != predecessor.role_schema_version
        or protocol.schema_sha256 != predecessor.role_schema_sha256
        or workflow is None
        or workflow.definition_id != predecessor.workflow_definition_id
        or not workflow.active
        or workflow.definition_key != manifest.preset_key
        or workflow.definition_version != predecessor.workflow_definition_version
        or workflow.definition_hash != predecessor.workflow_definition_sha256
        or bundle is None
        or bundle.bundle_id != predecessor.instruction_bundle_id
        or bundle.bundle_kind != "INSTRUCTION"
        or bundle.bundle_key != "legacy-item-extraction-support"
        or bundle.state != "ACTIVE"
        or prior_bundle is None
        or prior_bundle.bundle_revision_id != predecessor.instruction_bundle_revision_id
        or prior_bundle.bundle_id != predecessor.instruction_bundle_id
        or prior_bundle.bundle_kind != "INSTRUCTION"
        or prior_bundle.state != "RELEASED"
        or prior_bundle.revision_number != predecessor.instruction_revision_number
        or prior_bundle.manifest_sha256 != predecessor.instruction_manifest_sha256
        or prior_bundle.content_sha256 != predecessor.instruction_content_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_PREDECESSOR_STALE",
            "legacy extraction predecessor pointer graph differs",
        )

    try:
        validate_control_contract("execution-preset-revision", prior_preset.canonical_document)
        validate_control_contract("instruction-bundle-manifest", prior_bundle.canonical_document)
        validate_control_contract("worker-capacity-policy-v3", capacity.canonical_document)
        preset_document = ExecutionPresetRevision.model_validate(prior_preset.canonical_document)
        bundle_document = InstructionBundleManifest.model_validate(prior_bundle.canonical_document)
        capacity_document = WorkerCapacityPolicyV3.model_validate(capacity.canonical_document)
        compiled_workflow = compile_definition_data(
            workflow.canonical_definition,
            workflow.source_path,
            {"support"},
        )
    except (JsonSchemaValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_PREDECESSOR_STALE",
            "legacy extraction predecessor document is invalid",
        ) from exc
    components = {component.layer: component for component in bundle_document.components}
    platform = components.get("PLATFORM")
    role = components.get("ROLE")
    policies = tuple(preset_document.role_policies)
    bundle_document_value = bundle_document.model_dump(mode="json")
    bundle_manifest_artifact_sha256 = compute_control_document_artifact_hash(bundle_document_value)
    if (
        preset_document.content_sha256
        != compute_control_document_hash(
            preset_document.model_dump(mode="json"),
            "content_sha256",
        )
        or preset_document.content_sha256 != prior_preset.content_sha256
        or preset_document.content_sha256 != predecessor.preset_content_sha256
        or execution_preset_policy_sha256(preset_document.model_dump(mode="json"))
        != predecessor.preset_policy_sha256
        or bundle_document.content_sha256
        != compute_control_document_hash(
            bundle_document_value,
            "content_sha256",
        )
        or bundle_document.content_sha256 != prior_bundle.content_sha256
        or bundle_document.content_sha256 != predecessor.instruction_content_sha256
        or bundle_manifest_artifact_sha256 != prior_bundle.manifest_sha256
        or bundle_manifest_artifact_sha256 != predecessor.instruction_manifest_sha256
        or capacity_document.content_sha256
        != compute_control_document_hash(
            capacity_document.model_dump(mode="json"),
            "content_sha256",
        )
        or capacity_document.content_sha256 != capacity.content_sha256
        or capacity_document.content_sha256 != predecessor.capacity_policy_sha256
        or compiled_workflow.sha256 != workflow.definition_hash
        or compiled_workflow.sha256 != predecessor.workflow_definition_sha256
        or preset_document.schema_version != prior_preset.schema_version
        or preset_document.preset_id != prior_preset.preset_id
        or preset_document.preset_id != predecessor.preset_id
        or preset_document.preset_revision_id != prior_preset.preset_revision_id
        or preset_document.preset_revision_id != predecessor.preset_revision_id
        or preset_document.revision_number != prior_preset.revision_number
        or preset_document.revision_number != predecessor.preset_revision_number
        or preset_document.state != prior_preset.state
        or preset_document.state != "RELEASED"
        or preset_document.display_name != prior_preset.display_name
        or preset_document.description != prior_preset.description
        or preset_document.capacity_policy_revision_id != prior_preset.capacity_policy_revision_id
        or preset_document.capacity_policy_revision_id != predecessor.capacity_policy_revision_id
        or preset_document.general_knowledge_policy != prior_preset.general_knowledge_policy
        or list(preset_document.compatible_workflow_protocols)
        != prior_preset.compatible_workflow_protocols
        or bundle_document.schema_version != prior_bundle.schema_version
        or bundle_document.bundle_id != prior_bundle.bundle_id
        or bundle_document.bundle_id != predecessor.instruction_bundle_id
        or bundle_document.bundle_revision_id != prior_bundle.bundle_revision_id
        or bundle_document.bundle_revision_id != predecessor.instruction_bundle_revision_id
        or bundle_document.revision_number != prior_bundle.revision_number
        or bundle_document.revision_number != predecessor.instruction_revision_number
        or bundle_document.state != prior_bundle.state
        or bundle_document.state != "RELEASED"
        or capacity_document.schema_version != capacity.schema_version
        or capacity_document.capacity_policy_id != capacity.capacity_policy_id
        or capacity_document.capacity_policy_revision_id != capacity.capacity_policy_revision_id
        or capacity_document.capacity_policy_revision_id != predecessor.capacity_policy_revision_id
        or capacity_document.revision_number != capacity.revision_number
        or capacity_document.state != capacity.state
        or capacity_document.state != "RELEASED"
        or capacity_document.max_configured_slots != capacity.max_configured_slots
        or capacity_document.max_active_codex != capacity.max_active_codex
        or capacity_document.max_active_per_slot != capacity.max_active_per_slot
        or capacity_document.max_active_gpu != capacity.max_active_gpu
        or capacity_document.max_active_knowledge_analysis != capacity.max_active_knowledge_analysis
        or compiled_workflow.definition.schema_version != workflow.schema_version
        or compiled_workflow.definition.definition_key != workflow.definition_key
        or compiled_workflow.definition.definition_key != manifest.preset_key
        or compiled_workflow.definition.definition_version != workflow.definition_version
        or compiled_workflow.definition.definition_version
        != predecessor.workflow_definition_version
        or len(components) != 2
        or platform is None
        or role is None
        or platform.relative_path != "instructions/platform.md"
        or role.relative_path != "instructions/legacy-item-extraction.md"
        or platform.artifact.sha256 != predecessor.platform_instruction_sha256
        or role.artifact.sha256 != predecessor.role_instruction_sha256
        or len(policies) != 1
        or policies[0].role != "support"
        or policies[0].instruction_bundle.manifest_artifact.artifact_id
        != prior_bundle.manifest_artifact_id
        or policies[0].instruction_bundle.manifest_artifact.artifact_revision_id
        != prior_bundle.manifest_artifact_revision_id
        or policies[0].instruction_bundle.bundle_id != predecessor.instruction_bundle_id
        or policies[0].instruction_bundle.bundle_revision_id
        != predecessor.instruction_bundle_revision_id
        or policies[0].instruction_bundle.manifest_sha256 != predecessor.instruction_manifest_sha256
        or policies[0].instruction_bundle.manifest_artifact.sha256
        != policies[0].instruction_bundle.manifest_sha256
        or policies[0].instruction_bundle.manifest_artifact.sha256 != prior_bundle.manifest_sha256
        or policies[0].instruction_bundle.manifest_artifact.sha256
        != predecessor.instruction_manifest_sha256
        or policies[0].instruction_bundle.manifest_artifact.sha256
        != bundle_manifest_artifact_sha256
        or preset_document.capacity_policy_revision_id != predecessor.capacity_policy_revision_id
        or tuple(preset_document.compatible_workflow_protocols)
        != manifest.compatible_workflow_protocols
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_PREDECESSOR_STALE",
            "legacy extraction predecessor policy differs",
        )
    for pointer, expected_schema_ref, expected_media_type in (
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
    ):
        try:
            resolve_control_artifact_pointer(
                session,
                pointer,
                expected_schema_ref=expected_schema_ref,
                expected_media_type=expected_media_type,
            )
        except ControlPlaneError as exc:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_PREDECESSOR_STALE",
                "legacy extraction predecessor Artifact pointer differs",
            ) from exc

    target_bundle_revision_id = _stable_id(
        "instrrev_",
        f"legacy-item-extraction:support:v{manifest.instruction_revision_number}",
    )
    allowed_bundle_currents = {
        predecessor.instruction_bundle_revision_id,
        target_bundle_revision_id,
    }
    if bundle.current_revision_id not in allowed_bundle_currents:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction instruction current pointer differs",
        )
    if bundle.current_revision_id == target_bundle_revision_id:
        _require_partial_successor_bundle(
            session,
            predecessor=predecessor,
            target_revision_id=target_bundle_revision_id,
            target_role_sha256=role_sha256,
        )

    if logical.current_revision_id == predecessor.preset_revision_id:
        return platform.artifact
    current = (
        session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if logical.current_revision_id is not None
        else None
    )
    if (
        current is None
        or current.preset_id != predecessor.preset_id
        or current.state != "RELEASED"
        or not _is_successor_preset_policy(
            current,
            manifest=manifest,
            target_bundle_revision_id=target_bundle_revision_id,
        )
        or bundle.current_revision_id != target_bundle_revision_id
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction preset current pointer differs",
        )
    return platform.artifact


def _require_partial_successor_bundle(
    session: Session,
    *,
    predecessor: LegacyItemExtractionBootstrapPredecessor,
    target_revision_id: str,
    target_role_sha256: str,
) -> None:
    target = session.get(ExecutionBundleRevisionRecord, target_revision_id)
    if (
        target is None
        or target.bundle_id != predecessor.instruction_bundle_id
        or target.bundle_kind != "INSTRUCTION"
        or target.state != "RELEASED"
        or target.revision_number != predecessor.instruction_revision_number + 1
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction partial successor bundle differs",
        )
    try:
        document = InstructionBundleManifest.model_validate(target.canonical_document)
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction partial successor bundle is invalid",
        ) from exc
    components = {component.layer: component for component in document.components}
    platform = components.get("PLATFORM")
    role = components.get("ROLE")
    if (
        len(components) != 2
        or platform is None
        or role is None
        or platform.artifact.sha256 != predecessor.platform_instruction_sha256
        or role.artifact.sha256 != target_role_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction partial successor instruction differs",
        )


def _is_successor_preset_policy(
    revision: ExecutionPresetRevisionRecord,
    *,
    manifest: LegacyItemExtractionBootstrapManifest,
    target_bundle_revision_id: str,
) -> bool:
    predecessor = manifest.predecessor
    if predecessor is None:
        return False
    try:
        document = ExecutionPresetRevision.model_validate(revision.canonical_document)
    except ValueError:
        return False
    policies = tuple(document.role_policies)
    return (
        len(policies) == 1
        and policies[0].role == "support"
        and policies[0].instruction_bundle.bundle_revision_id == target_bundle_revision_id
        and policies[0].reference_bundle is None
        and [
            (candidate.model, candidate.reasoning_effort)
            for candidate in policies[0].model_candidates
        ]
        == [(manifest.model, manifest.reasoning_effort)]
        and policies[0].worker_pool_key == manifest.worker_pool_key
        and policies[0].timeout_seconds == manifest.timeout_seconds
        and policies[0].sandbox == "read-only"
        and policies[0].network == "disabled"
        and document.capacity_policy_revision_id == predecessor.capacity_policy_revision_id
        and document.general_knowledge_policy == manifest.general_knowledge_policy
        and tuple(document.compatible_workflow_protocols) == manifest.compatible_workflow_protocols
    )


def _matches_predecessor_preset(
    revision: ExecutionPresetRevisionRecord,
    predecessor: LegacyItemExtractionBootstrapPredecessor,
) -> bool:
    return (
        revision.preset_id == predecessor.preset_id
        and revision.preset_revision_id == predecessor.preset_revision_id
        and revision.revision_number == predecessor.preset_revision_number
        and revision.state == "RELEASED"
        and revision.content_sha256 == predecessor.preset_content_sha256
        and revision.capacity_policy_revision_id == predecessor.capacity_policy_revision_id
        and execution_preset_policy_sha256(revision.canonical_document)
        == predecessor.preset_policy_sha256
    )


def _require_successor_release_cas(
    session: Session,
    *,
    manifest: LegacyItemExtractionBootstrapManifest,
    target_policy_sha256: str,
) -> None:
    """Hold the preset row lock while proving predecessor-or-exact-replay state."""

    predecessor = manifest.predecessor
    if predecessor is None:
        return
    logical = session.scalar(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_key == manifest.preset_key)
        .with_for_update()
    )
    current = (
        session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if logical is not None and logical.current_revision_id is not None
        else None
    )
    if logical is None or logical.preset_id != predecessor.preset_id or current is None:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction preset CAS target is missing",
        )
    if execution_preset_policy_sha256(current.canonical_document) == target_policy_sha256:
        return
    if not _matches_predecessor_preset(current, predecessor):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "legacy extraction preset CAS predecessor differs",
        )


def _bundle_hashes(
    sessions: sessionmaker[Session],
    bundle_revision_id: str,
) -> tuple[str, str]:
    with sessions() as session:
        revision = session.get(ExecutionBundleRevisionRecord, bundle_revision_id)
        if revision is None or revision.state != "RELEASED":
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "legacy extraction instruction bundle is unavailable",
            )
        return revision.manifest_sha256, revision.content_sha256


def _capacity_hash(sessions: sessionmaker[Session], capacity_revision_id: str) -> str:
    with sessions() as session:
        revision = session.get(WorkerCapacityPolicyRevisionRecord, capacity_revision_id)
        if revision is None or revision.state != "RELEASED":
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "legacy extraction capacity policy is unavailable",
            )
        return revision.content_sha256


def _require_existing_registry_and_binding(
    session: Session,
    *,
    slots: tuple[WorkerSlot, ...],
) -> str:
    """Prove V2 reuses the installed slot registry and slot-06 auth identity."""

    for slot in slots:
        installed = session.get(WorkerSlotRecord, slot.slot_id)
        if (
            installed is None
            or installed.linux_user != slot.linux_user
            or installed.role != slot.role
            or installed.enabled != slot.enabled
            or installed.gpu != slot.gpu
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_SLOT_MISMATCH",
                "legacy extraction installed slot registry differs",
            )
    binding_id = _stable_id("authbinding_", "slot06")
    binding = session.get(CodexAuthBindingRecord, binding_id)
    if binding is None or binding.worker_slot_id != "06":
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_AUTH_BINDING_MISSING",
            "legacy extraction slot-06 auth binding is unavailable",
        )
    return binding_id


def bootstrap_legacy_item_extraction_control_plane(
    engine: Engine,
    *,
    config_directory: Path,
    source_commit: str,
    actor_id: str,
    evaluation_cases_total: int,
    settings: Settings | None = None,
) -> LegacyItemExtractionBootstrapResult:
    """Publish an evaluated source-only preset pinned to slot06 without executing Codex."""

    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "source commit is invalid")
    if not actor_id or len(actor_id) > 128 or not 1 <= evaluation_cases_total <= 10000:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "bootstrap operator input is invalid")
    manifest = load_legacy_item_extraction_bootstrap_manifest(config_directory)
    actual_settings = settings or Settings.from_environment()
    sessions = build_session_factory(engine)
    publisher = ControlArtifactPublisher(engine, actual_settings)
    registry = resolve_worker_configuration(actual_settings).registry
    _require_exact_six_slot_registry(registry.config.slots)
    platform_payload = _read_member(config_directory, manifest.platform_instruction_path)
    role_payload = _read_member(config_directory, manifest.role_instruction_path)
    if manifest.predecessor is not None:
        with sessions() as session:
            platform_artifact = _require_successor_preflight(
                session,
                manifest=manifest,
                platform_sha256="sha256:" + hashlib.sha256(platform_payload).hexdigest(),
                role_sha256="sha256:" + hashlib.sha256(role_payload).hexdigest(),
            )
            auth_binding_id = _require_existing_registry_and_binding(
                session,
                slots=registry.config.slots,
            )
    else:
        platform_artifact = None
        with transaction(sessions) as session:
            for slot in registry.config.slots:
                upsert_worker_slot(
                    session,
                    slot_id=slot.slot_id,
                    linux_user=slot.linux_user,
                    role=slot.role,
                    enabled=slot.enabled,
                    gpu=slot.gpu,
                )
            ensure_protocol_version(
                session,
                "workflow-role/1.14.0",
                role_schema_bundle_hash("workflow-role/1.14.0"),
            )
        capacity_revision_id = _publish_extraction_capacity_policy(
            sessions, slots=registry.config.slots, actor_id=actor_id
        )
        binding_ids = _bootstrap_bindings(
            sessions, slots=registry.config.slots, observed_at=manifest.created_at
        )
        auth_binding_id = binding_ids[5]
    if manifest.predecessor is not None:
        capacity_revision_id = manifest.predecessor.capacity_policy_revision_id
    if platform_artifact is None:
        platform_artifact = _publish_markdown(
            publisher,
            payload=platform_payload,
            logical_name="platform.md",
            schema_ref="eom://schemas/workflow/instruction-member/1.0",
            key="legacy-item-extraction-platform-v1",
            source_commit=source_commit,
            created_at=manifest.created_at,
        )
    role_artifact = _publish_markdown(
        publisher,
        payload=role_payload,
        logical_name="legacy-item-extraction.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key=(
            "legacy-item-extraction-role-v2"
            if manifest.predecessor is not None
            else "legacy-item-extraction-role-v1"
        ),
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    if manifest.predecessor is not None:
        _require_artifact_source_commit(
            sessions,
            pointer=role_artifact,
            source_commit=source_commit,
        )
    instruction = _publish_instruction_bundle(
        publisher,
        sessions,
        role="support",
        platform_artifact=platform_artifact,
        role_artifact=role_artifact,
        identity_key="legacy-item-extraction:support",
        bundle_key="legacy-item-extraction-support",
        role_relative_path=manifest.role_instruction_path,
        source_commit=source_commit,
        actor_id=actor_id,
        created_at=manifest.created_at,
        revision_number=manifest.instruction_revision_number or 1,
        predecessor=(
            BundleRevisionCAS(
                bundle_revision_id=manifest.predecessor.instruction_bundle_revision_id,
                manifest_sha256=manifest.predecessor.instruction_manifest_sha256,
                content_sha256=manifest.predecessor.instruction_content_sha256,
            )
            if manifest.predecessor is not None
            else None
        ),
    )
    role_policies: list[dict[str, object]] = [
        {
            "role": "support",
            "model_candidates": [
                {"model": manifest.model, "reasoning_effort": manifest.reasoning_effort}
            ],
            "instruction_bundle": instruction.model_dump(mode="json"),
            "reference_bundle": None,
            "worker_pool_key": "legacy-extraction",
            "timeout_seconds": manifest.timeout_seconds,
            "sandbox": "read-only",
            "network": "disabled",
        }
    ]
    draft = _find_or_create_draft(
        sessions,
        manifest=manifest,
        role_policies=role_policies,
        capacity_policy_revision_id=capacity_revision_id,
        actor_id=actor_id,
    )
    if manifest.predecessor is not None:
        expected_revision_number = manifest.predecessor.preset_revision_number + (
            2 if draft.state == "RELEASED" else 1
        )
        if draft.revision_number != expected_revision_number:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "legacy extraction preset successor history is not adjacent",
            )
    policy_sha256 = execution_preset_policy_sha256(draft.canonical_document)
    if draft.state == "RELEASED":
        with sessions() as session:
            evaluation = session.scalar(
                select(ExecutionPresetEvaluationRecord)
                .where(
                    ExecutionPresetEvaluationRecord.preset_id == draft.preset_id,
                    ExecutionPresetEvaluationRecord.evaluated_policy_sha256 == policy_sha256,
                    ExecutionPresetEvaluationRecord.outcome == "PASS",
                )
                .order_by(ExecutionPresetEvaluationRecord.completed_at.desc())
            )
            if evaluation is None:
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                    "released legacy extraction preset lacks evaluation evidence",
                )
        released = draft
    else:
        report_document = _build_non_live_evaluation_report(
            preset_revision_id=draft.preset_revision_id,
            policy_sha256=policy_sha256,
            evaluation_cases_total=evaluation_cases_total,
            completed_at=manifest.created_at + timedelta(minutes=1),
        )
        payload = canonical_json_bytes(report_document) + b"\n"
        report_artifact = publisher.publish_bytes(
            payload=payload,
            logical_name="legacy-item-extraction-preset-evaluation.json",
            schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            media_type="application/json",
            artifact_type="control_preset_evaluation",
            idempotency_key=(
                "control-bootstrap:legacy-item-extraction-evaluation:"
                f"{hashlib.sha256(payload).hexdigest()}"
            ),
            created_at=manifest.created_at + timedelta(minutes=1),
            source_commit=source_commit,
        )
        with transaction(sessions) as session:
            evaluation = record_execution_preset_evaluation(
                session,
                document=report_document,
                report_artifact=report_artifact.pointer,
                created_by=actor_id,
            )
            _require_successor_release_cas(
                session,
                manifest=manifest,
                target_policy_sha256=policy_sha256,
            )
            released = release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=actor_id,
                released_at=manifest.created_at + timedelta(minutes=2),
            )
            if manifest.predecessor is not None and (
                released.revision_number != manifest.predecessor.preset_revision_number + 2
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                    "legacy extraction released preset successor is not adjacent",
                )
    instruction_manifest_sha256, instruction_content_sha256 = _bundle_hashes(
        sessions,
        instruction.bundle_revision_id,
    )
    capacity_policy_sha256 = _capacity_hash(sessions, capacity_revision_id)
    return LegacyItemExtractionBootstrapResult(
        preset_id=released.preset_id,
        preset_revision_id=released.preset_revision_id,
        preset_revision_number=released.revision_number,
        preset_policy_sha256=policy_sha256,
        preset_content_sha256=released.content_sha256,
        capacity_policy_revision_id=capacity_revision_id,
        capacity_policy_sha256=capacity_policy_sha256,
        instruction_bundle_id=instruction.bundle_id,
        instruction_bundle_revision_id=instruction.bundle_revision_id,
        instruction_revision_number=manifest.instruction_revision_number or 1,
        instruction_manifest_sha256=instruction_manifest_sha256,
        instruction_content_sha256=instruction_content_sha256,
        evaluation_id=evaluation.evaluation_id,
        auth_binding_id=auth_binding_id,
        source_commit=source_commit,
    )


def _build_non_live_evaluation_report(
    *,
    preset_revision_id: str,
    policy_sha256: str,
    evaluation_cases_total: int,
    completed_at: datetime,
) -> dict[str, object]:
    """Build the existing V1 non-live contract-validation evidence."""

    report_document: dict[str, object] = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": preset_revision_id,
        "evaluated_policy_sha256": policy_sha256,
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "CONTRACT_VALIDATION",
        "cases_total": evaluation_cases_total,
        "cases_passed": evaluation_cases_total,
        "quality_score_permille": 1000,
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "report_sha256": "sha256:" + "0" * 64,
    }
    report_document["report_sha256"] = compute_control_document_hash(
        report_document, "report_sha256"
    )
    return report_document


def _publish_extraction_capacity_policy(
    sessions: sessionmaker[Session], *, slots: tuple[WorkerSlot, ...], actor_id: str
) -> str:
    _require_exact_six_slot_registry(slots)
    policy_id = _stable_id("capacity_", "fixed-host")
    revision_id = _stable_id("capacityrev_", "fixed-host:v3")
    document: dict[str, object] = {
        "schema_version": "worker-capacity-policy/1.2",
        "capacity_policy_id": policy_id,
        "capacity_policy_revision_id": revision_id,
        "revision_number": 3,
        "state": "RELEASED",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 2,
        "pools": [
            {
                "pool_key": "authoring",
                "roles": ["authoring"],
                "slot_keys": ["slot01"],
                "max_active": 1,
            },
            {"pool_key": "review", "roles": ["review"], "slot_keys": ["slot02"], "max_active": 1},
            {"pool_key": "image", "roles": ["image"], "slot_keys": ["slot03"], "max_active": 1},
            {
                "pool_key": "item-management",
                "roles": ["item_management"],
                "slot_keys": ["slot04"],
                "max_active": 1,
            },
            {"pool_key": "support", "roles": ["support"], "slot_keys": ["slot05"], "max_active": 1},
            {
                "pool_key": "legacy-extraction",
                "roles": ["support"],
                "slot_keys": ["slot06"],
                "max_active": 1,
            },
        ],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": EXTRACTION_CAPACITY_CREATED_AT.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    policy = WorkerCapacityPolicyV3.model_validate(document)
    with transaction(sessions) as session:
        existing = session.get(WorkerCapacityPolicyRevisionRecord, revision_id)
        if existing is not None and (
            existing.canonical_document != policy.model_dump(mode="json")
            or existing.content_sha256 != policy.content_sha256
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID", "fixed-host capacity V3 differs"
            )
        record_capacity_policy_revision(
            session,
            policy_key="fixed-host",
            document=policy.model_dump(mode="json"),
            created_by=actor_id,
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=policy_id,
            capacity_policy_revision_id=revision_id,
        )
    return revision_id


def _find_or_create_draft(
    sessions: sessionmaker[Session],
    *,
    manifest: LegacyItemExtractionBootstrapManifest,
    role_policies: list[dict[str, object]],
    capacity_policy_revision_id: str,
    actor_id: str,
) -> ExecutionPresetRevisionRecord:
    preview: dict[str, object] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "0" * 32,
        "preset_revision_id": "execpresetrev_" + "0" * 32,
        "revision_number": 1,
        "state": "DRAFT",
        "display_name": manifest.display_name,
        "description": manifest.description,
        "role_policies": role_policies,
        "capacity_policy_revision_id": capacity_policy_revision_id,
        "general_knowledge_policy": manifest.general_knowledge_policy,
        "compatible_workflow_protocols": list(manifest.compatible_workflow_protocols),
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": manifest.created_at,
    }
    expected_hash = execution_preset_policy_sha256(preview)
    with transaction(sessions) as session:
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == manifest.preset_key)
            .with_for_update()
        )
        revisions = (
            tuple(
                session.scalars(
                    select(ExecutionPresetRevisionRecord)
                    .where(ExecutionPresetRevisionRecord.preset_id == logical.preset_id)
                    .order_by(ExecutionPresetRevisionRecord.revision_number)
                )
            )
            if logical is not None
            else ()
        )
        if logical is not None and logical.state != "ACTIVE":
            raise ControlPlaneError("CONTROL_PRESET_RETIRED", "legacy extraction preset is retired")
        if logical is not None and logical.current_revision_id is not None:
            current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            if (
                current is None
                or current.preset_id != logical.preset_id
                or current.state != "RELEASED"
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT",
                    "released legacy extraction preset pointer differs",
                )
            if execution_preset_policy_sha256(current.canonical_document) == expected_hash:
                return current
            if manifest.predecessor is None or not _matches_predecessor_preset(
                current,
                manifest.predecessor,
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT",
                    "released legacy extraction preset policy differs",
                )
        if (
            logical is not None
            and logical.current_revision_id is None
            and any(revision.state == "RELEASED" for revision in revisions)
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "released legacy extraction preset lacks its current pointer",
            )
        released_matching = [
            revision
            for revision in revisions
            if revision.state == "RELEASED"
            and execution_preset_policy_sha256(revision.canonical_document) == expected_hash
        ]
        if len(released_matching) > 1:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "legacy extraction preset has duplicate released policy revisions",
            )
        if released_matching:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "legacy extraction config targets a non-current released policy",
            )
        matching = [
            revision
            for revision in revisions
            if revision.state == "DRAFT"
            and execution_preset_policy_sha256(revision.canonical_document) == expected_hash
        ]
        if manifest.predecessor is not None:
            future_revisions = {
                revision.preset_revision_id
                for revision in revisions
                if revision.revision_number > manifest.predecessor.preset_revision_number
            }
            expected_future = {
                revision.preset_revision_id
                for revision in matching
                if revision.revision_number == manifest.predecessor.preset_revision_number + 1
            }
            if future_revisions != expected_future:
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT",
                    "legacy extraction preset successor history is not adjacent",
                )
        released_policy_hashes = {
            execution_preset_policy_sha256(revision.canonical_document)
            for revision in revisions
            if revision.state == "RELEASED"
        }
        unresolved_other_drafts = [
            revision
            for revision in revisions
            if revision.state == "DRAFT"
            and revision not in matching
            and execution_preset_policy_sha256(revision.canonical_document)
            not in released_policy_hashes
        ]
        if len(matching) > 1 or unresolved_other_drafts:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "legacy extraction preset draft history differs"
            )
        if matching:
            return matching[0]
        return create_execution_preset_draft(
            session,
            preset_key=manifest.preset_key,
            display_name=manifest.display_name,
            description=manifest.description,
            role_policies=role_policies,
            capacity_policy_revision_id=capacity_policy_revision_id,
            general_knowledge_policy=manifest.general_knowledge_policy,
            compatible_workflow_protocols=list(manifest.compatible_workflow_protocols),
            created_by=actor_id,
            created_at=manifest.created_at,
        )


def _require_exact_six_slot_registry(slots: tuple[WorkerSlot, ...]) -> None:
    actual = {f"slot{slot.slot_id}": (str(slot.role), slot.enabled) for slot in slots}
    expected = {
        "slot01": ("authoring", True),
        "slot02": ("review", True),
        "slot03": ("image", True),
        "slot04": ("item_management", True),
        "slot05": ("support", True),
        "slot06": ("support", True),
    }
    if actual != expected:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_SLOT_MISMATCH",
            "legacy item extraction requires the exact six-slot inventory",
        )
