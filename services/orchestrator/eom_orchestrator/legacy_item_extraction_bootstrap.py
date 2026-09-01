"""Idempotent control-plane bootstrap for isolated legacy item extraction."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from eom_identifiers import canonical_json_bytes
from eom_workflow import WorkerCapacityPolicyV3
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.schemas import role_schema_bundle_hash
from jsonschema import ValidationError as JsonSchemaValidationError
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
    _safe_root,
    _stable_id,
)
from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    publish_capacity_policy_revision,
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

EXTRACTION_CAPACITY_CREATED_AT = datetime(2026, 9, 1, tzinfo=UTC)


class LegacyItemExtractionBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["legacy-item-extraction-control-bootstrap/1.0"]
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

    @model_validator(mode="after")
    def exact_immutable_contract(self) -> LegacyItemExtractionBootstrapManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("legacy extraction bootstrap timestamp must use UTC")
        if self.compatible_workflow_protocols != ("workflow-role/1.14.0",):
            raise ValueError("legacy extraction bootstrap protocol must be exact")
        return self


class LegacyItemExtractionBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    preset_revision_id: str
    preset_policy_sha256: str
    capacity_policy_revision_id: str
    instruction_bundle_revision_id: str
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
        validate_control_contract("legacy-item-extraction-control-bootstrap", value)
        return LegacyItemExtractionBootstrapManifest.model_validate(value)
    except (UnicodeError, yaml.YAMLError, JsonSchemaValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "legacy item extraction bootstrap manifest is invalid"
        ) from exc


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
    platform_artifact = _publish_markdown(
        publisher,
        payload=_read_member(config_directory, manifest.platform_instruction_path),
        logical_name="platform.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="legacy-item-extraction-platform-v1",
        source_commit=source_commit,
        created_at=manifest.created_at,
    )
    role_artifact = _publish_markdown(
        publisher,
        payload=_read_member(config_directory, manifest.role_instruction_path),
        logical_name="legacy-item-extraction.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        key="legacy-item-extraction-role-v1",
        source_commit=source_commit,
        created_at=manifest.created_at,
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
        report_document: dict[str, object] = {
            "schema_version": "execution-preset-evaluation-report/1.0",
            "evaluated_preset_revision_id": draft.preset_revision_id,
            "evaluated_policy_sha256": policy_sha256,
            "scope": "NON_LIVE",
            "outcome": "PASS",
            "summary_code": "LEGACY_EXTRACTION_CONTRACT_ACCEPTANCE",
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
            released = release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=actor_id,
                released_at=manifest.created_at + timedelta(minutes=2),
            )
    return LegacyItemExtractionBootstrapResult(
        preset_id=released.preset_id,
        preset_revision_id=released.preset_revision_id,
        preset_policy_sha256=policy_sha256,
        capacity_policy_revision_id=capacity_revision_id,
        instruction_bundle_revision_id=instruction.bundle_revision_id,
        evaluation_id=evaluation.evaluation_id,
        auth_binding_id=auth_binding_id,
        source_commit=source_commit,
    )


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
        matching = [
            revision
            for revision in revisions
            if revision.state in {"DRAFT", "RELEASED"}
            and execution_preset_policy_sha256(revision.canonical_document) == expected_hash
        ]
        if len(matching) > 1:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "legacy extraction preset history is ambiguous"
            )
        if matching:
            return matching[0]
        if any(revision.state == "DRAFT" for revision in revisions):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "legacy extraction has another unresolved draft"
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
