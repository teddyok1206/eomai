"""Resolve canonical account-scoped model proofs, without launching workers."""

from __future__ import annotations

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.codex_compatibility import CodexCompatibilityReport
from eom_workflow.control_plane import ModelCapability, ReasoningEffort
from sqlalchemy import Connection, Engine, select
from sqlalchemy.orm import Session

from eom_orchestrator.codex_compatibility_policy import (
    COMPATIBILITY_REPORT_SCHEMA,
    load_committed_compatibility_report,
)
from eom_orchestrator.control_models import (
    CodexAuthAssignmentRevisionRecord,
    CodexAuthBindingRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord, WorkerSlotRecord
from eom_orchestrator.reviewed_capability_policy import ReviewedCapabilityPolicy


def enrollment_compatibility_run_id(
    assignment_revision_id: str, policy: ReviewedCapabilityPolicy
) -> str:
    # An exact policy change invalidates lookup, rather than silently carrying a
    # previous account/runtime's proof into a new protected configuration.
    return (
        "codexcompat_"
        + content_sha256(
            {
                "assignment_revision_id": assignment_revision_id,
                "policy": policy.model_dump(mode="json"),
            }
        ).removeprefix("sha256:")[:32]
    )


def enrollment_candidate_pairs(
    policy: ReviewedCapabilityPolicy, *, binding_id: str, slot_id: str
) -> tuple[tuple[str, ReasoningEffort], ...]:
    """Existing scopes define candidates, never permission for the new account."""

    pairs = {
        (entry.model, ReasoningEffort(effort))
        for entry in policy.models
        if any(
            pin.binding_id == binding_id and getattr(pin, "slot_id", slot_id) == slot_id
            for pin in entry.bindings or ()
        )
        for effort in entry.reasoning_efforts
    }
    # Try the newer configured models first, with less expensive effort first.
    efforts = {
        name: index for index, name in enumerate(("minimal", "low", "medium", "high", "xhigh"))
    }
    return tuple(sorted(pairs, key=lambda pair: (pair[0], -efforts[pair[1]]), reverse=True))


def enrollment_verified_capabilities(
    session: Session, *, binding: CodexAuthBindingRecord, policy: ReviewedCapabilityPolicy
) -> tuple[ModelCapability, ...]:
    capabilities = _proved_capabilities(session, binding=binding, policy=policy)
    if not capabilities or binding.worker_slot_id not in {"01", "02"}:
        return capabilities
    # Authoring/review still require the exact pair on BOTH current accounts.
    # The peer may have its original reviewed scope or its own canonical probe.
    peer_id = "02" if binding.worker_slot_id == "01" else "01"
    peer = session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == peer_id)
    )
    slot = session.get(WorkerSlotRecord, peer_id)
    if (
        peer is None
        or slot is None
        or not slot.enabled
        or slot.role != {"01": "authoring", "02": "review"}[peer_id]
    ):
        return ()
    peer_pairs = {
        (entry.model, ReasoningEffort(effort))
        for entry in policy.models
        if entry.bindings is None
        or any(
            pin.binding_id == peer.binding_id
            and pin.assignment_revision_id == peer.current_assignment_revision_id
            and getattr(pin, "slot_id", peer_id) == peer_id
            for pin in entry.bindings
        )
        for effort in entry.reasoning_efforts
    }
    if not peer_pairs:
        peer_pairs = {
            (entry.model, effort)
            for entry in _proved_capabilities(session, binding=peer, policy=policy)
            for effort in entry.reasoning_efforts
        }
    return tuple(
        ModelCapability(model=entry.model, reasoning_efforts=efforts, state="AVAILABLE")
        for entry in capabilities
        if (
            efforts := tuple(
                effort for effort in entry.reasoning_efforts if (entry.model, effort) in peer_pairs
            )
        )
    )


def load_enrollment_model_verification_report(
    session: Session, *, binding: CodexAuthBindingRecord, policy: ReviewedCapabilityPolicy
) -> CodexCompatibilityReport | None:
    """Resolve canonical exact-policy proof, never trust a local result JSON as admission."""

    if binding.current_assignment_revision_id is None:
        return None
    assignment = session.get(
        CodexAuthAssignmentRevisionRecord, binding.current_assignment_revision_id
    )
    if assignment is None or assignment.binding_id != binding.binding_id:
        return None
    run_id = enrollment_compatibility_run_id(assignment.assignment_revision_id, policy)
    row = session.execute(
        select(JobRecord, ArtifactRevisionRecord)
        .join(ArtifactRevisionRecord, ArtifactRevisionRecord.revision_id == JobRecord.revision_id)
        .where(JobRecord.idempotency_key == run_id, JobRecord.status == "SUCCEEDED")
    ).one_or_none()
    if row is None:
        return None
    _job, revision = row
    report = load_committed_compatibility_report(
        _engine(session),
        ArtifactMemberPointer(
            artifact_id=revision.logical_artifact_id,
            artifact_revision_id=revision.revision_id,
            member_path="report.json",
            media_type="application/json",
            schema_ref=COMPATIBILITY_REPORT_SCHEMA,
            sha256=revision.content_hash,
        ),
    )
    candidates = set(
        enrollment_candidate_pairs(
            policy, binding_id=binding.binding_id, slot_id=binding.worker_slot_id
        )
    )
    if (
        report.runtime != policy.compatibility_runtime
        or report.request.run_id != run_id
        or report.request.created_at != assignment.assigned_at
        or any(
            case.binding_id != binding.binding_id
            or case.slot_id != binding.worker_slot_id
            or case.assignment_revision_id != assignment.assignment_revision_id
            or case.expected_resource_version > binding.resource_version
            or (case.model, str(case.reasoning_effort)) not in candidates
            for case in report.cases
        )
    ):
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_POLICY_MISMATCH", "automatic model proof differs"
        )
    return report


def _proved_capabilities(
    session: Session, *, binding: CodexAuthBindingRecord, policy: ReviewedCapabilityPolicy
) -> tuple[ModelCapability, ...]:
    report = load_enrollment_model_verification_report(session, binding=binding, policy=policy)
    if report is None:
        return ()
    passed: dict[str, set[ReasoningEffort]] = {}
    for case in report.cases:
        if case.status == "PASS":
            passed.setdefault(case.model, set()).add(case.reasoning_effort)
    return tuple(
        ModelCapability(model=model, reasoning_efforts=tuple(sorted(efforts)), state="AVAILABLE")
        for model, efforts in sorted(passed.items())
    )


def _engine(session: Session) -> Engine:
    bind = session.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind
