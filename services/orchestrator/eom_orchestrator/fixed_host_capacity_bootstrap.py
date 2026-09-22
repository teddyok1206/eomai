"""Authoritative fixed-host six-slot capacity V4 bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_workflow import WorkerCapacityPolicyV3, WorkerCapacityPolicyV4
from eom_workflow.control_schemas import validate_control_contract
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_bootstrap import _stable_id
from eom_orchestrator.control_models import (
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    publish_capacity_policy_revision,
    record_capacity_policy_revision,
)
from eom_orchestrator.database import transaction
from eom_orchestrator.worker_registry import WorkerSlot

FIXED_HOST_CAPACITY_V4_CREATED_AT = datetime(2026, 9, 17, tzinfo=UTC)


def require_exact_six_slots(slots: tuple[WorkerSlot, ...]) -> None:
    """Require the reviewed role-to-slot topology used by fixed-host capacity V4."""

    actual = tuple((slot.slot_id, slot.role, slot.enabled, slot.gpu) for slot in slots)
    expected = (
        ("01", "authoring", True, False),
        ("02", "review", True, False),
        ("03", "image", True, True),
        ("04", "item_management", True, False),
        ("05", "support", True, False),
        ("06", "support", True, False),
    )
    if actual != expected:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_SLOT_MISMATCH",
            "fixed-host capacity V4 requires the exact six-slot worker registry",
        )


def publish_fixed_host_capacity_v4(
    sessions: sessionmaker[Session],
    *,
    slots: tuple[WorkerSlot, ...],
    actor_id: str,
) -> str:
    """Idempotently publish the shared slot06-aware capacity policy."""

    require_exact_six_slots(slots)
    policy_id = _stable_id("capacity_", "fixed-host")
    revision_id = _stable_id("capacityrev_", "fixed-host:v4")
    document: dict[str, object] = {
        "schema_version": "worker-capacity-policy/1.3",
        "capacity_policy_id": policy_id,
        "capacity_policy_revision_id": revision_id,
        "revision_number": 4,
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
                "pool_key": "customer-support",
                "roles": ["support"],
                "slot_keys": ["slot06"],
                "max_active": 1,
            },
        ],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": FIXED_HOST_CAPACITY_V4_CREATED_AT.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    validate_control_contract("worker-capacity-policy-v4", document)
    policy = WorkerCapacityPolicyV4.model_validate(document)
    with transaction(sessions) as session:
        logical = session.get(WorkerCapacityPolicyRecord, policy_id)
        if logical is not None and logical.current_revision_id not in {
            _stable_id("capacityrev_", "fixed-host:v3"),
            revision_id,
        }:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "fixed-host capacity predecessor differs",
            )
        predecessor = session.get(
            WorkerCapacityPolicyRevisionRecord,
            _stable_id("capacityrev_", "fixed-host:v3"),
        )
        if predecessor is None:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "fixed-host capacity V3 predecessor is missing",
            )
        predecessor_policy = WorkerCapacityPolicyV3.model_validate(predecessor.canonical_document)
        if (
            predecessor.content_sha256 != predecessor_policy.content_sha256
            or compute_control_document_hash(
                predecessor_policy.model_dump(mode="json"),
                "content_sha256",
            )
            != predecessor_policy.content_sha256
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "fixed-host capacity V3 predecessor hash differs",
            )
        existing = session.get(WorkerCapacityPolicyRevisionRecord, revision_id)
        if existing is not None and (
            existing.canonical_document != policy.model_dump(mode="json")
            or existing.content_sha256 != policy.content_sha256
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID",
                "fixed-host capacity V4 differs",
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
