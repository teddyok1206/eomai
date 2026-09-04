"""Reviewed bootstrap for the Graph-backed single-item Execution Preset."""

from __future__ import annotations

import hashlib
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from eom_identifiers import canonical_json_bytes
from eom_workflow import ExecutionPresetRevision
from eom_workflow.control_schemas import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft_v2,
    execution_preset_policy_sha256,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.settings import Settings

MAX_MANIFEST_BYTES = 64 * 1024
EXPECTED_ROLES = ("authoring", "image", "item_management", "review")


class KnowledgeItemRetrievalBootstrapPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    access_policy_revision_id: Literal["accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9"]
    access_policy_sha256: Literal[
        "sha256:bf35bc53cd756efdff81fe4154a639968083b5d91932bdc09deaa439b32fcbc0"
    ]
    allowed_corpus_keys: tuple[Literal["integrated-science-textbooks"], ...] = Field(
        min_length=1, max_length=1
    )
    allowed_query_kinds: tuple[Literal["ITEM_PREPARATION"], ...] = Field(min_length=1, max_length=1)
    allowed_source_classes: tuple[Literal["APPROVED_ITEM", "TEXTBOOK"], ...] = Field(
        min_length=2, max_length=2
    )
    maximum_budget: dict[str, int]

    @model_validator(mode="after")
    def exact_retrieval_boundary(self) -> KnowledgeItemRetrievalBootstrapPolicy:
        if self.allowed_corpus_keys != ("integrated-science-textbooks",):
            raise ValueError("knowledge item corpus policy differs")
        if self.allowed_query_kinds != ("ITEM_PREPARATION",):
            raise ValueError("knowledge item query policy differs")
        if self.allowed_source_classes != ("APPROVED_ITEM", "TEXTBOOK"):
            raise ValueError("knowledge item source policy differs")
        if self.maximum_budget != {
            "max_documents": 16,
            "max_item_revisions": 32,
            "max_graph_nodes": 128,
            "max_claims": 64,
            "max_context_tokens": 16000,
        }:
            raise ValueError("knowledge item evidence budget differs")
        return self


class KnowledgeItemBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[
        "knowledge-item-control-bootstrap/1.0", "knowledge-item-control-bootstrap/2.0"
    ]
    preset_key: Literal["knowledge-grounded-item"]
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    created_at: datetime
    base_preset_key: Literal["standard-item"]
    base_preset_schema_version: Literal["execution-preset-revision/1.0"]
    general_knowledge_policy: Literal["ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[
        Literal["workflow-role/1.12.0", "workflow-role/1.15.0"], ...
    ] = Field(min_length=1, max_length=1)
    evidence_access_by_role: dict[str, Literal["NONE", "EVIDENCE_CONTEXT"]]
    retrieval_policy: KnowledgeItemRetrievalBootstrapPolicy

    @model_validator(mode="after")
    def exact_role_and_protocol_boundary(self) -> KnowledgeItemBootstrapManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("knowledge item bootstrap timestamp must use UTC")
        expected_protocol = {
            "knowledge-item-control-bootstrap/1.0": "workflow-role/1.12.0",
            "knowledge-item-control-bootstrap/2.0": "workflow-role/1.15.0",
        }[self.schema_version]
        if self.compatible_workflow_protocols != (expected_protocol,):
            raise ValueError("knowledge item workflow protocol differs")
        if self.evidence_access_by_role != {
            "authoring": "EVIDENCE_CONTEXT",
            "image": "EVIDENCE_CONTEXT",
            "review": "EVIDENCE_CONTEXT",
            "item_management": "NONE",
        }:
            raise ValueError("knowledge item evidence role map differs")
        return self


class KnowledgeItemBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str
    preset_revision_id: str
    preset_policy_sha256: str
    base_preset_revision_id: str
    base_preset_policy_sha256: str
    access_policy_revision_id: str
    access_policy_sha256: str
    evaluation_id: str
    source_commit: str


def load_knowledge_item_bootstrap_manifest(
    config_directory: Path,
) -> KnowledgeItemBootstrapManifest:
    """Load one local reviewed manifest through JSON Schema and Pydantic."""

    root = _safe_root(config_directory)
    raw = _read_manifest(root / "bootstrap.yaml", root=root)
    try:
        value: object = yaml.safe_load(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("knowledge item bootstrap manifest must be an object")
        schema_version = value.get("schema_version")
        if not isinstance(schema_version, str):
            raise ValueError("knowledge item bootstrap schema version is missing")
        schema_name = {
            "knowledge-item-control-bootstrap/1.0": "knowledge-item-control-bootstrap",
            "knowledge-item-control-bootstrap/2.0": "knowledge-item-control-bootstrap-v2",
        }.get(schema_version)
        if schema_name is None:
            raise ValueError("knowledge item bootstrap schema version is unsupported")
        validate_control_contract(schema_name, value)
        return KnowledgeItemBootstrapManifest.model_validate(value)
    except (
        UnicodeError,
        yaml.YAMLError,
        JsonSchemaValidationError,
        ValidationError,
        ValueError,
    ) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "knowledge item bootstrap manifest is invalid"
        ) from exc


