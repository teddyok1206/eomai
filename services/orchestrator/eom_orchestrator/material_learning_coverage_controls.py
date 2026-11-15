"""Explicit same-logical Material ROLE1.37 -> ROLE1.39 control upgrade.

The initial bootstrap and ordinary administrator model-selection path are not
changed. Only the protocol differs from the exact current administrator policy;
draft/evaluation/publication/release remain owned by the existing lifecycle.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.control_plane import ExecutionPresetEvaluationReport, ExecutionPresetRevision
from eom_workflow.schemas import load_role_input_schema, role_schema_bundle_hash
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
from eom_orchestrator.preset_model_selection import non_live_invocation_cases, validated_preset
from eom_orchestrator.preset_policy import execution_preset_policy_sha256
from eom_orchestrator.repository import ensure_protocol_version

_KEY = "material-learning"
_BASE_PROTOCOL = "workflow-role/1.37.0"
_TARGET_PROTOCOL = "workflow-role/1.39.0"


def _preserved_policy(value: ExecutionPresetRevision) -> dict[str, Any]:
    body = value.model_dump(mode="json")
    for field in (
        "preset_revision_id",
        "revision_number",
        "state",
        "content_sha256",
        "created_at",
        "compatible_workflow_protocols",
    ):
        body.pop(field)
    return body


def require_material_learning_coverage_successor(
    base: ExecutionPresetRevision, successor: ExecutionPresetRevision
) -> None:
    """Pure protocol-only rule, including model order, labels and every authority pin."""
    if (
        base.state != "RELEASED"
        or base.compatible_workflow_protocols != (_BASE_PROTOCOL,)
        or base.general_knowledge_policy != "DENY"
        or len(base.role_policies) != 1
        or base.role_policies[0].role != "support"
        or base.role_policies[0].worker_pool_key != "support"
        or successor.state not in {"DRAFT", "RELEASED"}
        or successor.compatible_workflow_protocols != (_TARGET_PROTOCOL,)
        or _preserved_policy(base) != _preserved_policy(successor)
    ):
        raise ControlPlaneError(
            "CONTROL_MATERIAL_COVERAGE_POLICY_CHANGED",
            "only the Material coverage protocol may change",
        )


def _locked_base(
    session: Session, *, expected_revision_id: str, expected_sha256: str
) -> tuple[ExecutionPresetRevision, ExecutionPresetRevision | None]:
    session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
    logical = session.scalar(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_key == _KEY)
        .with_for_update()
    )
    if logical is None or logical.state != "ACTIVE":
        raise ControlPlaneError("CONTROL_PRESET_NOT_PUBLISHED", "Material preset is unavailable")
    row = session.get(ExecutionPresetRevisionRecord, expected_revision_id, populate_existing=True)
    base = validated_preset(row) if row is not None else None
    if (
        not isinstance(base, ExecutionPresetRevision)
        or base.preset_id != logical.preset_id
        or base.content_sha256 != expected_sha256
        or base.state != "RELEASED"
        or base.compatible_workflow_protocols != (_BASE_PROTOCOL,)
        or base.general_knowledge_policy != "DENY"
    ):
        raise ControlPlaneError(
            "CONTROL_MATERIAL_COVERAGE_BASE_INVALID",
            "exact released Material1.37 baseline required",
        )
    if logical.current_revision_id == expected_revision_id:
        return base, None
    current_row = (
        session.get(
            ExecutionPresetRevisionRecord, logical.current_revision_id, populate_existing=True
        )
        if logical.current_revision_id
        else None
    )
    current = validated_preset(current_row) if current_row is not None else None
    if isinstance(current, ExecutionPresetRevision) and current.state == "RELEASED":
        try:
            require_material_learning_coverage_successor(base, current)
        except ControlPlaneError:
            pass
        else:
            return base, current
    raise ControlPlaneError("CONTROL_PRESET_BASE_STALE", "Material current revision changed")


def upgrade_material_learning_coverage_preset(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    expected_current_revision_id: str,
    expected_current_sha256: str,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
    reviewed_at: datetime,
) -> ExecutionPresetRevision:
    """Explicit reviewed upgrade, never startup/upload/polling or model invocation.

    The old parent is rechecked under the same logical-row lock immediately
    before release. A lost publication response may only be explicitly resumed
    with this same exact draft/report key, not resubmitted under a fresh identity.
    """
    if (
        re.fullmatch(r"execpresetrev_[0-9a-f]{32}", expected_current_revision_id) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_current_sha256) is None
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or reviewed_at.utcoffset() != timedelta(0)
    ):
        raise ControlPlaneError(
            "CONTROL_MATERIAL_COVERAGE_INPUT_INVALID", "exact pins and UTC review time required"
        )
    authorize(operator_id)
    with sessions.begin() as session:
        base, replay = _locked_base(
            session,
            expected_revision_id=expected_current_revision_id,
            expected_sha256=expected_current_sha256,
        )
        if replay is not None:
            return replay
        ensure_protocol_version(
            session, _TARGET_PROTOCOL, role_schema_bundle_hash(_TARGET_PROTOCOL)
        )
        load_role_input_schema("support", _TARGET_PROTOCOL)
        matching: list[ExecutionPresetRevision] = []
        for row in session.scalars(
            select(ExecutionPresetRevisionRecord).where(
                ExecutionPresetRevisionRecord.preset_id == base.preset_id,
                ExecutionPresetRevisionRecord.state == "DRAFT",
                ExecutionPresetRevisionRecord.compatible_workflow_protocols == [_TARGET_PROTOCOL],
            )
        ):
            value = validated_preset(row)
            if isinstance(value, ExecutionPresetRevision):
                try:
                    require_material_learning_coverage_successor(base, value)
                except ControlPlaneError:
                    continue  # Historical/administrator drafts are immutable, not commandeered.
                matching.append(value)
        if len(matching) > 1:
            raise ControlPlaneError(
                "CONTROL_MATERIAL_COVERAGE_DRAFT_AMBIGUOUS", "matching drafts repeat"
            )
        draft = (
            matching[0]
            if matching
            else validated_preset(
                create_execution_preset_draft(
                    session,
                    preset_key=_KEY,
                    display_name=base.display_name,
                    description=base.description,
                    role_policies=[policy.model_dump(mode="json") for policy in base.role_policies],
                    capacity_policy_revision_id=base.capacity_policy_revision_id,
                    general_knowledge_policy=base.general_knowledge_policy,
                    compatible_workflow_protocols=[_TARGET_PROTOCOL],
                    created_by=operator_id,
                    created_at=reviewed_at,
                )
            )
        )
        if not isinstance(draft, ExecutionPresetRevision):
            raise ControlPlaneError(
                "CONTROL_MATERIAL_COVERAGE_BASE_INVALID", "Material preset schema differs"
            )
        require_material_learning_coverage_successor(base, draft)
    cases = (
        "MATERIAL_NATIVE_USE_COVERAGE",
        "EXACT_CURRENT_ADMIN_POLICY_PRESERVED",
        *non_live_invocation_cases(draft),
    )
    # The immutable draft time makes resumed NON_LIVE evidence byte-identical;
    # this does not claim inference, content quality or live entitlement checks.
    evaluated_at = draft.created_at.astimezone(UTC)
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
        completed_at=evaluated_at.isoformat().replace("+00:00", "Z"),
    )
    report = ExecutionPresetEvaluationReport.model_validate(
        {**body, "report_sha256": content_sha256(body)}
    )
    authorize(operator_id)
    artifact = publisher.publish_bytes(
        payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
        logical_name="material-coverage-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="material-coverage-eval:"
        + content_sha256(
            {
                "base": expected_current_revision_id,
                "base_sha256": expected_current_sha256,
                "draft": draft.preset_revision_id,
                "report_sha256": report.report_sha256,
            }
        )[7:],
        created_at=evaluated_at,
        source_commit=source_commit,
    )
    with sessions.begin() as session:
        final_base, replay = _locked_base(
            session,
            expected_revision_id=expected_current_revision_id,
            expected_sha256=expected_current_sha256,
        )
        authorize(operator_id)
        if replay is not None:
            return replay
        require_material_learning_coverage_successor(final_base, draft)
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
                released_at=evaluated_at,
            )
        )
        if not isinstance(released, ExecutionPresetRevision):
            raise ControlPlaneError(
                "CONTROL_MATERIAL_COVERAGE_BASE_INVALID", "released schema differs"
            )
        require_material_learning_coverage_successor(final_base, released)
        return released
