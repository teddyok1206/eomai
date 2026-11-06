"""Purpose-limited uploaded-material presets through the existing control lifecycle.

The material lane is persisted in Catalog; this policy shares the existing four
host permits rather than creating an additional physical slot or queue.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    new_capacity_policy_id,
    new_capacity_policy_revision_id,
    sha256_bytes,
)
from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
    WorkerCapacityPolicyV7,
)
from eom_workflow.schemas import load_role_input_schema, role_schema_bundle_hash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    publish_capacity_policy_revision,
    record_capacity_policy_revision,
    resolve_released_instruction_bundle,
)
from eom_orchestrator.creative_office_parallel_controls import (
    creative_office_report_capacity_document,
)
from eom_orchestrator.external_item_learning_controls import (
    publish_source_learning_instruction_bundle,
)
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.preset_model_selection import (
    non_live_invocation_cases,
    resolve_released_capacity_policy,
    validated_preset,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256
from eom_orchestrator.repository import ensure_protocol_version

CAPACITY_KEY = "uploaded-material-learning"


@dataclass(frozen=True, slots=True)
class MaterialLearningControls:
    capacity: WorkerCapacityPolicyV7
    learning: ExecutionPresetRevision
    item: ExecutionPresetRevision
    solution: ExecutionPresetRevision
    document: ExecutionPresetRevision


def material_learning_capacity_document(*, created_at: datetime) -> dict[str, object]:
    body = creative_office_report_capacity_document(created_at=created_at)
    body.update(
        schema_version="worker-capacity-policy/1.6",
        purpose="UPLOADED_MATERIAL_LEARNING",
        capacity_policy_id=new_capacity_policy_id(),
        capacity_policy_revision_id=new_capacity_policy_revision_id(),
    )
    body.pop("content_sha256")
    return {**body, "content_sha256": content_sha256(body)}


def _instruction(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    key: str,
    platform: bytes,
    role: bytes,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
    reviewed_at: datetime,
) -> BundleRevisionPointer:
    with sessions() as session:
        logical = session.scalar(
            select(ExecutionBundleRecord).where(
                ExecutionBundleRecord.bundle_key == key,
                ExecutionBundleRecord.bundle_kind == "INSTRUCTION",
            )
        )
        if logical is not None:
            row = session.get(ExecutionBundleRevisionRecord, logical.current_revision_id)
            if row is None or logical.state != "ACTIVE" or row.state != "RELEASED":
                raise ControlPlaneError("CONTROL_MATERIAL_INSTRUCTION_INVALID", "state differs")
            pointer = BundleRevisionPointer(
                bundle_id=row.bundle_id,
                bundle_revision_id=row.bundle_revision_id,
                manifest_artifact=ControlArtifactPointer(
                    artifact_id=row.manifest_artifact_id,
                    artifact_revision_id=row.manifest_artifact_revision_id,
                    sha256=row.manifest_sha256,
                    schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
                    media_type="application/json",
                    logical_name="instruction-bundle.json",
                ),
                manifest_sha256=row.manifest_sha256,
            )
            actual = resolve_released_instruction_bundle(session, pointer)
            if tuple(
                (part.layer, part.relative_path, part.artifact.sha256) for part in actual.components
            ) != (
                ("PLATFORM", "instructions/platform.md", sha256_bytes(platform)),
                ("ROLE", "instructions/external-item-learning.md", sha256_bytes(role)),
            ):
                raise ControlPlaneError("CONTROL_MATERIAL_INSTRUCTION_INVALID", "bytes differ")
            return pointer
    return publish_source_learning_instruction_bundle(
        sessions,
        publisher,
        platform_payload=platform,
        role_payload=role,
        source_commit=source_commit,
        operator_id=operator_id,
        created_at=reviewed_at,
        authorize_control_change=authorize,
        bundle_key=key,
    )


def _release_purpose(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    key: str,
    protocols: tuple[str, ...],
    baseline: ExecutionPresetRevision,
    instruction: BundleRevisionPointer,
    capacity: WorkerCapacityPolicyV7,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> ExecutionPresetRevision:
    policies = [
        baseline.role_policies[0]
        .model_copy(update={"instruction_bundle": instruction})
        .model_dump(mode="json")
    ]
    general = "DENY" if key == "material-learning" else baseline.general_knowledge_policy

    def check(row: ExecutionPresetRevisionRecord | None) -> ExecutionPresetRevision:
        value = validated_preset(row) if row else None
        if (
            not isinstance(value, ExecutionPresetRevision)
            or value.capacity_policy_revision_id != capacity.capacity_policy_revision_id
            or value.compatible_workflow_protocols != protocols
            or value.general_knowledge_policy != general
            or [part.model_dump(mode="json") for part in value.role_policies] != policies
        ):
            raise ControlPlaneError("CONTROL_MATERIAL_PRESET_INVALID", "pins differ")
        return value

    authorize(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        for protocol in protocols:
            ensure_protocol_version(session, protocol, role_schema_bundle_hash(protocol))
            load_role_input_schema("support", protocol)
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == key)
            .with_for_update()
        )
        if logical is not None and logical.state != "ACTIVE":
            raise ControlPlaneError("CONTROL_PRESET_RETIRED", "material purpose retired")
        if logical is not None and logical.current_revision_id:
            current = check(session.get(ExecutionPresetRevisionRecord, logical.current_revision_id))
            if current.state != "RELEASED":
                raise ControlPlaneError("CONTROL_PRESET_NOT_PUBLISHED", "material purpose differs")
            return current
        drafts = (
            tuple(
                session.scalars(
                    select(ExecutionPresetRevisionRecord).where(
                        ExecutionPresetRevisionRecord.preset_id == logical.preset_id,
                        ExecutionPresetRevisionRecord.state == "DRAFT",
                    )
                )
            )
            if logical
            else ()
        )
        if len(drafts) > 1:
            raise ControlPlaneError("CONTROL_MATERIAL_PRESET_INVALID", "drafts repeat")
        draft = check(
            drafts[0]
            if drafts
            else create_execution_preset_draft(
                session,
                preset_key=key,
                display_name={
                    "material-learning": "자료 내용·문항 읽기",
                    "material-item-analysis": "자료 문항 Graph 분석",
                    "material-item-solution": "자료 문항 풀이보고서",
                    "material-knowledge-analysis": "자료 설명 Graph 분석",
                }[key],
                description="자료 학습 1 AI lane, 기존 host 동시4와 지식 분석 소유 경계 재사용",
                role_policies=policies,
                capacity_policy_revision_id=capacity.capacity_policy_revision_id,
                general_knowledge_policy=general,
                compatible_workflow_protocols=list(protocols),
                created_by=operator_id,
                created_at=datetime.now(UTC),
            )
        )
    cases = (
        "SOURCE_BOUND_MATERIAL_PURPOSE",
        "ONE_MATERIAL_AI_LANE_SHARED_HOST_FOUR",
        *non_live_invocation_cases(draft),
    )
    now = datetime.now(UTC)
    body = dict(
        schema_version="execution-preset-evaluation-report/1.0",
        evaluated_preset_revision_id=draft.preset_revision_id,
        evaluated_policy_sha256=execution_preset_policy_sha256(draft),
        scope="NON_LIVE",
        outcome="PASS",
        summary_code="CONTRACT_VALIDATION",
        cases_total=len(cases),
        cases_passed=len(cases),
        quality_score_permille=None,
        completed_at=now.isoformat().replace("+00:00", "Z"),
    )
    report = ExecutionPresetEvaluationReport.model_validate(
        {**body, "report_sha256": content_sha256(body)}
    )
    authorize(operator_id)
    artifact = publisher.publish_bytes(
        payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
        logical_name="material-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="material-preset-eval:" + report.report_sha256[7:],
        created_at=now,
        source_commit=source_commit,
    )
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        authorize(operator_id)
        record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=artifact.pointer,
            created_by=operator_id,
        )
        return check(
            release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=operator_id,
                released_at=now,
            )
        )


def release_material_learning_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    baseline_revision_id: str,
    platform_payload: bytes,
    learning_payload: bytes,
    document_payload: bytes,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
    reviewed_at: datetime,
) -> MaterialLearningControls:
    """Explicit release action; never invoked by upload, polling or service startup."""
    authorize(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        row = session.get(ExecutionPresetRevisionRecord, baseline_revision_id)
        baseline = validated_preset(row) if row else None
        if (
            not isinstance(baseline, ExecutionPresetRevision)
            or baseline.state != "RELEASED"
            or not {"workflow-role/1.4.0", "workflow-role/1.35.0"}.issubset(
                baseline.compatible_workflow_protocols
            )
            or len(baseline.role_policies) != 1
        ):
            raise ControlPlaneError(
                "CONTROL_MATERIAL_BASE_INVALID", "exact Item/solution baseline required"
            )
        role = baseline.role_policies[0]
        if (
            role.role != "support"
            or role.worker_pool_key != "support"
            or role.sandbox != "read-only"
            or role.network != "disabled"
            or role.reference_bundle is not None
            or role.timeout_seconds != 7200
        ):
            raise ControlPlaneError("CONTROL_MATERIAL_BASE_INVALID", "isolation differs")
        logical = session.scalar(
            select(WorkerCapacityPolicyRecord)
            .where(WorkerCapacityPolicyRecord.policy_key == CAPACITY_KEY)
            .with_for_update()
        )
        if logical is None:
            capacity_row = record_capacity_policy_revision(
                session,
                policy_key=CAPACITY_KEY,
                document=material_learning_capacity_document(created_at=reviewed_at),
                created_by=operator_id,
            )
            publish_capacity_policy_revision(
                session,
                capacity_policy_id=capacity_row.capacity_policy_id,
                capacity_policy_revision_id=capacity_row.capacity_policy_revision_id,
            )
            capacity_id = capacity_row.capacity_policy_revision_id
        elif logical.state == "ACTIVE" and logical.current_revision_id is not None:
            capacity_id = logical.current_revision_id
        else:
            raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "material purpose retired")
        capacity = resolve_released_capacity_policy(session, capacity_id)
        if not isinstance(capacity, WorkerCapacityPolicyV7):
            raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "material capacity differs")
    learning = _instruction(
        sessions,
        publisher,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
        key="material-learning-instructions-v1",
        platform=platform_payload,
        role=learning_payload,
        reviewed_at=reviewed_at,
    )
    document = _instruction(
        sessions,
        publisher,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
        key="material-knowledge-instructions-v1",
        platform=platform_payload,
        role=document_payload,
        reviewed_at=reviewed_at,
    )
    values = []
    for key, protocol, instruction in (
        ("material-learning", "workflow-role/1.37.0", learning),
        ("material-item-analysis", "workflow-role/1.4.0", role.instruction_bundle),
        ("material-item-solution", "workflow-role/1.35.0", role.instruction_bundle),
        ("material-knowledge-analysis", "workflow-role/1.38.0", document),
    ):
        values.append(
            _release_purpose(
                sessions,
                publisher,
                operator_id=operator_id,
                source_commit=source_commit,
                authorize=authorize,
                key=key,
                protocols=(protocol,),
                baseline=baseline,
                instruction=instruction,
                capacity=capacity,
            )
        )
    return MaterialLearningControls(capacity, *values)
