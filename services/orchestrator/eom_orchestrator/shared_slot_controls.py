"""Explicit shared-capacity transition using existing immutable control owners.

This is an operator release use case, not an automatic "latest" rewrite. Callers
pin the exact current presets and prove the installed fixed units before preparing.
Existing plans, cohorts and released capacity documents are never mutated.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    new_capacity_policy_id,
    new_capacity_policy_revision_id,
)
from eom_operator_identity import PermissionKey
from eom_workflow.control_plane import ExecutionPresetEvaluationReport, ExecutionPresetRevisionV2
from eom_workflow.shared_worker_capacity import ORDINARY_SLOT_KEYS, SharedWorkerCapacityPolicy
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
    create_execution_preset_draft_v2,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.preset_model_selection import (
    Preset,
    resolve_released_capacity_policy,
    validate_preset_model_admission,
    validated_preset,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256

CAPACITY_KEY = "ordinary-shared-slots"


class SharedSlotPrincipal(Protocol):
    @property
    def operator_id(self) -> str: ...

    @property
    def roles(self) -> tuple[str, ...]: ...

    @property
    def effective_permissions(self) -> tuple[str, ...]: ...

    @property
    def authenticated_at(self) -> datetime: ...


def authorize_shared_slot_release(
    principal: SharedSlotPrincipal, *, operator_id: str, observed_at: datetime
) -> None:
    """Require the actual, recently authenticated control administrator."""
    required = {
        PermissionKey.EXECUTION_PRESET_MANAGE.value,
        PermissionKey.CODEX_ACCOUNT_MANAGE.value,
    }
    if (
        observed_at.utcoffset() != timedelta(0)
        or principal.authenticated_at.utcoffset() != timedelta(0)
        or principal.operator_id != operator_id
        or "ADMIN" not in principal.roles
        or not required.issubset(principal.effective_permissions)
        or not timedelta(0) <= observed_at - principal.authenticated_at <= timedelta(minutes=15)
    ):
        raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "current administrator required")


@dataclass(frozen=True, slots=True)
class SharedSlotTransition:
    capacity: SharedWorkerCapacityPolicy
    drafts: tuple[Preset, ...]


def shared_capacity_document(
    baselines: tuple[Preset, ...], *, created_at: datetime
) -> dict[str, Any]:
    memberships: dict[str, set[str]] = {}
    for preset in baselines:
        for policy in preset.role_policies:
            memberships.setdefault(policy.worker_pool_key, set()).add(str(policy.role))
    body = dict(
        schema_version="worker-capacity-policy/1.7",
        purpose="SHARED_ORDINARY_SLOTS",
        capacity_policy_id=new_capacity_policy_id(),
        capacity_policy_revision_id=new_capacity_policy_revision_id(),
        revision_number=1,
        state="RELEASED",
        max_configured_slots=6,
        max_active_codex=4,
        max_active_per_slot=1,
        max_active_gpu=1,
        max_active_knowledge_analysis=4,
        pools=[
            dict(
                pool_key=key, roles=sorted(roles), slot_keys=list(ORDINARY_SLOT_KEYS), max_active=4
            )
            for key, roles in sorted(memberships.items())
        ],
        created_at=created_at.isoformat().replace("+00:00", "Z"),
    )
    return body | {"content_sha256": content_sha256(body)}


def prepare_shared_slot_controls(
    session: Session,
    *,
    baselines: tuple[Preset, ...],
    operator_id: str,
    created_at: datetime,
    require_installed_units: Callable[[], None],
) -> SharedSlotTransition:
    if not baselines or len({v.preset_id for v in baselines}) != len(baselines):
        raise ControlPlaneError("CONTROL_SHARED_BASE_INVALID", "unique exact baselines required")
    require_installed_units()
    session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
    logicals = {}
    already_released = {}
    # Stable row order avoids reversed multi-preset lock acquisition by two operators.
    for baseline in sorted(baselines, key=lambda p: p.preset_id):
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_id == baseline.preset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if logical is None or logical.state != "ACTIVE" or baseline.state != "RELEASED":
            raise ControlPlaneError(
                "CONTROL_PRESET_BASE_STALE", "shared transition baseline changed"
            )
        row = session.get(ExecutionPresetRevisionRecord, baseline.preset_revision_id)
        if row is None or validated_preset(row) != baseline:
            raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "shared baseline differs")
        if logical.current_revision_id != baseline.preset_revision_id:
            current_row = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            current = validated_preset(current_row) if current_row else None
            if current is None or current.state != "RELEASED":
                raise ControlPlaneError("CONTROL_PRESET_BASE_STALE", "current baseline changed")
            current_capacity = resolve_released_capacity_policy(
                session, current.capacity_policy_revision_id
            )
            expected = baseline.model_copy(
                update={"capacity_policy_revision_id": current.capacity_policy_revision_id}
            )
            if not isinstance(
                current_capacity, SharedWorkerCapacityPolicy
            ) or execution_preset_policy_sha256(current) != execution_preset_policy_sha256(
                expected
            ):
                raise ControlPlaneError(
                    "CONTROL_PRESET_BASE_STALE", "unrelated policy became current"
                )
            already_released[baseline.preset_id] = current
        logicals[baseline.preset_id] = logical
    proposed = shared_capacity_document(baselines, created_at=created_at)
    capacity_logical = session.scalar(
        select(WorkerCapacityPolicyRecord).where(
            WorkerCapacityPolicyRecord.policy_key == CAPACITY_KEY
        )
    )
    if capacity_logical is None:
        capacity_row = record_capacity_policy_revision(
            session, policy_key=CAPACITY_KEY, document=proposed, created_by=operator_id
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=capacity_row.capacity_policy_id,
            capacity_policy_revision_id=capacity_row.capacity_policy_revision_id,
        )
        capacity = resolve_released_capacity_policy(
            session, capacity_row.capacity_policy_revision_id
        )
    else:
        if capacity_logical.state != "ACTIVE" or capacity_logical.current_revision_id is None:
            raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "shared capacity retired")
        capacity = resolve_released_capacity_policy(session, capacity_logical.current_revision_id)
    if not isinstance(capacity, SharedWorkerCapacityPolicy):
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "shared capacity family differs"
        )
    pools = {p.pool_key: set(str(r) for r in p.roles) for p in capacity.pools}
    for preset in baselines:
        for policy in preset.role_policies:
            if str(policy.role) not in pools.get(policy.worker_pool_key, set()):
                raise ControlPlaneError(
                    "CONTROL_SHARED_POOL_MISSING",
                    "publish a reviewed capacity successor for new pools",
                )
    drafts = []
    for baseline in baselines:
        if baseline.preset_id in already_released:
            current = already_released[baseline.preset_id]
            if current.capacity_policy_revision_id != capacity.capacity_policy_revision_id:
                raise ControlPlaneError(
                    "CONTROL_CAPACITY_POINTER_INVALID", "replay uses a different shared capacity"
                )
            drafts.append(current)
            continue
        if baseline.capacity_policy_revision_id == capacity.capacity_policy_revision_id:
            drafts.append(baseline)
            continue
        logical = logicals[baseline.preset_id]
        pending = tuple(
            session.scalars(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_id == baseline.preset_id,
                    ExecutionPresetRevisionRecord.state == "DRAFT",
                    ExecutionPresetRevisionRecord.revision_number > baseline.revision_number,
                )
            )
        )
        if pending:
            if len(pending) != 1:
                raise ControlPlaneError("CONTROL_SHARED_DRAFT_CONFLICT", "multiple pending drafts")
            draft = validated_preset(pending[0])
            expected = baseline.model_copy(
                update={"capacity_policy_revision_id": capacity.capacity_policy_revision_id}
            )
            if execution_preset_policy_sha256(expected) != execution_preset_policy_sha256(draft):
                raise ControlPlaneError(
                    "CONTROL_SHARED_DRAFT_CONFLICT", "unrelated draft must be resolved first"
                )
        else:
            values: dict[str, Any] = dict(
                session=session,
                preset_key=logical.preset_key,
                display_name=baseline.display_name,
                description=baseline.description,
                role_policies=[p.model_dump(mode="json") for p in baseline.role_policies],
                capacity_policy_revision_id=capacity.capacity_policy_revision_id,
                general_knowledge_policy=str(baseline.general_knowledge_policy),
                compatible_workflow_protocols=list(baseline.compatible_workflow_protocols),
                created_by=operator_id,
                created_at=created_at,
            )
            if isinstance(baseline, ExecutionPresetRevisionV2):
                row = create_execution_preset_draft_v2(
                    **values, retrieval_policy=baseline.retrieval_policy.model_dump(mode="json")
                )
            else:
                row = create_execution_preset_draft(**values)
            draft = validated_preset(row)
        drafts.append(draft)
    return SharedSlotTransition(capacity, tuple(drafts))


def release_shared_slot_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    baselines: tuple[Preset, ...],
    operator_id: str,
    source_commit: str,
    created_at: datetime,
    authorize: Callable[[str], None],
    require_installed_units: Callable[[], None],
) -> SharedSlotTransition:
    """Publish metadata-only acceptance; not a model/content quality canary.

    A transport interruption leaves drafts/evidence, not an invented success.
    Replay with the same predecessor accepts already-published exact successors.
    """
    authorize(operator_id)
    with sessions.begin() as session:
        prepared = prepare_shared_slot_controls(
            session,
            baselines=baselines,
            operator_id=operator_id,
            created_at=created_at,
            require_installed_units=require_installed_units,
        )
    released = []
    for baseline, draft in zip(baselines, prepared.drafts, strict=True):
        if draft.state == "RELEASED":
            released.append(draft)
            continue
        with sessions.begin() as session:
            cases = (
                "EXPLICIT_SHARED_CAPACITY_TRANSITION",
                "PROMPTS_ROLES_AND_RETRIEVAL_UNCHANGED",
                "CHAT_SLOT_EXCLUDED",
                "HOST_AND_PER_SLOT_CEILINGS_PRESERVED",
                *validate_preset_model_admission(session, draft, observed_at=created_at),
            )
        body = dict(
            schema_version="execution-preset-evaluation-report/1.0",
            evaluated_preset_revision_id=draft.preset_revision_id,
            evaluated_policy_sha256=execution_preset_policy_sha256(draft),
            scope="NON_LIVE",
            outcome="PASS",
            quality_score_permille=None,
            cases_total=len(cases),
            cases_passed=len(cases),
            summary_code="CONTRACT_VALIDATION",
            completed_at=created_at.isoformat().replace("+00:00", "Z"),
        )
        report = ExecutionPresetEvaluationReport.model_validate(
            body | {"report_sha256": content_sha256(body)}
        )
        authorize(operator_id)
        artifact = publisher.publish_bytes(
            payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
            logical_name="shared-slot-preset-evaluation.json",
            schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            media_type="application/json",
            artifact_type="control_preset_evaluation",
            idempotency_key="shared-slot-eval:" + report.report_sha256[7:],
            created_at=created_at,
            source_commit=source_commit,
        )
        with sessions.begin() as session:
            session.execute(
                select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID))
            )
            authorize(operator_id)
            require_installed_units()
            logical = session.scalar(
                select(ExecutionPresetRecord)
                .where(ExecutionPresetRecord.preset_id == draft.preset_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if logical is None or logical.current_revision_id != baseline.preset_revision_id:
                raise ControlPlaneError(
                    "CONTROL_PRESET_BASE_STALE", "baseline changed before shared release"
                )
            validate_preset_model_admission(session, draft, observed_at=created_at)
            record_execution_preset_evaluation(
                session,
                document=report.model_dump(mode="json"),
                report_artifact=artifact.pointer,
                created_by=operator_id,
            )
            result = release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=operator_id,
                released_at=created_at,
            )
            released.append(validated_preset(result))
    return SharedSlotTransition(prepared.capacity, tuple(released))
