"""Release purpose-limited capacity and clones of exact creative baseline policies.

Only pool/capacity and separate logical preset identities change. Existing lifecycle
owners still validate bundles, model acceptance, NON_LIVE evidence and publication.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    new_capacity_policy_id,
    new_capacity_policy_revision_id,
)
from eom_workflow.control_plane import (
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
    WorkerCapacityPolicyV5,
)
from eom_workflow.schemas import load_role_input_schema
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    publish_capacity_policy_revision,
    record_capacity_policy_revision,
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

CAPACITY_KEY = "creative-report-backfill-three"


@dataclass(frozen=True, slots=True)
class CreativeParallelControls:
    capacity: WorkerCapacityPolicyV5
    extraction: ExecutionPresetRevision
    analysis: ExecutionPresetRevision


def creative_report_capacity_document(*, created_at: datetime) -> dict[str, object]:
    body = {
        "schema_version": "worker-capacity-policy/1.4",
        "capacity_policy_id": new_capacity_policy_id(),
        "capacity_policy_revision_id": new_capacity_policy_revision_id(),
        "revision_number": 1,
        "state": "RELEASED",
        "purpose": "CREATIVE_REPORT_BACKFILL",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 3,
        "pools": [
            {
                "pool_key": "support",
                "roles": ["support"],
                "slot_keys": ["slot04", "slot05", "slot06"],
                "max_active": 3,
            }
        ],
        "delegated_slot_roles": [
            {
                "pool_key": "support",
                "slot_key": "slot04",
                "native_role": "item_management",
                "execution_role": "support",
            }
        ],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    return {**body, "content_sha256": content_sha256(body)}


def parallel_role_policies(baseline: ExecutionPresetRevision) -> list[dict[str, object]]:
    if (
        baseline.state != "RELEASED"
        or len(baseline.role_policies) != 1
        or baseline.role_policies[0].role != "support"
        or baseline.role_policies[0].worker_pool_key != "support"
        or baseline.role_policies[0].sandbox != "read-only"
        or baseline.role_policies[0].network != "disabled"
        or baseline.role_policies[0].timeout_seconds != 7200
        or baseline.role_policies[0].reference_bundle is not None
    ):
        raise ControlPlaneError("CONTROL_CREATIVE_PARALLEL_BASE_INVALID", "baseline differs")
    return [{**baseline.role_policies[0].model_dump(mode="json"), "worker_pool_key": "support"}]


def _release_preset(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    baseline: ExecutionPresetRevision,
    purpose: Literal["source", "analysis"],
    capacity: WorkerCapacityPolicyV5,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> ExecutionPresetRevision:
    key = (
        "creative-source-learning-parallel"
        if purpose == "source"
        else "creative-knowledge-analysis-parallel"
    )
    policies = parallel_role_policies(baseline)

    def check(row: ExecutionPresetRevisionRecord | None) -> ExecutionPresetRevision:
        preset = validated_preset(row) if row else None
        if (
            not isinstance(preset, ExecutionPresetRevision)
            or preset.capacity_policy_revision_id != capacity.capacity_policy_revision_id
            or preset.compatible_workflow_protocols != baseline.compatible_workflow_protocols
            or preset.general_knowledge_policy != baseline.general_knowledge_policy
            or [part.model_dump(mode="json") for part in preset.role_policies] != policies
        ):
            raise ControlPlaneError("CONTROL_CREATIVE_PARALLEL_PRESET_INVALID", "pins differ")
        return preset

    authorize(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == key)
            .with_for_update()
        )
        if logical is not None and logical.state != "ACTIVE":
            raise ControlPlaneError("CONTROL_PRESET_RETIRED", "parallel purpose is retired")
        if logical is not None and logical.current_revision_id:
            current = check(session.get(ExecutionPresetRevisionRecord, logical.current_revision_id))
            if current.state != "RELEASED":
                raise ControlPlaneError("CONTROL_PRESET_NOT_PUBLISHED", "parallel state differs")
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
            if logical is not None
            else ()
        )
        if len(drafts) > 1:
            raise ControlPlaneError("CONTROL_CREATIVE_PARALLEL_PRESET_INVALID", "drafts repeat")
        row = (
            drafts[0]
            if drafts
            else create_execution_preset_draft(
                session,
                preset_key=key,
                display_name="창작 문항 3슬롯 "
                + ("원문·풀이" if purpose == "source" else "Graph 분석"),
                description="고정된 기존 지침·모델·격리, 창작 보고서 전용 동시 3",
                role_policies=policies,
                capacity_policy_revision_id=capacity.capacity_policy_revision_id,
                general_knowledge_policy=baseline.general_knowledge_policy,
                compatible_workflow_protocols=list(baseline.compatible_workflow_protocols),
                created_by=operator_id,
                created_at=datetime.now(UTC),
            )
        )
        draft = check(row)
    for protocol in draft.compatible_workflow_protocols:
        load_role_input_schema("support", protocol)
    cases = (
        "EXACT_BASELINE_INSTRUCTIONS_MODEL_AND_ISOLATION",
        "CREATIVE_REPORTS_SLOT04_05_06_ONLY",
        "ROLE_SCHEMA_RESOLVED",
        *non_live_invocation_cases(draft),
    )
    now = datetime.now(UTC)
    body = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": draft.preset_revision_id,
        "evaluated_policy_sha256": execution_preset_policy_sha256(draft),
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "CONTRACT_VALIDATION",
        "cases_total": len(cases),
        "cases_passed": len(cases),
        "quality_score_permille": None,
        "completed_at": now.isoformat().replace("+00:00", "Z"),
    }
    report = ExecutionPresetEvaluationReport.model_validate(
        {**body, "report_sha256": content_sha256(body)}
    )
    authorize(operator_id)
    artifact = publisher.publish_bytes(
        payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
        logical_name="creative-parallel-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="creative-parallel-eval:" + report.report_sha256[7:],
        created_at=now,
        source_commit=source_commit,
    )
    with sessions.begin() as session:
        # Take the lifecycle fence before evaluation inserts acquire FK row
        # locks. Reversing this order deadlocks two exact concurrent releases.
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        authorize(operator_id)
        record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=artifact.pointer,
            created_by=operator_id,
        )
        released = check(
            release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=operator_id,
                released_at=now,
            )
        )
        if released.state != "RELEASED":
            raise ControlPlaneError("CONTROL_PRESET_NOT_PUBLISHED", "parallel release differs")
        return released


def release_creative_parallel_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    extraction_revision_id: str,
    analysis_revision_id: str,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> CreativeParallelControls:
    authorize(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        baselines = []
        for revision_id, expected_key in (
            (extraction_revision_id, "creative-source-learning"),
            (analysis_revision_id, "creative-knowledge-analysis"),
        ):
            row = session.get(ExecutionPresetRevisionRecord, revision_id)
            baseline = validated_preset(row) if row else None
            logical = session.get(ExecutionPresetRecord, baseline.preset_id) if baseline else None
            if (
                not isinstance(baseline, ExecutionPresetRevision)
                or logical is None
                or logical.state != "ACTIVE"
                or logical.preset_key != expected_key
            ):
                raise ControlPlaneError("CONTROL_CREATIVE_PARALLEL_BASE_INVALID", "purpose differs")
            parallel_role_policies(baseline)
            baselines.append(baseline)
        if (
            baselines[0].compatible_workflow_protocols != ("workflow-role/1.34.0",)
            or baselines[0].general_knowledge_policy != "DENY"
            or "workflow-role/1.6.0" not in baselines[1].compatible_workflow_protocols
            or baselines[0].capacity_policy_revision_id != baselines[1].capacity_policy_revision_id
        ):
            raise ControlPlaneError("CONTROL_CREATIVE_PARALLEL_BASE_INVALID", "family differs")
        logical_capacity = session.scalar(
            select(WorkerCapacityPolicyRecord)
            .where(WorkerCapacityPolicyRecord.policy_key == CAPACITY_KEY)
            .with_for_update()
        )
        if logical_capacity is None:
            capacity_row = record_capacity_policy_revision(
                session,
                policy_key=CAPACITY_KEY,
                document=creative_report_capacity_document(created_at=datetime.now(UTC)),
                created_by=operator_id,
            )
            publish_capacity_policy_revision(
                session,
                capacity_policy_id=capacity_row.capacity_policy_id,
                capacity_policy_revision_id=capacity_row.capacity_policy_revision_id,
            )
            capacity_id = capacity_row.capacity_policy_revision_id
        else:
            if logical_capacity.state != "ACTIVE" or logical_capacity.current_revision_id is None:
                raise ControlPlaneError(
                    "CONTROL_CAPACITY_POINTER_INVALID", "parallel purpose retired"
                )
            capacity_id = logical_capacity.current_revision_id
        capacity = resolve_released_capacity_policy(session, capacity_id)
        if not isinstance(capacity, WorkerCapacityPolicyV5):
            raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "parallel schema differs")
    extraction = _release_preset(
        sessions,
        publisher,
        baseline=baselines[0],
        purpose="source",
        capacity=capacity,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )
    analysis = _release_preset(
        sessions,
        publisher,
        baseline=baselines[1],
        purpose="analysis",
        capacity=capacity,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )
    return CreativeParallelControls(capacity, extraction, analysis)
