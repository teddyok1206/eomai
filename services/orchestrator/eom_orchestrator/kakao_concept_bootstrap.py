"""Publish the optional concept preset through existing Control owners, without model execution."""

import hashlib
import re
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path

from eom_identifiers import canonical_json_bytes
from eom_workflow import ExecutionPresetEvaluationReport, ExecutionPresetRevision
from eom_workflow.control_plane import BundleRevisionPointer, ControlArtifactPointer
from eom_workflow.kakao_concept_request import CONCEPT_ROLE_PROTOCOL
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.repository import admitted_workflow_definition
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from .artifact_publication_lock import artifact_publication_lock
from .control_artifacts import ControlArtifactPublisher
from .control_bootstrap import (
    _publish_instruction_bundle,
    _read_file,
    _safe_root,
)
from .control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from .control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    capacity_worker_role_clause,
    compute_control_document_hash,
    resolve_released_instruction_bundle,
)
from .database import build_session_factory
from .preset_lifecycle import (
    create_execution_preset_draft,
    execution_preset_policy_sha256,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from .preset_model_selection import Preset, validated_preset
from .repository import ensure_protocol_version
from .settings import Settings

PRESET_KEY = "kakao-concepts"
DISPLAY_NAME = "KakaoTalk 교과서 개념 추천"
DESCRIPTION = "공유 슬롯에서 질문의 교과서 근거로 설명 초안을 준비합니다."


class KakaoConceptBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preset_id: str
    preset_revision_id: str
    preset_sha256: str
    base_preset_revision_id: str
    instruction_bundle_revision_id: str
    capacity_policy_revision_id: str
    evaluation_id: str
    source_commit: str


def _baseline(
    session: Session,
    revision_id: str,
    expected_sha256: str,
) -> tuple[Preset, ControlArtifactPointer]:
    row = session.get(ExecutionPresetRevisionRecord, revision_id)
    if (
        admitted_workflow_definition(
            session, definition_key="kakao-concepts", definition_version="1.0.0"
        )
        is None
    ):
        raise ControlPlaneError(
            "CONTROL_WORKFLOW_NOT_PUBLISHED", "concept definition must be admitted first"
        )
    logical = session.get(ExecutionPresetRecord, row.preset_id) if row else None
    if (
        row is None
        or logical is None
        or logical.state != "ACTIVE"
        or logical.current_revision_id != revision_id
        or row.content_sha256 != expected_sha256
    ):
        raise ControlPlaneError("CONTROL_PRESET_POINTER_STALE", "support baseline changed")
    base = validated_preset(row)
    policies = [policy for policy in base.role_policies if policy.role == "support"]
    if base.state != "RELEASED" or len(policies) != 1:
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "released support baseline required"
        )
    capacity = session.get(WorkerCapacityPolicyRevisionRecord, base.capacity_policy_revision_id)
    if capacity is None or capacity.schema_version != "worker-capacity-policy/1.7":
        raise ControlPlaneError(
            "CONTROL_CAPACITY_ROLE_MISMATCH", "ordinary shared capacity required"
        )
    capacity_worker_role_clause(capacity, pool_key="support", execution_role="support")
    bundle = resolve_released_instruction_bundle(session, policies[0].instruction_bundle)
    platforms = [
        component.artifact for component in bundle.components if component.layer == "PLATFORM"
    ]
    if len(platforms) != 1:
        raise ControlPlaneError(
            "CONTROL_BUNDLE_POINTER_INVALID", "one platform instruction required"
        )
    return base, platforms[0]


