"""Initial creative policy release from executed NON_LIVE contract cases only.

This does not refresh model observations, assert entitlement/quota, claim a slot
or start a Workflow. Ordinary execution and model-successor gates stay intact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.control_plane import (
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
)
from eom_workflow.schemas import load_role_input_schema, role_schema_bundle_hash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    resolve_control_artifact_pointer,
)
from eom_orchestrator.external_item_learning_controls import (
    resolve_external_item_learning_control_policy,
)
from eom_orchestrator.models import ProtocolVersionRecord
from eom_orchestrator.preset_lifecycle import (
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.preset_model_selection import non_live_invocation_cases, validated_preset
from eom_orchestrator.preset_policy import execution_preset_policy_sha256

_EVALUATION_SCHEMA = "eom://schemas/workflow/execution-preset-evaluation-report/1.0"


@dataclass(frozen=True, slots=True)
class ReleasedExternalItemLearningControls:
    preset: ExecutionPresetRevision
    evaluation_id: str
    evaluation_artifact: ControlArtifactPointer
    executed_cases: tuple[str, ...]


def _checked_draft(session: Session, draft: ExecutionPresetRevision) -> tuple[str, ...]:
    record = session.get(ExecutionPresetRevisionRecord, draft.preset_revision_id)
    stored = validated_preset(record) if record is not None else None
    if (
        stored != draft
        or draft.revision_number != 1
        or draft.state != "DRAFT"
        or len(draft.role_policies) != 1
        or draft.compatible_workflow_protocols != ("workflow-role/1.33.0",)
        or draft.general_knowledge_policy != "DENY"
        or len(draft.role_policies[0].model_candidates) != 1
    ):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_CONFLICT", "creative initial draft differs")
    role = draft.role_policies[0]
    expected = resolve_external_item_learning_control_policy(
        session,
        instruction=role.instruction_bundle,
        capacity_revision_id=draft.capacity_policy_revision_id,
        candidate=role.model_candidates[0],
    )
    if role != expected:
        raise ControlPlaneError("CONTROL_BOOTSTRAP_CONFLICT", "creative role policy differs")
    protocol = session.get(ProtocolVersionRecord, "workflow-role/1.33.0")
    if protocol is None or protocol.schema_sha256 != role_schema_bundle_hash(
        "workflow-role/1.33.0"
    ):
        raise ControlPlaneError(
            "CONTROL_PROTOCOL_POINTER_MISSING", "creative role protocol differs"
        )
    load_role_input_schema("support", "workflow-role/1.33.0")
    return (
        "EXACT_STORED_INITIAL_DRAFT",
        "EXACT_CREATIVE_INSTRUCTION_METADATA",
        "FIXED_HOST_SUPPORT_CAPACITY",
        "REGISTERED_ROLE_SCHEMA",
        *non_live_invocation_cases(draft),
    )


def _released_replay(
    session: Session, draft: ExecutionPresetRevision, cases: tuple[str, ...]
) -> ReleasedExternalItemLearningControls | None:
    logical = session.get(ExecutionPresetRecord, draft.preset_id, with_for_update=True)
    if (
        logical is None
        or logical.preset_key != "external-item-learning"
        or logical.state != "ACTIVE"
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_HISTORY_INVALID", "creative preset is unavailable"
        )
    if logical.current_revision_id is None:
        return None
    row = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
    current = validated_preset(row) if row is not None else None
    policy_sha = execution_preset_policy_sha256(draft)
    if (
        not isinstance(current, ExecutionPresetRevision)
        or current.state != "RELEASED"
        or current.preset_id != draft.preset_id
        or execution_preset_policy_sha256(current) != policy_sha
    ):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_CONFLICT", "creative published policy differs")
    evaluation = session.scalar(
        select(ExecutionPresetEvaluationRecord)
        .where(
            ExecutionPresetEvaluationRecord.preset_id == draft.preset_id,
            ExecutionPresetEvaluationRecord.evaluated_preset_revision_id
            == draft.preset_revision_id,
            ExecutionPresetEvaluationRecord.evaluated_policy_sha256 == policy_sha,
            ExecutionPresetEvaluationRecord.scope == "NON_LIVE",
            ExecutionPresetEvaluationRecord.outcome == "PASS",
            ExecutionPresetEvaluationRecord.summary_code == "CONTRACT_VALIDATION",
        )
        .order_by(ExecutionPresetEvaluationRecord.completed_at.desc())
        .limit(1)
    )
    if (
        evaluation is None
        or evaluation.cases_total != len(cases)
        or evaluation.cases_passed != len(cases)
        or evaluation.quality_score_permille is not None
    ):
        raise ControlPlaneError("CONTROL_EVALUATION_INVALID", "creative technical evidence differs")
    pointer = ControlArtifactPointer(
        artifact_id=evaluation.report_artifact_id,
        artifact_revision_id=evaluation.report_artifact_revision_id,
        sha256=evaluation.report_content_sha256,
        schema_ref=_EVALUATION_SCHEMA,
        media_type="application/json",
        logical_name="creative-preset-evaluation.json",
    )
    resolve_control_artifact_pointer(session, pointer)
    return ReleasedExternalItemLearningControls(current, evaluation.evaluation_id, pointer, cases)


def release_external_item_learning_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    draft: ExecutionPresetRevision,
    operator_id: str,
    source_commit: str,
    authorize_control_change: Callable[[str], None],
) -> ReleasedExternalItemLearningControls:
    """Record real static/CLI adapter checks, without a fresh-model availability claim."""

    authorize_control_change(operator_id)
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        cases = _checked_draft(session, draft)
        existing = _released_replay(session, draft, cases)
        if existing is not None:
            authorize_control_change(operator_id)
            return existing
    checked_at = datetime.now(UTC)
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
        "completed_at": checked_at.isoformat().replace("+00:00", "Z"),
    }
    report = ExecutionPresetEvaluationReport.model_validate(
        {**body, "report_sha256": content_sha256(body)}
    )
    authorize_control_change(operator_id)
    published = publisher.publish_bytes(
        payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
        logical_name="creative-preset-evaluation.json",
        schema_ref=_EVALUATION_SCHEMA,
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="creative-preset-evaluation:" + report.report_sha256[7:],
        created_at=checked_at,
        source_commit=source_commit,
    )
    with sessions.begin() as session:
        authorize_control_change(operator_id)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        if _checked_draft(session, draft) != cases:
            raise ControlPlaneError(
                "CONTROL_EVALUATION_INVALID", "creative validation cases changed"
            )
        existing = _released_replay(session, draft, cases)
        if existing is not None:
            return existing
        evaluation = record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=published.pointer,
            created_by=operator_id,
        )
        row = release_execution_preset(
            session,
            draft_revision_id=draft.preset_revision_id,
            released_by=operator_id,
            released_at=checked_at,
        )
        current = validated_preset(row)
        if not isinstance(current, ExecutionPresetRevision):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "creative released schema differs"
            )
        authorize_control_change(operator_id)
        return ReleasedExternalItemLearningControls(
            current, evaluation.evaluation_id, published.pointer, cases
        )