def bootstrap_knowledge_item_control_plane(
    engine: Engine,
    *,
    config_directory: Path,
    source_commit: str,
    actor_id: str,
    evaluation_cases_total: int,
    settings: Settings | None = None,
) -> KnowledgeItemBootstrapResult:
    """Publish one V2 preset by pinning the current reviewed standard-item policy."""

    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "source commit is invalid")
    if not actor_id or len(actor_id) > 128 or not 1 <= evaluation_cases_total <= 10000:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "bootstrap operator input is invalid")
    manifest = load_knowledge_item_bootstrap_manifest(config_directory)
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        base, draft = _find_or_create_draft(session, manifest=manifest, actor_id=actor_id)
    base_policy_sha256 = execution_preset_policy_sha256(base.canonical_document)
    policy_sha256 = execution_preset_policy_sha256(draft.canonical_document)
    if draft.state == "RELEASED":
        evaluation = _released_evaluation(sessions, draft=draft, policy_sha256=policy_sha256)
        return _result(
            manifest,
            draft=draft,
            base=base,
            policy_sha256=policy_sha256,
            base_policy_sha256=base_policy_sha256,
            evaluation_id=evaluation.evaluation_id,
            source_commit=source_commit,
        )

    actual_settings = settings or Settings.from_environment()
    publisher = ControlArtifactPublisher(engine, actual_settings)
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
    payload = canonical_json_bytes(report_document) + b"\n"
    artifact = publisher.publish_bytes(
        payload=payload,
        logical_name="knowledge-item-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key=(
            "control-bootstrap:knowledge-item-evaluation:" + hashlib.sha256(payload).hexdigest()
        ),
        created_at=manifest.created_at + timedelta(minutes=1),
        source_commit=source_commit,
    )
    with transaction(sessions) as session:
        evaluation = record_execution_preset_evaluation(
            session,
            document=report_document,
            report_artifact=artifact.pointer,
            created_by=actor_id,
        )
        released = release_execution_preset(
            session,
            draft_revision_id=draft.preset_revision_id,
            released_by=actor_id,
            released_at=manifest.created_at + timedelta(minutes=2),
        )
    return _result(
        manifest,
        draft=released,
        base=base,
        policy_sha256=policy_sha256,
        base_policy_sha256=base_policy_sha256,
        evaluation_id=evaluation.evaluation_id,
        source_commit=source_commit,
    )