def _draft(
    sessions: sessionmaker[Session],
    *,
    base_revision_id: str,
    base_sha256: str,
    instruction: BundleRevisionPointer,
    actor_id: str,
    created_at: datetime,
) -> ExecutionPresetRevisionRecord:
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        base, _ = _baseline(session, base_revision_id, base_sha256)
        source = next(policy for policy in base.role_policies if policy.role == "support")
        policies = [
            {
                **source.model_dump(mode="json"),
                "instruction_bundle": instruction.model_dump(mode="json"),
                "reference_bundle": None,
                "worker_pool_key": "support",
                "sandbox": "read-only",
                "network": "disabled",
            }
        ]
        values = dict(
            preset_key=PRESET_KEY,
            display_name=DISPLAY_NAME,
            description=DESCRIPTION,
            role_policies=policies,
            capacity_policy_revision_id=base.capacity_policy_revision_id,
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=[CONCEPT_ROLE_PROTOCOL],
        )
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == PRESET_KEY)
            .with_for_update()
        )
        if logical is not None:
            if logical.state != "ACTIVE":
                raise ControlPlaneError("CONTROL_PRESET_RETIRED", "concept preset retired")
            query = select(ExecutionPresetRevisionRecord).where(
                ExecutionPresetRevisionRecord.preset_id == logical.preset_id
            )
            if logical.current_revision_id is not None:
                query = query.where(
                    ExecutionPresetRevisionRecord.preset_revision_id == logical.current_revision_id
                )
            else:
                query = query.order_by(ExecutionPresetRevisionRecord.revision_number.desc()).limit(
                    1
                )
            old = session.scalar(query)
            if old is not None:
                checked = validated_preset(old)
                if any(
                    checked.model_dump(mode="json")[key] != value
                    for key, value in values.items()
                    if key != "preset_key"
                ):
                    raise ControlPlaneError(
                        "CONTROL_BOOTSTRAP_CONFLICT", "concept policy already differs"
                    )
                session.expunge(old)
                return old
        row = create_execution_preset_draft(
            session,
            preset_key=PRESET_KEY,
            display_name=DISPLAY_NAME,
            description=DESCRIPTION,
            role_policies=policies,
            capacity_policy_revision_id=base.capacity_policy_revision_id,
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=[CONCEPT_ROLE_PROTOCOL],
            created_by=actor_id,
            created_at=created_at,
        )
        session.expunge(row)
        return row


def bootstrap_kakao_concepts(
    engine: Engine,
    *,
    instruction_path: Path,
    source_commit: str,
    actor_id: str,
    created_at: datetime,
    base_preset_revision_id: str,
    base_preset_sha256: str,
    settings: Settings | None = None,
) -> KakaoConceptBootstrapResult:
    """Release only the new purpose; current slots/auth/capacity and other presets are untouched."""
    # Reuse the existing process-safe publication adapter. This lock owns only this
    # bootstrap, not worker capacity or source reads, and takes no application row locks.
    with artifact_publication_lock(
        engine,
        namespace="kakao-concept-bootstrap",
        idempotency_key=PRESET_KEY,
        local_lock=nullcontext(),
    ):
        return _publish_kakao_concepts(
            engine,
            instruction_path=instruction_path,
            source_commit=source_commit,
            actor_id=actor_id,
            created_at=created_at,
            base_preset_revision_id=base_preset_revision_id,
            base_preset_sha256=base_preset_sha256,
            settings=settings,
        )


