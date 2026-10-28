"""Release a one-slot purpose binding of the existing knowledge-analysis policy.

Models, instructions and worker protocol are inherited from an exact released
baseline. Only a new preset key and the already released support-only capacity
are selected. This does not observe/login a slot or run model inference.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.control_plane import ExecutionPresetEvaluationReport, ExecutionPresetRevision
from eom_workflow.schemas import load_role_input_schema
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID, ControlPlaneError
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

CREATIVE_KNOWLEDGE_PRESET_KEY = "creative-knowledge-analysis"


def release_creative_knowledge_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    baseline_revision_id: str,
    capacity_revision_id: str,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> ExecutionPresetRevision:
    authorize(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        baseline_row = session.get(ExecutionPresetRevisionRecord, baseline_revision_id)
        baseline = validated_preset(baseline_row) if baseline_row else None
        capacity = resolve_released_capacity_policy(session, capacity_revision_id)
        pools = {entry.pool_key: entry for entry in capacity.pools}
        pool = pools.get("support")
        if (
            not isinstance(baseline, ExecutionPresetRevision)
            or baseline.state != "RELEASED"
            or "workflow-role/1.6.0" not in baseline.compatible_workflow_protocols
            or len(baseline.role_policies) != 1
            or baseline.role_policies[0].worker_pool_key != "support"
            or pool is None
            or pool.slot_keys != ("slot05",)
            or pool.max_active != 1
        ):
            raise ControlPlaneError("CONTROL_CREATIVE_ANALYSIS_POLICY_INVALID", "policy differs")
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == CREATIVE_KNOWLEDGE_PRESET_KEY)
            .with_for_update()
        )
        expected_roles = baseline.role_policies
        if logical is not None and logical.current_revision_id is not None:
            row = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            current = validated_preset(row) if row else None
            if (
                not isinstance(current, ExecutionPresetRevision)
                or current.state != "RELEASED"
                or current.role_policies != expected_roles
                or current.capacity_policy_revision_id != capacity_revision_id
                or current.general_knowledge_policy != baseline.general_knowledge_policy
            ):
                raise ControlPlaneError(
                    "CONTROL_CREATIVE_ANALYSIS_POLICY_INVALID", "replay differs"
                )
            if current.compatible_workflow_protocols == baseline.compatible_workflow_protocols:
                return current
            # An initial canary exposed that approved-Item V2 uses the released
            # base Workflow's 1.4 protocol. Preserve the incomplete first release
            # and publish a successor inheriting the complete baseline family.
            if current.compatible_workflow_protocols != ("workflow-role/1.6.0",):
                raise ControlPlaneError(
                    "CONTROL_CREATIVE_ANALYSIS_POLICY_INVALID", "protocol replay differs"
                )
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
            raise ControlPlaneError("CONTROL_CREATIVE_ANALYSIS_POLICY_INVALID", "drafts repeat")
        draft_row = (
            drafts[0]
            if drafts
            else create_execution_preset_draft(
                session,
                preset_key=CREATIVE_KNOWLEDGE_PRESET_KEY,
                display_name="창작 문항 Graph 분석",
                description="기존 지식 분석을 support 05에 한정",
                role_policies=[entry.model_dump(mode="json") for entry in expected_roles],
                capacity_policy_revision_id=capacity_revision_id,
                general_knowledge_policy=baseline.general_knowledge_policy,
                compatible_workflow_protocols=list(baseline.compatible_workflow_protocols),
                created_by=operator_id,
                created_at=datetime.now(UTC),
            )
        )
        draft = validated_preset(draft_row)
        if (
            not isinstance(draft, ExecutionPresetRevision)
            or draft.role_policies != expected_roles
            or draft.capacity_policy_revision_id != capacity_revision_id
            or draft.compatible_workflow_protocols != baseline.compatible_workflow_protocols
        ):
            raise ControlPlaneError("CONTROL_CREATIVE_ANALYSIS_POLICY_INVALID", "draft differs")
    for protocol in draft.compatible_workflow_protocols:
        load_role_input_schema("support", protocol)
    cases = (
        "EXACT_KNOWLEDGE_ROLE_POLICY",
        "SUPPORT_SLOT05_ONLY",
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
        logical_name="creative-analysis-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="creative-analysis-eval:" + report.report_sha256[7:],
        created_at=now,
        source_commit=source_commit,
    )
    with sessions.begin() as session:
        authorize(operator_id)
        record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=artifact.pointer,
            created_by=operator_id,
        )
        released = validated_preset(
            release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=operator_id,
                released_at=now,
            )
        )
        if not isinstance(released, ExecutionPresetRevision):
            raise ControlPlaneError("CONTROL_CREATIVE_ANALYSIS_POLICY_INVALID", "released schema")
        return released
