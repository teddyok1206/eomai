"""Idempotent operator bootstrap for the first reviewed standard Execution Preset."""

from __future__ import annotations

import hashlib
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from eom_identifiers import canonical_json_bytes
from eom_workflow import BundleRevisionPointer, ControlArtifactPointer, WorkerCapacityPolicy
from eom_workflow.schemas import role_schema_bundle_hash
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    publish_bundle_revision,
    publish_capacity_policy_revision,
    record_auth_health,
    record_bundle_revision,
    record_capacity_policy_revision,
)
from eom_orchestrator.database import build_session_factory, transaction
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

MAX_BOOTSTRAP_MANIFEST_BYTES = 64 * 1024
MAX_BOOTSTRAP_MEMBER_BYTES = 512 * 1024
EXPECTED_ROLE_SLOTS = {
    "authoring": "slot01",
    "image": "slot03",
    "review": "slot02",
    "item_management": "slot04",
}


class BootstrapRole(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["authoring", "image", "review", "item_management"]
    slot_key: str = Field(pattern=r"^slot0[1-5]$")
    worker_pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    instruction_path: str = Field(pattern=r"^instructions/[a-z0-9-]+\.md$")
    timeout_seconds: int = Field(ge=30, le=7200)


class StandardBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["standard-control-bootstrap/1.0"]
    preset_key: Literal["standard-item"]
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    created_at: datetime
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"]
    general_knowledge_policy: Literal["ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[str, ...] = Field(min_length=1, max_length=16)
    reference_path: str = Field(pattern=r"^references/[a-z0-9-]+\.md$")
    roles: tuple[BootstrapRole, ...] = Field(min_length=4, max_length=4)
    support_slot_key: Literal["slot05"]

    @model_validator(mode="after")
    def exact_fixed_role_map(self) -> StandardBootstrapManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("bootstrap timestamp must use UTC")
        actual = {role.role: role.slot_key for role in self.roles}
        if actual != EXPECTED_ROLE_SLOTS or len(actual) != len(self.roles):
            raise ValueError("bootstrap role and slot map must match fixed identities")
        if len(set(self.compatible_workflow_protocols)) != len(self.compatible_workflow_protocols):
            raise ValueError("bootstrap workflow protocols must be unique")
        return self


class StandardBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    preset_revision_id: str
    preset_policy_sha256: str
    capacity_policy_revision_id: str
    instruction_bundle_revision_ids: tuple[str, ...]
    reference_bundle_revision_id: str
    auth_binding_ids: tuple[str, ...]
    evaluation_id: str
    source_commit: str


class KnowledgeAnalysisBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["knowledge-analysis-control-bootstrap/1.0"]
    preset_key: Literal["knowledge-analysis"]
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    created_at: datetime
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"]
    general_knowledge_policy: Literal["ALLOW_WITH_PROVENANCE", "DENY"]
    compatible_workflow_protocols: tuple[Literal["workflow-role/1.4.0"], ...] = Field(
        min_length=1, max_length=1
    )
    platform_instruction_path: Literal["instructions/platform.md"]
    role_instruction_path: Literal["instructions/knowledge-analysis.md"]
    slot_key: Literal["slot05"]
    worker_pool_key: Literal["support"]
    timeout_seconds: int = Field(ge=30, le=7200)

    @model_validator(mode="after")
    def exact_analysis_contract(self) -> KnowledgeAnalysisBootstrapManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("knowledge analysis bootstrap timestamp must use UTC")
        if self.compatible_workflow_protocols != ("workflow-role/1.4.0",):
            raise ValueError("knowledge analysis bootstrap protocol must be exact")
        return self


class KnowledgeAnalysisBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    preset_revision_id: str
    preset_policy_sha256: str
    capacity_policy_revision_id: str
    instruction_bundle_revision_id: str
    evaluation_id: str
    source_commit: str


def bootstrap_standard_control_plane(
    engine: Engine,
    *,
    config_directory: Path,
    source_commit: str,
    actor_id: str,
    evaluation_cases_total: int,
    settings: Settings | None = None,
) -> StandardBootstrapResult:
    """Publish reviewed inputs and one immutable standard preset without credential access."""

    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "source commit is invalid")
    if not actor_id or len(actor_id) > 128 or not 1 <= evaluation_cases_total <= 10000:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "bootstrap operator input is invalid")
    manifest = load_standard_bootstrap_manifest(config_directory)
    actual_settings = settings or Settings.from_environment()
    sessions = build_session_factory(engine)
    publisher = ControlArtifactPublisher(engine, actual_settings)
    registry = resolve_worker_configuration(actual_settings).registry
    _require_registry(manifest, registry.config.slots)
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

    platform_payload = _read_member(config_directory, "instructions/platform.md")
    platform_artifact = _publish_markdown(
        publisher,
        payload=platform_payload,
        logical_name="platform.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="instruction-platform",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    reference_payload = _read_member(config_directory, manifest.reference_path)
    reference_artifact = _publish_markdown(
        publisher,
        payload=reference_payload,
        logical_name=PurePosixPath(manifest.reference_path).name,
        schema_ref="eom://schemas/knowledge/reference-markdown/1.0",
        key="reference-general-knowledge",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )

    instruction_pointers: dict[str, BundleRevisionPointer] = {}
    for role in manifest.roles:
        role_artifact = _publish_markdown(
            publisher,
            payload=_read_member(config_directory, role.instruction_path),
            logical_name=PurePosixPath(role.instruction_path).name,
            schema_ref="eom://schemas/workflow/instruction-member/1.0",
            key=f"instruction-{role.role}",
            source_commit=source_commit,
            created_at=manifest.created_at,
        )
        instruction_pointers[role.role] = _publish_instruction_bundle(
            publisher,
            sessions,
            role=role.role,
            platform_artifact=platform_artifact,
            role_artifact=role_artifact,
            identity_key=f"standard-item:{role.role}",
            bundle_key=f"standard-item-{role.role}",
            role_relative_path=role.instruction_path,
            source_commit=source_commit,
            actor_id=actor_id,
            created_at=manifest.created_at,
        )
    reference_pointer = _publish_reference_bundle(
        publisher,
        sessions,
        reference_artifact=reference_artifact,
        source_commit=source_commit,
        actor_id=actor_id,
        created_at=manifest.created_at,
    )
    capacity_revision_id = _publish_capacity_policy(
        sessions,
        manifest=manifest,
        actor_id=actor_id,
    )
    binding_ids = _bootstrap_bindings(
        sessions,
        slots=registry.config.slots,
        observed_at=manifest.created_at,
    )

    role_policies: list[dict[str, object]] = []
    for role in manifest.roles:
        role_policies.append(
            {
                "role": role.role,
                "model_candidates": [
                    {"model": manifest.model, "reasoning_effort": manifest.reasoning_effort}
                ],
                "instruction_bundle": instruction_pointers[role.role].model_dump(mode="json"),
                "reference_bundle": reference_pointer.model_dump(mode="json"),
                "worker_pool_key": role.worker_pool_key,
                "timeout_seconds": role.timeout_seconds,
                "sandbox": "read-only",
                "network": "disabled",
            }
        )
    draft = _find_or_create_draft(
        sessions,
        manifest=manifest,
        role_policies=role_policies,
        capacity_policy_revision_id=capacity_revision_id,
        actor_id=actor_id,
    )
    policy_sha256 = execution_preset_policy_sha256(draft.canonical_document)
    if draft.state == "RELEASED":
        with sessions() as session:
            existing_evaluation = session.scalar(
                select(ExecutionPresetEvaluationRecord)
                .where(
                    ExecutionPresetEvaluationRecord.preset_id == draft.preset_id,
                    ExecutionPresetEvaluationRecord.evaluated_policy_sha256 == policy_sha256,
                    ExecutionPresetEvaluationRecord.outcome == "PASS",
                    ExecutionPresetEvaluationRecord.scope.in_(("NON_LIVE", "LIVE_ONE_SHOT")),
                )
                .order_by(
                    ExecutionPresetEvaluationRecord.completed_at.desc(),
                    ExecutionPresetEvaluationRecord.evaluation_id.desc(),
                )
            )
            if existing_evaluation is None:
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                    "released standard preset lacks its evaluation evidence",
                )
            return StandardBootstrapResult(
                preset_id=draft.preset_id,
                preset_revision_id=draft.preset_revision_id,
                preset_policy_sha256=policy_sha256,
                capacity_policy_revision_id=capacity_revision_id,
                instruction_bundle_revision_ids=tuple(
                    instruction_pointers[role.role].bundle_revision_id for role in manifest.roles
                ),
                reference_bundle_revision_id=reference_pointer.bundle_revision_id,
                auth_binding_ids=binding_ids,
                evaluation_id=existing_evaluation.evaluation_id,
                source_commit=source_commit,
            )
    report_document: dict[str, object] = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": draft.preset_revision_id,
        "evaluated_policy_sha256": policy_sha256,
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
        "cases_total": evaluation_cases_total,
        "cases_passed": evaluation_cases_total,
        "quality_score_permille": 1000,
        "completed_at": (manifest.created_at + timedelta(minutes=1))
        .isoformat()
        .replace("+00:00", "Z"),
        "report_sha256": "sha256:" + "0" * 64,
    }
    report_document["report_sha256"] = compute_control_document_hash(
        report_document, "report_sha256"
    )
    report_artifact = publisher.publish_bytes(
        payload=canonical_json_bytes(report_document) + b"\n",
        logical_name="preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key=f"control-bootstrap:evaluation:{report_document['report_sha256']}",
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
        released = release_execution_preset(
            session,
            draft_revision_id=draft.preset_revision_id,
            released_by=actor_id,
            released_at=manifest.created_at + timedelta(minutes=2),
        )
    return StandardBootstrapResult(
        preset_id=released.preset_id,
        preset_revision_id=released.preset_revision_id,
        preset_policy_sha256=policy_sha256,
        capacity_policy_revision_id=capacity_revision_id,
        instruction_bundle_revision_ids=tuple(
            instruction_pointers[role.role].bundle_revision_id for role in manifest.roles
        ),
        reference_bundle_revision_id=reference_pointer.bundle_revision_id,
        auth_binding_ids=binding_ids,
        evaluation_id=evaluation.evaluation_id,
        source_commit=source_commit,
    )


def bootstrap_knowledge_analysis_control_plane(
    engine: Engine,
    *,
    config_directory: Path,
    source_commit: str,
    actor_id: str,
    evaluation_cases_total: int,
    settings: Settings | None = None,
) -> KnowledgeAnalysisBootstrapResult:
    """Publish the reviewed support-only analysis preset without running Codex."""

    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "source commit is invalid")
    if not actor_id or len(actor_id) > 128 or not 1 <= evaluation_cases_total <= 10000:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "bootstrap operator input is invalid")
    manifest = load_knowledge_analysis_bootstrap_manifest(config_directory)
    actual_settings = settings or Settings.from_environment()
    sessions = build_session_factory(engine)
    publisher = ControlArtifactPublisher(engine, actual_settings)
    registry = resolve_worker_configuration(actual_settings).registry
    matching_slots = [
        slot
        for slot in registry.config.slots
        if f"slot{slot.slot_id}" == manifest.slot_key
        and str(slot.role) == "support"
        and slot.enabled
    ]
    if len(registry.config.slots) != 5 or len(matching_slots) != 1:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_SLOT_MISMATCH",
            "knowledge analysis requires the enabled fixed slot05 support identity",
        )
    with transaction(sessions) as session:
        for protocol_version in manifest.compatible_workflow_protocols:
            ensure_protocol_version(
                session,
                protocol_version,
                role_schema_bundle_hash(protocol_version),
            )
    capacity_revision_id = _released_analysis_capacity_policy(sessions)
    platform_artifact = _publish_markdown(
        publisher,
        payload=_read_member(config_directory, manifest.platform_instruction_path),
        logical_name="platform.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="knowledge-analysis-platform-v1",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    role_artifact = _publish_markdown(
        publisher,
        payload=_read_member(config_directory, manifest.role_instruction_path),
        logical_name="knowledge-analysis.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="knowledge-analysis-role-v1",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    instruction = _publish_instruction_bundle(
        publisher,
        sessions,
        role="support",
        platform_artifact=platform_artifact,
        role_artifact=role_artifact,
        identity_key="knowledge-analysis:support",
        bundle_key="knowledge-analysis-support",
        role_relative_path=manifest.role_instruction_path,
        source_commit=source_commit,
        actor_id=actor_id,
        created_at=manifest.created_at,
    )
    role_policies: list[dict[str, object]] = [
        {
            "role": "support",
            "model_candidates": [
                {"model": manifest.model, "reasoning_effort": manifest.reasoning_effort}
            ],
            "instruction_bundle": instruction.model_dump(mode="json"),
            "reference_bundle": None,
            "worker_pool_key": manifest.worker_pool_key,
            "timeout_seconds": manifest.timeout_seconds,
            "sandbox": "read-only",
            "network": "disabled",
        }
    ]
    draft = _find_or_create_analysis_draft(
        sessions,
        manifest=manifest,
        role_policies=role_policies,
        capacity_policy_revision_id=capacity_revision_id,
        actor_id=actor_id,
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
                    ExecutionPresetEvaluationRecord.scope.in_(("NON_LIVE", "LIVE_ONE_SHOT")),
                )
                .order_by(
                    ExecutionPresetEvaluationRecord.completed_at.desc(),
                    ExecutionPresetEvaluationRecord.evaluation_id.desc(),
                )
            )
            if evaluation is None:
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                    "released knowledge analysis preset lacks evaluation evidence",
                )
        return KnowledgeAnalysisBootstrapResult(
            preset_id=draft.preset_id,
            preset_revision_id=draft.preset_revision_id,
            preset_policy_sha256=policy_sha256,
            capacity_policy_revision_id=capacity_revision_id,
            instruction_bundle_revision_id=instruction.bundle_revision_id,
            evaluation_id=evaluation.evaluation_id,
            source_commit=source_commit,
        )
    report_document: dict[str, object] = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": draft.preset_revision_id,
        "evaluated_policy_sha256": policy_sha256,
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
        "cases_total": evaluation_cases_total,
        "cases_passed": evaluation_cases_total,
        "quality_score_permille": 1000,
        "completed_at": (manifest.created_at + timedelta(minutes=1))
        .isoformat()
        .replace("+00:00", "Z"),
        "report_sha256": "sha256:" + "0" * 64,
    }
    report_document["report_sha256"] = compute_control_document_hash(
        report_document, "report_sha256"
    )
    report_payload = canonical_json_bytes(report_document) + b"\n"
    report_artifact = publisher.publish_bytes(
        payload=report_payload,
        logical_name="knowledge-analysis-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key=(
            "control-bootstrap:knowledge-analysis-evaluation:"
            f"{hashlib.sha256(report_payload).hexdigest()}"
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
        released = release_execution_preset(
            session,
            draft_revision_id=draft.preset_revision_id,
            released_by=actor_id,
            released_at=manifest.created_at + timedelta(minutes=2),
        )
    return KnowledgeAnalysisBootstrapResult(
        preset_id=released.preset_id,
        preset_revision_id=released.preset_revision_id,
        preset_policy_sha256=policy_sha256,
        capacity_policy_revision_id=capacity_revision_id,
        instruction_bundle_revision_id=instruction.bundle_revision_id,
        evaluation_id=evaluation.evaluation_id,
        source_commit=source_commit,
    )


def load_standard_bootstrap_manifest(config_directory: Path) -> StandardBootstrapManifest:
    root = _safe_root(config_directory)
    raw = _read_file(root / "bootstrap.yaml", root=root, max_bytes=MAX_BOOTSTRAP_MANIFEST_BYTES)
    try:
        value: object = yaml.safe_load(raw.decode("utf-8"))
        return StandardBootstrapManifest.model_validate(value)
    except (UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "standard bootstrap manifest is invalid"
        ) from exc


def load_knowledge_analysis_bootstrap_manifest(
    config_directory: Path,
) -> KnowledgeAnalysisBootstrapManifest:
    root = _safe_root(config_directory)
    raw = _read_file(root / "bootstrap.yaml", root=root, max_bytes=MAX_BOOTSTRAP_MANIFEST_BYTES)
    try:
        value: object = yaml.safe_load(raw.decode("utf-8"))
        return KnowledgeAnalysisBootstrapManifest.model_validate(value)
    except (UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID",
            "knowledge analysis bootstrap manifest is invalid",
        ) from exc


def _publish_markdown(
    publisher: ControlArtifactPublisher,
    *,
    payload: bytes,
    logical_name: str,
    schema_ref: str,
    key: str,
    source_commit: str,
    created_at: datetime,
) -> ControlArtifactPointer:
    digest = hashlib.sha256(payload).hexdigest()
    return publisher.publish_bytes(
        payload=payload,
        logical_name=logical_name,
        schema_ref=schema_ref,
        media_type="text/markdown",
        artifact_type="control_markdown",
        idempotency_key=f"control-bootstrap:{key}:{digest}",
        created_at=created_at,
        source_commit=source_commit,
    ).pointer


def _publish_instruction_bundle(
    publisher: ControlArtifactPublisher,
    sessions: sessionmaker[Session],
    *,
    role: str,
    platform_artifact: ControlArtifactPointer,
    role_artifact: ControlArtifactPointer,
    identity_key: str,
    bundle_key: str,
    role_relative_path: str,
    source_commit: str,
    actor_id: str,
    created_at: datetime,
) -> BundleRevisionPointer:
    bundle_id = _stable_id("instrbundle_", identity_key)
    revision_id = _stable_id("instrrev_", f"{identity_key}:v1")
    document: dict[str, object] = {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": bundle_id,
        "bundle_revision_id": revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "components": [
            {
                "layer": "PLATFORM",
                "relative_path": "instructions/platform.md",
                "artifact": platform_artifact.model_dump(mode="json"),
            },
            {
                "layer": "ROLE",
                "relative_path": role_relative_path,
                "artifact": role_artifact.model_dump(mode="json"),
            },
        ],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    payload = canonical_json_bytes(document) + b"\n"
    manifest = publisher.publish_bytes(
        payload=payload,
        logical_name="instruction-bundle.json",
        schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
        media_type="application/json",
        artifact_type="control_instruction_bundle",
        idempotency_key=f"control-bootstrap:instruction-bundle:{hashlib.sha256(payload).hexdigest()}",
        created_at=created_at,
        source_commit=source_commit,
    ).pointer
    with transaction(sessions) as session:
        revision = record_bundle_revision(
            session,
            bundle_key=bundle_key,
            manifest_artifact=manifest,
            document=document,
            created_by=actor_id,
        )
        publish_bundle_revision(
            session,
            bundle_id=revision.bundle_id,
            bundle_revision_id=revision.bundle_revision_id,
        )
    return BundleRevisionPointer(
        bundle_id=bundle_id,
        bundle_revision_id=revision_id,
        manifest_artifact=manifest,
        manifest_sha256=manifest.sha256,
    )


def _publish_reference_bundle(
    publisher: ControlArtifactPublisher,
    sessions: sessionmaker[Session],
    *,
    reference_artifact: ControlArtifactPointer,
    source_commit: str,
    actor_id: str,
    created_at: datetime,
) -> BundleRevisionPointer:
    bundle_id = _stable_id("refbundle_", "standard-item:general-knowledge")
    revision_id = _stable_id("refrev_", "standard-item:general-knowledge:v1")
    document: dict[str, object] = {
        "schema_version": "reference-bundle-manifest/1.0",
        "bundle_id": bundle_id,
        "bundle_revision_id": revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "entries": [
            {
                "reference_key": "general-knowledge-provenance",
                "source_class": "INTERNAL_GUIDE",
                "relative_path": "references/general-knowledge-provenance.md",
                "source_logical_id": _stable_id("internalguide_", "general-knowledge"),
                "source_revision_id": _stable_id("internalguiderev_", "general-knowledge:v1"),
                "rights_policy_revision_id": _stable_id("rightsrev_", "internal-guidance:v1"),
                "artifact": reference_artifact.model_dump(mode="json"),
            }
        ],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    payload = canonical_json_bytes(document) + b"\n"
    manifest = publisher.publish_bytes(
        payload=payload,
        logical_name="reference-bundle.json",
        schema_ref="eom://schemas/workflow/reference-bundle-manifest/1.0",
        media_type="application/json",
        artifact_type="control_reference_bundle",
        idempotency_key=f"control-bootstrap:reference-bundle:{hashlib.sha256(payload).hexdigest()}",
        created_at=created_at,
        source_commit=source_commit,
    ).pointer
    with transaction(sessions) as session:
        revision = record_bundle_revision(
            session,
            bundle_key="standard-item-general-knowledge",
            manifest_artifact=manifest,
            document=document,
            created_by=actor_id,
        )
        publish_bundle_revision(
            session,
            bundle_id=revision.bundle_id,
            bundle_revision_id=revision.bundle_revision_id,
        )
    return BundleRevisionPointer(
        bundle_id=bundle_id,
        bundle_revision_id=revision_id,
        manifest_artifact=manifest,
        manifest_sha256=manifest.sha256,
    )


def _publish_capacity_policy(
    sessions: sessionmaker[Session], *, manifest: StandardBootstrapManifest, actor_id: str
) -> str:
    policy_id = _stable_id("capacity_", "fixed-host")
    revision_id = _stable_id("capacityrev_", "fixed-host:v1")
    pools = [
        {
            "pool_key": role.worker_pool_key,
            "roles": [role.role],
            "slot_keys": [role.slot_key],
            "max_active": 1,
        }
        for role in manifest.roles
    ]
    pools.append(
        {
            "pool_key": "support",
            "roles": ["support"],
            "slot_keys": [manifest.support_slot_key],
            "max_active": 1,
        }
    )
    document: dict[str, object] = {
        "schema_version": "worker-capacity-policy/1.0",
        "capacity_policy_id": policy_id,
        "capacity_policy_revision_id": revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "max_configured_slots": 5,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 1,
        "pools": pools,
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": manifest.created_at.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    with transaction(sessions) as session:
        record_capacity_policy_revision(
            session,
            policy_key="fixed-host",
            document=document,
            created_by=actor_id,
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=policy_id,
            capacity_policy_revision_id=revision_id,
        )
    return revision_id


def _bootstrap_bindings(
    sessions: sessionmaker[Session], *, slots: tuple[WorkerSlot, ...], observed_at: datetime
) -> tuple[str, ...]:
    binding_ids: list[str] = []
    with transaction(sessions) as session:
        for slot in slots:
            slot_id = slot.slot_id
            binding_id = _stable_id("authbinding_", f"slot{slot_id}")
            existing = session.get(CodexAuthBindingRecord, binding_id)
            if existing is None:
                record_auth_health(
                    session,
                    document={
                        "schema_version": "codex-auth-health-view/1.0",
                        "binding_id": binding_id,
                        "slot_key": f"slot{slot_id}",
                        "account_label": f"codex-slot-{slot_id}",
                        "state": "STALE",
                        "reason_code": "BOOTSTRAP_OBSERVATION_REQUIRED",
                        "codex_cli_version": "0.0.0",
                        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                        "valid_until": (observed_at + timedelta(minutes=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    },
                )
            elif (
                existing.worker_slot_id != slot_id
                or existing.account_label != f"codex-slot-{slot_id}"
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT", "Codex auth binding identity differs"
                )
            binding_ids.append(binding_id)
    return tuple(binding_ids)


def _find_or_create_draft(
    sessions: sessionmaker[Session],
    *,
    manifest: StandardBootstrapManifest,
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
    expected_policy_sha256 = execution_preset_policy_sha256(preview)
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
            raise ControlPlaneError("CONTROL_PRESET_RETIRED", "standard preset is retired")
        if logical is not None and logical.current_revision_id is not None:
            current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            if (
                current is None
                or current.state != "RELEASED"
                or execution_preset_policy_sha256(current.canonical_document)
                != expected_policy_sha256
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT", "released standard preset policy differs"
                )
            return current
        matching = [
            revision
            for revision in revisions
            if revision.state == "DRAFT"
            and execution_preset_policy_sha256(revision.canonical_document)
            == expected_policy_sha256
        ]
        if len(matching) > 1 or (revisions and not matching):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "standard preset draft history differs"
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


def _released_analysis_capacity_policy(sessions: sessionmaker[Session]) -> str:
    with sessions() as session:
        logical = session.scalar(
            select(WorkerCapacityPolicyRecord).where(
                WorkerCapacityPolicyRecord.policy_key == "fixed-host"
            )
        )
        revision = (
            session.get(WorkerCapacityPolicyRevisionRecord, logical.current_revision_id)
            if logical is not None and logical.current_revision_id is not None
            else None
        )
        if (
            logical is None
            or logical.state != "ACTIVE"
            or revision is None
            or revision.capacity_policy_id != logical.capacity_policy_id
            or revision.state != "RELEASED"
        ):
            raise ControlPlaneError(
                "CONTROL_CAPACITY_POLICY_MISSING",
                "released fixed-host capacity policy is unavailable",
            )
        policy = WorkerCapacityPolicy.model_validate(revision.canonical_document)
        support = [pool for pool in policy.pools if pool.pool_key == "support"]
        if (
            policy.content_sha256 != revision.content_sha256
            or policy.max_active_knowledge_analysis != 1
            or len(support) != 1
            or support[0].roles != ("support",)
            or support[0].slot_keys != ("slot05",)
            or support[0].max_active != 1
        ):
            raise ControlPlaneError(
                "CONTROL_CAPACITY_POLICY_INVALID",
                "fixed-host knowledge analysis capacity contract differs",
            )
        return revision.capacity_policy_revision_id


def _find_or_create_analysis_draft(
    sessions: sessionmaker[Session],
    *,
    manifest: KnowledgeAnalysisBootstrapManifest,
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
    expected_policy_sha256 = execution_preset_policy_sha256(preview)
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
            raise ControlPlaneError("CONTROL_PRESET_RETIRED", "knowledge preset is retired")
        if logical is not None and logical.current_revision_id is not None:
            current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            if (
                current is None
                or current.state != "RELEASED"
                or execution_preset_policy_sha256(current.canonical_document)
                != expected_policy_sha256
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT",
                    "released knowledge analysis preset policy differs",
                )
            return current
        matching = [
            revision
            for revision in revisions
            if revision.state == "DRAFT"
            and execution_preset_policy_sha256(revision.canonical_document)
            == expected_policy_sha256
        ]
        if len(matching) > 1 or (revisions and not matching):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "knowledge analysis preset draft history differs",
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


def _require_registry(manifest: StandardBootstrapManifest, slots: tuple[WorkerSlot, ...]) -> None:
    actual = {f"slot{slot.slot_id}": (str(slot.role), slot.enabled) for slot in slots}
    expected = {**EXPECTED_ROLE_SLOTS, "support": manifest.support_slot_key}
    mismatched = any(actual.get(slot_key) != (role, True) for role, slot_key in expected.items())
    if len(actual) != 5 or mismatched:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_SLOT_MISMATCH", "fixed worker inventory differs from bootstrap"
        )


def _stable_id(prefix: str, key: str) -> str:
    return prefix + hashlib.sha256(f"eom-standard-control-v1:{key}".encode()).hexdigest()[:32]


def _safe_root(path: Path) -> Path:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode) or not path.is_absolute():
            raise OSError("unsafe bootstrap root")
        resolved = path.resolve(strict=True)
        if resolved != path:
            raise OSError("bootstrap root must be canonical")
        return resolved
    except OSError as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "standard bootstrap root is unsafe"
        ) from exc


def _read_member(root: Path, relative_path: str) -> bytes:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "bootstrap member path is unsafe")
    return _read_file(
        root.joinpath(*relative.parts), root=root, max_bytes=MAX_BOOTSTRAP_MEMBER_BYTES
    )


def _read_file(path: Path, *, root: Path, max_bytes: int) -> bytes:
    try:
        relative = path.relative_to(root)
        current = root
        for component in relative.parts[:-1]:
            current /= component
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise OSError("unsafe bootstrap parent")
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= max_bytes
            or metadata.st_mode & 0o002
        ):
            raise OSError("unsafe bootstrap member")
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "standard bootstrap member is unsafe"
        ) from exc