def _publish_kakao_concepts(
    engine: Engine,
    *,
    instruction_path: Path,
    source_commit: str,
    actor_id: str,
    created_at: datetime,
    base_preset_revision_id: str,
    base_preset_sha256: str,
    settings: Settings | None,
) -> KakaoConceptBootstrapResult:
    if (
        re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or not actor_id
        or len(actor_id) > 128
        or created_at.tzinfo is None
        or created_at.utcoffset() != timedelta(0)
    ):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "publication identity/time invalid")
    root = _safe_root(instruction_path.parent)
    role_bytes = _read_file(instruction_path, root=root, max_bytes=64 * 1024)
    if not role_bytes or b"\0" in role_bytes:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "instruction is invalid")
    try:
        role_bytes.decode("utf-8")
    except UnicodeError as error:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "instruction is not UTF-8") from error
    sessions = build_session_factory(engine)
    with sessions() as session:
        _, platform = _baseline(session, base_preset_revision_id, base_preset_sha256)
    publisher = ControlArtifactPublisher(engine, settings)
    identity = hashlib.sha256(
        source_commit.encode() + role_bytes + base_preset_revision_id.encode()
    ).hexdigest()
    role = publisher.publish_bytes(
        payload=role_bytes,
        logical_name="kakao-concepts.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        media_type="text/markdown",
        artifact_type="control_markdown",
        idempotency_key="kakao-concept-role:" + identity,
        source_commit=source_commit,
        created_at=created_at,
    ).pointer
    instruction = _publish_instruction_bundle(
        publisher,
        sessions,
        role="support",
        platform_artifact=platform,
        role_artifact=role,
        identity_key="kakao-concepts:" + identity,
        bundle_key=PRESET_KEY + "-support",
        role_relative_path="instructions/kakao-concepts.md",
        source_commit=source_commit,
        actor_id=actor_id,
        created_at=created_at,
    )
    row = _draft(
        sessions,
        base_revision_id=base_preset_revision_id,
        base_sha256=base_preset_sha256,
        instruction=instruction,
        actor_id=actor_id,
        created_at=created_at,
    )
    policy_hash = execution_preset_policy_sha256(row.canonical_document)
    with sessions() as session:
        evaluation = session.scalar(
            select(ExecutionPresetEvaluationRecord)
            .where(
                ExecutionPresetEvaluationRecord.preset_id == row.preset_id,
                ExecutionPresetEvaluationRecord.evaluated_policy_sha256 == policy_hash,
                ExecutionPresetEvaluationRecord.scope == "NON_LIVE",
                ExecutionPresetEvaluationRecord.outcome == "PASS",
            )
            .order_by(ExecutionPresetEvaluationRecord.completed_at.desc())
            .limit(1)
        )
    if row.state != "RELEASED":
        # This checks the exact typed policy, not an AI answer or textbook quality score.
        checked = ExecutionPresetRevision.model_validate(row.canonical_document)
        if checked.compatible_workflow_protocols != (CONCEPT_ROLE_PROTOCOL,):
            raise ControlPlaneError("CONTROL_WORKFLOW_PROTOCOL_INVALID", "concept protocol differs")
        report = ExecutionPresetEvaluationReport(
            schema_version="execution-preset-evaluation-report/1.0",
            evaluated_preset_revision_id=row.preset_revision_id,
            evaluated_policy_sha256=policy_hash,
            scope="NON_LIVE",
            outcome="PASS",
            summary_code="CONTRACT_VALIDATION",
            cases_total=1,
            cases_passed=1,
            quality_score_permille=None,
            completed_at=created_at,
            report_sha256="sha256:" + "0" * 64,
        ).model_dump(mode="json")
        report["report_sha256"] = compute_control_document_hash(report, "report_sha256")
        payload = canonical_json_bytes(report) + b"\n"
        published = publisher.publish_bytes(
            payload=payload,
            logical_name="kakao-concepts-evaluation.json",
            schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            media_type="application/json",
            artifact_type="control_preset_evaluation",
            idempotency_key="kakao-concepts-evaluation:" + hashlib.sha256(payload).hexdigest(),
            created_at=created_at,
            source_commit=source_commit,
        )
        with sessions.begin() as session:
            session.execute(
                select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID))
            )
            _baseline(session, base_preset_revision_id, base_preset_sha256)
            ensure_protocol_version(
                session, CONCEPT_ROLE_PROTOCOL, role_schema_bundle_hash(CONCEPT_ROLE_PROTOCOL)
            )
            evaluation = record_execution_preset_evaluation(
                session, document=report, report_artifact=published.pointer, created_by=actor_id
            )
            row = release_execution_preset(
                session,
                draft_revision_id=row.preset_revision_id,
                released_by=actor_id,
                released_at=created_at,
            )
            session.expunge(row)
    if evaluation is None:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_HISTORY_INVALID", "contract evaluation missing")
    return KakaoConceptBootstrapResult(
        preset_id=row.preset_id,
        preset_revision_id=row.preset_revision_id,
        preset_sha256=row.content_sha256,
        base_preset_revision_id=base_preset_revision_id,
        instruction_bundle_revision_id=instruction.bundle_revision_id,
        capacity_policy_revision_id=row.capacity_policy_revision_id,
        evaluation_id=evaluation.evaluation_id,
        source_commit=source_commit,
    )