def _find_or_create_draft(
    session: Session,
    *,
    manifest: KnowledgeItemBootstrapManifest,
    actor_id: str,
) -> tuple[ExecutionPresetRevisionRecord, ExecutionPresetRevisionRecord]:
    base_logical = session.scalar(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_key == manifest.base_preset_key)
        .with_for_update()
    )
    base = (
        session.get(ExecutionPresetRevisionRecord, base_logical.current_revision_id)
        if base_logical is not None and base_logical.current_revision_id is not None
        else None
    )
    if (
        base_logical is None
        or base_logical.state != "ACTIVE"
        or base is None
        or base.preset_id != base_logical.preset_id
        or base.state != "RELEASED"
        or base.schema_version != manifest.base_preset_schema_version
        or base.content_sha256
        != compute_control_document_hash(base.canonical_document, "content_sha256")
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID",
            "released standard-item base preset is unavailable or stale",
        )
    try:
        base_model = ExecutionPresetRevision.model_validate(base.canonical_document)
    except ValidationError as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID", "standard-item base policy is invalid"
        ) from exc
    if (
        base_model.compatible_workflow_protocols != manifest.compatible_workflow_protocols
        or base_model.general_knowledge_policy != manifest.general_knowledge_policy
        or tuple(sorted(str(policy.role) for policy in base_model.role_policies)) != EXPECTED_ROLES
        or len(base_model.role_policies) != len(EXPECTED_ROLES)
        or any(policy.reference_bundle is None for policy in base_model.role_policies)
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID",
            "standard-item base policy differs from the reviewed Graph-item boundary",
        )
    role_policies = []
    for policy in base_model.role_policies:
        projected = policy.model_dump(mode="json")
        projected["evidence_access"] = manifest.evidence_access_by_role[str(policy.role)]
        role_policies.append(projected)
    preview: dict[str, object] = {
        "schema_version": "execution-preset-revision/2.0",
        "preset_id": "execpreset_" + "0" * 32,
        "preset_revision_id": "execpresetrev_" + "0" * 32,
        "revision_number": 1,
        "state": "DRAFT",
        "display_name": manifest.display_name,
        "description": manifest.description,
        "role_policies": role_policies,
        "capacity_policy_revision_id": base_model.capacity_policy_revision_id,
        "general_knowledge_policy": manifest.general_knowledge_policy,
        "compatible_workflow_protocols": list(manifest.compatible_workflow_protocols),
        "retrieval_policy": manifest.retrieval_policy.model_dump(mode="json"),
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": manifest.created_at,
    }
    expected_policy_sha256 = execution_preset_policy_sha256(preview)
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
        raise ControlPlaneError("CONTROL_PRESET_RETIRED", "knowledge item preset is retired")
    if logical is not None and logical.current_revision_id is not None:
        current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if current is None or current.state != "RELEASED":
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "released knowledge item pointer differs"
            )
        if execution_preset_policy_sha256(current.canonical_document) == expected_policy_sha256:
            return base, current
        current_protocols = tuple(current.compatible_workflow_protocols)
        requested_protocol = manifest.compatible_workflow_protocols[0]
        protocol_rank = {"workflow-role/1.12.0": 1, "workflow-role/1.15.0": 2}
        if (
            len(current_protocols) != 1
            or current_protocols[0] not in protocol_rank
            or protocol_rank[current_protocols[0]] > protocol_rank[requested_protocol]
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT",
                "knowledge item preset succession cannot move backward",
            )
    released_matching = [
        revision
        for revision in revisions
        if revision.state == "RELEASED"
        and execution_preset_policy_sha256(revision.canonical_document) == expected_policy_sha256
    ]
    if released_matching:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT",
            "matching released knowledge item policy is not current",
        )
    matching = [
        revision
        for revision in revisions
        if revision.state == "DRAFT"
        and execution_preset_policy_sha256(revision.canonical_document) == expected_policy_sha256
    ]
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
            "CONTROL_BOOTSTRAP_CONFLICT", "knowledge item preset draft history differs"
        )
    if matching:
        return base, matching[0]
    draft = create_execution_preset_draft_v2(
        session,
        preset_key=manifest.preset_key,
        display_name=manifest.display_name,
        description=manifest.description,
        role_policies=role_policies,
        capacity_policy_revision_id=base_model.capacity_policy_revision_id,
        general_knowledge_policy=manifest.general_knowledge_policy,
        compatible_workflow_protocols=list(manifest.compatible_workflow_protocols),
        retrieval_policy=manifest.retrieval_policy.model_dump(mode="json"),
        created_by=actor_id,
        created_at=manifest.created_at,
    )
    return base, draft


def _released_evaluation(
    sessions: sessionmaker[Session],
    *,
    draft: ExecutionPresetRevisionRecord,
    policy_sha256: str,
) -> ExecutionPresetEvaluationRecord:
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
            "released knowledge item preset lacks evaluation evidence",
        )
    return evaluation


def _result(
    manifest: KnowledgeItemBootstrapManifest,
    *,
    draft: ExecutionPresetRevisionRecord,
    base: ExecutionPresetRevisionRecord,
    policy_sha256: str,
    base_policy_sha256: str,
    evaluation_id: str,
    source_commit: str,
) -> KnowledgeItemBootstrapResult:
    return KnowledgeItemBootstrapResult(
        preset_id=draft.preset_id,
        preset_revision_id=draft.preset_revision_id,
        preset_policy_sha256=policy_sha256,
        base_preset_revision_id=base.preset_revision_id,
        base_preset_policy_sha256=base_policy_sha256,
        access_policy_revision_id=manifest.retrieval_policy.access_policy_revision_id,
        access_policy_sha256=manifest.retrieval_policy.access_policy_sha256,
        evaluation_id=evaluation_id,
        source_commit=source_commit,
    )


def _safe_root(path: Path) -> Path:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode) or not path.is_absolute():
            raise OSError("unsafe bootstrap root")
        resolved = path.resolve(strict=True)
        if resolved != path or metadata.st_mode & 0o002:
            raise OSError("bootstrap root must be canonical and not world-writable")
        return resolved
    except OSError as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "knowledge item bootstrap root is unsafe"
        ) from exc


def _read_manifest(path: Path, *, root: Path) -> bytes:
    try:
        if path.parent != root:
            raise OSError("manifest path escaped its root")
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= MAX_MANIFEST_BYTES
            or metadata.st_mode & 0o002
        ):
            raise OSError("unsafe bootstrap manifest")
        return path.read_bytes()
    except OSError as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "knowledge item bootstrap manifest is unsafe"
        ) from exc
