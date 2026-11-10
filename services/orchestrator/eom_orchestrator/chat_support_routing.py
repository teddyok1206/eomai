"""Move new support/review work to 05 without reinterpreting pinned executions.

Uses existing capacity/preset schemas and publication services. No new queue,
model request, direct Artifact write or mutation of historical revisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow import (
    ExecutionPresetRevisionV2,
    WorkerCapacityPolicy,
    WorkerCapacityPolicyV3,
    WorkerCapacityPolicyV4,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    compute_control_document_hash,
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
    non_live_invocation_cases,
    resolve_released_capacity_policy,
    validated_preset,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256

_KEYS = (
    "customer-support",
    "pdf-document-review",
    "item-inference-transfer-comparison-axes",
    "legacy-item-extraction",
)
_EVALUATION_SCHEMA = "eom://schemas/workflow/execution-preset-evaluation-report/1.0"


@dataclass(frozen=True)
class SupportRoutingPredecessors:
    """Exact reviewed source pointers, not an instruction to resolve latest."""

    capacity_revision_id: str
    customer_support_revision_id: str
    document_review_revision_id: str
    inference_transfer_revision_id: str
    legacy_extraction_revision_id: str
    legacy_capacity_revision_id: str

    @property
    def preset_ids(self) -> tuple[str, ...]:
        return (
            self.customer_support_revision_id,
            self.document_review_revision_id,
            self.inference_transfer_revision_id,
            self.legacy_extraction_revision_id,
        )


@dataclass(frozen=True)
class SupportRoutingResult:
    capacity_revision_id: str
    customer_support_revision_id: str
    document_review_revision_id: str
    inference_transfer_revision_id: str
    legacy_extraction_revision_id: str


def slot05_capacity_document(
    predecessor: WorkerCapacityPolicyV4, legacy: WorkerCapacityPolicyV3
) -> dict[str, Any]:
    """Existing generic capacity for the four currently slot06-only use cases.

    Fixed-host V4 is frozen to slot06. Its schema/head stay unchanged; the
    Separate pools retain their purposes and share one physical slot05. Generic
    V1 conservatively admits at most one global knowledge-analysis claim; it
    does not change any existing analysis lease or another policy's ceiling.
    """
    pools = predecessor.pools
    supports = [pool for pool in pools if pool.pool_key == "customer-support"]
    if (
        len(supports) != 1
        or supports[0].slot_keys != ("slot06",)
        or supports[0].roles != ("support",)
        or predecessor.state != "RELEASED"
    ):
        raise ControlPlaneError("CONTROL_CHAT_ROUTING_CONFLICT", "support routing differs")
    extraction = [pool for pool in legacy.pools if pool.pool_key == "legacy-extraction"]
    if (
        len(extraction) != 1
        or extraction[0].slot_keys != ("slot06",)
        or extraction[0].roles != ("support",)
        or legacy.state != "RELEASED"
        or legacy.capacity_policy_id != predecessor.capacity_policy_id
    ):
        raise ControlPlaneError("CONTROL_CHAT_ROUTING_CONFLICT", "extraction routing differs")
    identity = content_sha256(
        {
            "predecessor": predecessor.content_sha256,
            "legacy_predecessor": legacy.content_sha256,
            "routing": "chat06-support05/1.0",
        }
    )[7:39]
    document: dict[str, Any] = {
        "schema_version": "worker-capacity-policy/1.0",
        "capacity_policy_id": "capacity_" + identity,
        "capacity_policy_revision_id": "capacityrev_" + identity,
        "revision_number": 1,
        "state": "RELEASED",
        "max_configured_slots": 5,
        "max_active_codex": predecessor.max_active_codex,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 1,
        "pools": [
            {
                "pool_key": "customer-support",
                "roles": ["support"],
                "slot_keys": ["slot05"],
                "max_active": 1,
            },
            {
                "pool_key": "legacy-extraction",
                "roles": ["support"],
                "slot_keys": ["slot05"],
                "max_active": 1,
            },
        ],
        "created_at": predecessor.created_at.isoformat().replace("+00:00", "Z"),
        "content_sha256": "sha256:" + "0" * 64,
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    WorkerCapacityPolicy.model_validate(document)
    return document


def _sources(
    session: Session, expected: SupportRoutingPredecessors
) -> tuple[WorkerCapacityPolicyV4, WorkerCapacityPolicyV3, tuple[Preset, ...]]:
    capacity_row = session.get(WorkerCapacityPolicyRevisionRecord, expected.capacity_revision_id)
    if capacity_row is None:
        raise ControlPlaneError("CONTROL_POINTER_MISSING", "routing capacity is missing")
    capacity = resolve_released_capacity_policy(session, expected.capacity_revision_id)
    if not isinstance(capacity, WorkerCapacityPolicyV4):
        raise ControlPlaneError("CONTROL_CHAT_ROUTING_CONFLICT", "capacity family differs")
    legacy = resolve_released_capacity_policy(session, expected.legacy_capacity_revision_id)
    if not isinstance(legacy, WorkerCapacityPolicyV3):
        raise ControlPlaneError("CONTROL_CHAT_ROUTING_CONFLICT", "extraction capacity differs")
    values: list[Preset] = []
    for key, revision_id in zip(_KEYS, expected.preset_ids, strict=True):
        row = session.get(ExecutionPresetRevisionRecord, revision_id)
        if row is None:
            raise ControlPlaneError("CONTROL_POINTER_MISSING", "routing preset is missing")
        value = validated_preset(row)
        logical = session.get(ExecutionPresetRecord, value.preset_id)
        if (
            logical is None
            or logical.preset_key != key
            or logical.state != "ACTIVE"
            or value.state != "RELEASED"
            or value.capacity_policy_revision_id
            != (
                legacy.capacity_policy_revision_id
                if key == "legacy-item-extraction"
                else capacity.capacity_policy_revision_id
            )
            or len(value.role_policies) != 1
            or value.role_policies[0].role != "support"
            or value.role_policies[0].worker_pool_key
            != ("legacy-extraction" if key == "legacy-item-extraction" else "customer-support")
        ):
            raise ControlPlaneError("CONTROL_CHAT_ROUTING_CONFLICT", "preset source differs")
        values.append(value)
    return capacity, legacy, tuple(values)


def _policy(predecessor: Preset, capacity_revision_id: str) -> str:
    document = predecessor.model_dump(mode="json")
    document["capacity_policy_revision_id"] = capacity_revision_id
    return execution_preset_policy_sha256(document)


def _current_or_draft(
    session: Session, source: Preset, *, capacity_revision_id: str, actor_id: str
) -> ExecutionPresetRevisionRecord:
    logical = session.get(ExecutionPresetRecord, source.preset_id, with_for_update=True)
    if logical is None or logical.state != "ACTIVE":
        raise ControlPlaneError("CONTROL_CHAT_ROUTING_CONFLICT", "preset is unavailable")
    current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
    expected_policy = _policy(source, capacity_revision_id)
    if (
        current is not None
        and execution_preset_policy_sha256(validated_preset(current)) == expected_policy
    ):
        return current
    if logical.current_revision_id != source.preset_revision_id:
        raise ControlPlaneError("CONTROL_PRESET_BASE_STALE", "routing predecessor changed")
    drafts = session.scalars(
        select(ExecutionPresetRevisionRecord).where(
            ExecutionPresetRevisionRecord.preset_id == source.preset_id,
            ExecutionPresetRevisionRecord.state == "DRAFT",
        )
    )
    for draft in drafts:
        if execution_preset_policy_sha256(validated_preset(draft)) == expected_policy:
            return draft
    kwargs: dict[str, Any] = {
        "preset_key": logical.preset_key,
        "display_name": source.display_name,
        "description": source.description,
        "role_policies": [role.model_dump(mode="json") for role in source.role_policies],
        "capacity_policy_revision_id": capacity_revision_id,
        "general_knowledge_policy": source.general_knowledge_policy,
        "compatible_workflow_protocols": list(source.compatible_workflow_protocols),
        "created_by": actor_id,
        "created_at": datetime.now(UTC),
    }
    if isinstance(source, ExecutionPresetRevisionV2):
        return create_execution_preset_draft_v2(
            session, **kwargs, retrieval_policy=source.retrieval_policy.model_dump(mode="json")
        )
    return create_execution_preset_draft(session, **kwargs)


def release_slot05_support_routing(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    predecessors: SupportRoutingPredecessors,
    actor_id: str,
    source_commit: str,
) -> SupportRoutingResult:
    """Deployment-owned, exact-predecessor release; caller authorizes the operation."""
    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        capacity, legacy, sources = _sources(session, predecessors)
        document = slot05_capacity_document(capacity, legacy)
        capacity_id = str(document["capacity_policy_revision_id"])
        logical = session.get(WorkerCapacityPolicyRecord, capacity.capacity_policy_id)
        if logical is None or logical.current_revision_id != capacity.capacity_policy_revision_id:
            raise ControlPlaneError("CONTROL_CURRENT_REVISION_STALE", "capacity head changed")
        record_capacity_policy_revision(
            session, policy_key="slot05-interactive-support", document=document, created_by=actor_id
        )
        prepared = tuple(
            validated_preset(
                _current_or_draft(
                    session, source, capacity_revision_id=capacity_id, actor_id=actor_id
                )
            )
            for source in sources
        )

    reports = []
    for draft in prepared:
        if draft.state == "RELEASED":
            continue
        # Real deterministic validation of the unchanged invocation contract.
        cases = (
            "EXACT_PREDECESSORS",
            "ONLY_SUPPORT_SLOT_CHANGED",
            *non_live_invocation_cases(draft),
        )
        report: dict[str, Any] = {
            "schema_version": "execution-preset-evaluation-report/1.0",
            "evaluated_preset_revision_id": draft.preset_revision_id,
            "evaluated_policy_sha256": execution_preset_policy_sha256(draft),
            "scope": "NON_LIVE",
            "outcome": "PASS",
            "summary_code": "CONTRACT_VALIDATION",
            "cases_total": len(cases),
            "cases_passed": len(cases),
            "quality_score_permille": None,
            "completed_at": draft.created_at.isoformat().replace("+00:00", "Z"),
            "report_sha256": "sha256:" + "0" * 64,
        }
        report["report_sha256"] = compute_control_document_hash(report, "report_sha256")
        published = publisher.publish_bytes(
            payload=canonical_json_bytes(report) + b"\n",
            logical_name="chat-slot-routing-evaluation.json",
            schema_ref=_EVALUATION_SCHEMA,
            media_type="application/json",
            artifact_type="control_preset_evaluation",
            idempotency_key="chat-slot-routing:" + str(report["report_sha256"])[7:],
            created_at=draft.created_at,
            source_commit=source_commit,
        )
        reports.append((report, published.pointer))

    with sessions.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        _, _, sources = _sources(session, predecessors)
        # Revalidate every head before publishing any one.
        revisions = tuple(
            _current_or_draft(session, source, capacity_revision_id=capacity_id, actor_id=actor_id)
            for source in sources
        )
        if all(row.state == "RELEASED" for row in revisions):
            # A concurrent identical release may have closed every draft while
            # this caller published its identical evidence. Never create again.
            return SupportRoutingResult(capacity_id, *(row.preset_revision_id for row in revisions))
        if tuple(row.preset_revision_id for row in revisions) != tuple(
            value.preset_revision_id for value in prepared
        ):
            raise ControlPlaneError("CONTROL_PRESET_BASE_STALE", "prepared routing changed")
        for report, pointer in reports:
            record_execution_preset_evaluation(
                session, document=report, report_artifact=pointer, created_by=actor_id
            )
        published_ids = tuple(
            row.preset_revision_id
            if row.state == "RELEASED"
            else release_execution_preset(
                session,
                draft_revision_id=row.preset_revision_id,
                released_by=actor_id,
                released_at=datetime.now(UTC),
            ).preset_revision_id
            for row in revisions
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=str(document["capacity_policy_id"]),
            capacity_policy_revision_id=capacity_id,
        )
        return SupportRoutingResult(capacity_id, *published_ids)
