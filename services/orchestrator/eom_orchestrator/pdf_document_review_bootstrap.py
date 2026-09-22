"""Idempotent control-plane bootstrap for immutable PDF document review."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from eom_identifiers import canonical_json_bytes
from eom_workflow import AgentStep, ExecutionPresetRevision, compile_definition_data
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.schemas import result_schema_protocol, role_schema_bundle_hash
from eom_workflow_runner.models import WorkflowDefinitionRecord
from pydantic import BaseModel, ConfigDict, Field, model_validator
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
)
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.fixed_host_capacity_bootstrap import (
    publish_fixed_host_capacity_v4,
    require_exact_six_slots,
)
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    execution_preset_policy_sha256,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.repository import ensure_protocol_version, upsert_worker_slot
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import Settings


class PdfDocumentReviewBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["pdf-document-review-control-bootstrap/1.0"]
    preset_key: Literal["pdf-document-review"]
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    created_at: datetime
    model: Literal["gpt-5.6-terra"]
    reasoning_effort: Literal["xhigh"]
    general_knowledge_policy: Literal["ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[Literal["workflow-role/1.25.0"], ...] = Field(
        min_length=1,
        max_length=1,
    )
    platform_instruction_path: Literal["instructions/platform.md"]
    role_instruction_path: Literal["instructions/pdf-document-review.md"]
    slot_key: Literal["slot06"]
    worker_pool_key: Literal["customer-support"]
    timeout_seconds: Literal[3600]

    @model_validator(mode="after")
    def exact_policy(self) -> PdfDocumentReviewBootstrapManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("PDF document-review bootstrap timestamp must use UTC")
        if self.compatible_workflow_protocols != ("workflow-role/1.25.0",):
            raise ValueError("PDF document-review bootstrap protocol must be exact")
        return self


class PdfDocumentReviewBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    preset_revision_id: str
    preset_content_sha256: str
    capacity_policy_revision_id: str
    capacity_policy_sha256: str
    instruction_bundle_id: str
    instruction_bundle_revision_id: str
    instruction_manifest_sha256: str
    evaluation_id: str
    auth_binding_id: str
    source_commit: str


def load_pdf_document_review_bootstrap_manifest(
    config_directory: Path,
) -> PdfDocumentReviewBootstrapManifest:
    root = _safe_root(config_directory)
    raw = _read_file(root / "bootstrap.yaml", root=root, max_bytes=MAX_BOOTSTRAP_MANIFEST_BYTES)
    try:
        value: object = yaml.safe_load(raw.decode("utf-8"))
        if isinstance(value, dict) and isinstance(value.get("created_at"), datetime):
            value = dict(value)
            value["created_at"] = value["created_at"].isoformat().replace("+00:00", "Z")
        validate_control_contract("pdf-document-review-control-bootstrap", value)
        return PdfDocumentReviewBootstrapManifest.model_validate(value)
    except (UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID",
            "PDF document-review bootstrap manifest is invalid",
        ) from exc


def bootstrap_pdf_document_review_control_plane(
    engine: Engine,
    *,
    config_directory: Path,
    source_commit: str,
    actor_id: str,
    settings: Settings | None = None,
) -> PdfDocumentReviewBootstrapResult:
    """Publish the reviewed slot06 PDF policy without starting a worker."""

    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "source commit is invalid")
    if not actor_id or len(actor_id) > 128:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "bootstrap actor is invalid")
    manifest = load_pdf_document_review_bootstrap_manifest(config_directory)
    actual_settings = settings or Settings.from_environment()
    sessions = build_session_factory(engine)
    publisher = ControlArtifactPublisher(engine, actual_settings)
    slots = resolve_worker_configuration(actual_settings).registry.config.slots
    require_exact_six_slots(slots)

    with transaction(sessions) as session:
        for slot in slots:
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
            "workflow-role/1.25.0",
            role_schema_bundle_hash("workflow-role/1.25.0"),
        )
        definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == "pdf-document-review",
                WorkflowDefinitionRecord.definition_version == "1.0.0",
                WorkflowDefinitionRecord.active.is_(True),
            )
        )
        if definition is None:
            raise ControlPlaneError(
                "CONTROL_WORKFLOW_NOT_PUBLISHED",
                "PDF document-review Workflow definition is not active",
            )
        compiled = compile_definition_data(
            definition.canonical_definition,
            definition.source_path,
            {"support"},
        )
        protocols = {
            result_schema_protocol(step.result_schema)
            for step in compiled.definition.steps
            if isinstance(step, AgentStep)
        }
        if protocols != {"workflow-role/1.25.0"}:
            raise ControlPlaneError(
                "CONTROL_WORKFLOW_PROTOCOL_INVALID",
                "PDF document-review Workflow protocol differs",
            )

    capacity_revision_id = publish_fixed_host_capacity_v4(
        sessions,
        slots=slots,
        actor_id=actor_id,
    )
    binding_ids = _bootstrap_bindings(
        sessions,
        slots=slots,
        observed_at=manifest.created_at,
    )
    platform_artifact = _publish_markdown(
        publisher,
        payload=_read_member(config_directory, manifest.platform_instruction_path),
        logical_name="platform.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="pdf-document-review-platform-v1",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    role_artifact = _publish_markdown(
        publisher,
        payload=_read_member(config_directory, manifest.role_instruction_path),
        logical_name="pdf-document-review.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="pdf-document-review-role-v1",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    for pointer in (platform_artifact, role_artifact):
        _require_artifact_source_commit(
            sessions,
            pointer=pointer,
            source_commit=source_commit,
        )
    instruction = _publish_instruction_bundle(
        publisher,
        sessions,
        role="support",
        platform_artifact=platform_artifact,
        role_artifact=role_artifact,
        identity_key="pdf-document-review:support",
        bundle_key="pdf-document-review-support",
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
    draft_or_release = _find_or_create_exact_preset(
        sessions,
        manifest=manifest,
        role_policies=role_policies,
        capacity_policy_revision_id=capacity_revision_id,
        actor_id=actor_id,
    )
    policy_sha256 = execution_preset_policy_sha256(draft_or_release.canonical_document)
    if draft_or_release.state == "RELEASED":
        with sessions() as session:
            evaluation = session.scalar(
                select(ExecutionPresetEvaluationRecord)
                .where(
                    ExecutionPresetEvaluationRecord.preset_id == draft_or_release.preset_id,
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
                    "released PDF document-review preset lacks evaluation evidence",
                )
        released = draft_or_release
    else:
        report = _evaluation_report(
            preset_revision_id=draft_or_release.preset_revision_id,
            policy_sha256=policy_sha256,
            completed_at=manifest.created_at + timedelta(minutes=1),
        )
        payload = canonical_json_bytes(report) + b"\n"
        report_artifact = publisher.publish_bytes(
            payload=payload,
            logical_name="pdf-document-review-preset-evaluation.json",
            schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            media_type="application/json",
            artifact_type="control_preset_evaluation",
            idempotency_key=(
                "control-bootstrap:pdf-document-review-evaluation:"
                f"{hashlib.sha256(payload).hexdigest()}"
            ),
            created_at=manifest.created_at + timedelta(minutes=1),
            source_commit=source_commit,
        )
        with transaction(sessions) as session:
            evaluation = record_execution_preset_evaluation(
                session,
                document=report,
                report_artifact=report_artifact.pointer,
                created_by=actor_id,
            )
            released = release_execution_preset(
                session,
                draft_revision_id=draft_or_release.preset_revision_id,
                released_by=actor_id,
                released_at=manifest.created_at + timedelta(minutes=2),
            )
    with sessions() as session:
        capacity = session.get(WorkerCapacityPolicyRevisionRecord, capacity_revision_id)
        bundle = session.get(ExecutionBundleRevisionRecord, instruction.bundle_revision_id)
        if capacity is None or bundle is None:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "PDF document-review control records are missing",
            )
        return PdfDocumentReviewBootstrapResult(
            preset_id=released.preset_id,
            preset_revision_id=released.preset_revision_id,
            preset_content_sha256=released.content_sha256,
            capacity_policy_revision_id=capacity_revision_id,
            capacity_policy_sha256=capacity.content_sha256,
            instruction_bundle_id=instruction.bundle_id,
            instruction_bundle_revision_id=instruction.bundle_revision_id,
            instruction_manifest_sha256=bundle.manifest_sha256,
            evaluation_id=evaluation.evaluation_id,
            auth_binding_id=binding_ids[5],
            source_commit=source_commit,
        )


def _find_or_create_exact_preset(
    sessions: sessionmaker[Session],
    *,
    manifest: PdfDocumentReviewBootstrapManifest,
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
    preview["content_sha256"] = compute_control_document_hash(preview, "content_sha256")
    expected_policy_hash = execution_preset_policy_sha256(
        ExecutionPresetRevision.model_validate(preview)
    )
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
            raise ControlPlaneError("CONTROL_PRESET_RETIRED", "PDF review preset is retired")
        if logical is not None and logical.current_revision_id is not None:
            current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            if current is None or current.state != "RELEASED":
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT",
                    "PDF review released preset pointer differs",
                )
            if execution_preset_policy_sha256(current.canonical_document) == expected_policy_hash:
                return current
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "PDF review released preset policy differs",
            )
        if any(revision.state == "RELEASED" for revision in revisions):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "PDF review released preset lacks its current pointer",
            )
        matching_drafts = [
            revision
            for revision in revisions
            if revision.state == "DRAFT"
            and execution_preset_policy_sha256(revision.canonical_document) == expected_policy_hash
        ]
        if len(matching_drafts) > 1:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "PDF review preset draft policy is duplicated",
            )
        if matching_drafts:
            if any(revision.state != "DRAFT" for revision in revisions):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT",
                    "PDF review preset history differs",
                )
            return matching_drafts[0]
        if revisions:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "PDF review preset already has a different policy",
            )
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


def _evaluation_report(
    *,
    preset_revision_id: str,
    policy_sha256: str,
    completed_at: datetime,
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": preset_revision_id,
        "evaluated_policy_sha256": policy_sha256,
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "CONTRACT_VALIDATION",
        "cases_total": 1,
        "cases_passed": 1,
        "quality_score_permille": None,
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "report_sha256": "sha256:" + "0" * 64,
    }
    document["report_sha256"] = compute_control_document_hash(document, "report_sha256")
    return document
