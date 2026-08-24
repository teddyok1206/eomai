"""Deterministic released-preset resolution into one immutable execution plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts import (
    EducationalRetrievalRequirement,
    EvidenceBundlePublicationResultV2,
    KnowledgeAnalysisRequestV2,
)
from eom_identifiers import content_sha256, new_execution_plan_id
from eom_workflow.control_plane import (
    ExecutionPresetRevision,
    ExecutionPresetRevisionV2,
    ResolvedExecutionPlan,
    ResolvedExecutionPlanV2,
    ResolvedExecutionPlanV3,
    ResolvedStepExecution,
    ResolvedStepExecutionV3,
    WorkerRole,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    compute_control_document_hash,
    record_knowledge_backed_execution_plan,
    record_resolved_execution_plan,
)

RESOLVER_VERSION = "1.0.0"
KNOWLEDGE_BACKED_RESOLVER_VERSION = "3.0.0"


@dataclass(frozen=True)
class ExecutionStepRequirement:
    """Workflow-owned step identity and role, in deterministic execution-plan order."""

    step_key: str
    role: WorkerRole


def current_knowledge_backed_preset(
    session: Session,
    *,
    preset_key: str,
    workflow_role_schema_version: str,
) -> ExecutionPresetRevisionV2:
    """Resolve one published V2 preset before Catalog evidence creation."""

    logical = session.scalar(
        select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == preset_key)
    )
    revision = (
        session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if logical is not None and logical.current_revision_id is not None
        else None
    )
    if (
        logical is None
        or logical.state != "ACTIVE"
        or revision is None
        or revision.preset_id != logical.preset_id
        or revision.state != "RELEASED"
        or workflow_role_schema_version not in revision.compatible_workflow_protocols
    ):
        raise ControlPlaneError(
            "CONTROL_PRESET_NOT_PUBLISHED", "knowledge-backed preset is not published"
        )
    try:
        return ExecutionPresetRevisionV2.model_validate(revision.canonical_document)
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "knowledge-backed request requires a V2 preset"
        ) from exc


def validate_educational_retrieval_policy(
    preset: ExecutionPresetRevisionV2,
    requirement: EducationalRetrievalRequirement,
) -> None:
    """Fail before Catalog or workflow creation when educational intent exceeds preset bounds."""

    policy = preset.retrieval_policy
    if (
        requirement.corpus_key not in policy.allowed_corpus_keys
        or requirement.query_kind not in policy.allowed_query_kinds
        or not set(requirement.source_classes).issubset(policy.allowed_source_classes)
    ):
        raise ControlPlaneError(
            "CONTROL_RETRIEVAL_POLICY_DENIED", "educational retrieval exceeds preset policy"
        )


def resolve_knowledge_backed_execution_plan(
    session: Session,
    *,
    preset_revision_id: str,
    requirement: EducationalRetrievalRequirement,
    evidence: EvidenceBundlePublicationResultV2,
    dependencies: ResolvedPlanDependencyEvidence,
    steps: tuple[ExecutionStepRequirement, ...],
    resolved_at: datetime | None = None,
) -> ResolvedExecutionPlanV3:
    """Pin an exact preset and Catalog-produced Evidence Bundle to one fresh workflow."""

    if not steps:
        raise ControlPlaneError("CONTROL_PLAN_STEPS_MISSING", "execution plan has no steps")
    existing = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == dependencies.workflow_id
        )
    )
    if existing is not None:
        return ResolvedExecutionPlanV3.model_validate(existing.canonical_document)
    preset_record = session.get(ExecutionPresetRevisionRecord, preset_revision_id)
    if preset_record is None or preset_record.state != "RELEASED":
        raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "pinned preset is stale")
    try:
        preset = ExecutionPresetRevisionV2.model_validate(preset_record.canonical_document)
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "knowledge-backed request requires a V2 preset"
        ) from exc
    validate_educational_retrieval_policy(preset, requirement)
    policy = preset.retrieval_policy
    if (
        evidence.access_policy_revision_id != policy.access_policy_revision_id
        or evidence.access_policy_sha256 != policy.access_policy_sha256
        or dependencies.graph_snapshot_revision_id
        != evidence.graph_snapshot.graph_snapshot_revision_id
        or dependencies.evidence_bundle_revision_id != evidence.evidence_bundle_revision_id
    ):
        raise ControlPlaneError(
            "CONTROL_PLAN_DEPENDENCY_MISMATCH", "Evidence Bundle pointer differs from policy"
        )
    policies = {item.role: item for item in preset.role_policies}
    resolved_steps: list[ResolvedStepExecutionV3] = []
    seen_keys: set[str] = set()
    for required in steps:
        if required.step_key in seen_keys:
            raise ControlPlaneError("CONTROL_PLAN_STEP_DUPLICATE", "execution step is duplicated")
        seen_keys.add(required.step_key)
        role_policy = policies.get(required.role)
        if role_policy is None:
            raise ControlPlaneError(
                "CONTROL_PRESET_ROLE_MISSING", "execution preset lacks a required role"
            )
        candidate = role_policy.model_candidates[0]
        resolved_steps.append(
            ResolvedStepExecutionV3(
                step_key=required.step_key,
                role=required.role,
                model=candidate.model,
                reasoning_effort=candidate.reasoning_effort,
                instruction_bundle=role_policy.instruction_bundle,
                reference_bundle=role_policy.reference_bundle,
                worker_pool_key=role_policy.worker_pool_key,
                timeout_seconds=role_policy.timeout_seconds,
                sandbox=role_policy.sandbox,
                network=role_policy.network,
                general_knowledge_mode=(
                    "DENIED"
                    if preset.general_knowledge_policy == "DENY"
                    else "ALLOWED_WITH_PROVENANCE"
                ),
                evidence_access=role_policy.evidence_access,
            )
        )
    actual_resolved_at = resolved_at or datetime.now(UTC)
    document: dict[str, object] = {
        "schema_version": "resolved-execution-plan/3.0",
        "plan_id": new_execution_plan_id(),
        "workflow_id": dependencies.workflow_id,
        "workload_class": "KNOWLEDGE_BACKED_ITEM",
        "preset_id": preset.preset_id,
        "preset_revision_id": preset.preset_revision_id,
        "preset_sha256": preset.content_sha256,
        "workflow_definition_key": dependencies.workflow_definition_key,
        "workflow_definition_version": dependencies.workflow_definition_version,
        "workflow_definition_sha256": dependencies.workflow_definition_sha256,
        "content_pack_release_id": dependencies.content_pack_release_id,
        "content_pack_sha256": dependencies.content_pack_sha256,
        "capacity_policy_revision_id": preset.capacity_policy_revision_id,
        "retrieval_requirement": requirement.model_dump(mode="json"),
        "retrieval_requirement_sha256": content_sha256(requirement.model_dump(mode="json")),
        "retrieval_request_id": evidence.retrieval_request_id,
        "retrieval_request_sha256": evidence.retrieval_request_sha256,
        "graph_snapshot": evidence.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": evidence.access_policy_revision_id,
        "access_policy_sha256": evidence.access_policy_sha256,
        "requester_permissions_sha256": evidence.requester_permissions_sha256,
        "evidence_bundle_id": evidence.evidence_bundle_id,
        "evidence_bundle_revision_id": evidence.evidence_bundle_revision_id,
        "evidence_manifest_artifact": evidence.manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": evidence.manifest_sha256,
        "evidence_context_artifact": evidence.context_artifact.model_dump(mode="json"),
        "steps": [step.model_dump(mode="json") for step in resolved_steps],
        "resolver_version": KNOWLEDGE_BACKED_RESOLVER_VERSION,
        "resolved_at": actual_resolved_at.isoformat().replace("+00:00", "Z"),
        "plan_sha256": "sha256:" + "0" * 64,
    }
    document["plan_sha256"] = compute_control_document_hash(document, "plan_sha256")
    model = ResolvedExecutionPlanV3.model_validate(document)
    record = record_knowledge_backed_execution_plan(
        session,
        document=model.model_dump(mode="json"),
        dependencies=dependencies,
    )
    return ResolvedExecutionPlanV3.model_validate(record.canonical_document)


def resolve_execution_plan(
    session: Session,
    *,
    preset_key: str,
    dependencies: ResolvedPlanDependencyEvidence,
    steps: tuple[ExecutionStepRequirement, ...],
    resolved_at: datetime | None = None,
) -> ResolvedExecutionPlan:
    """Resolve the currently published preset once for one exact workflow.

    Existing workflow plans are returned byte-for-byte. No current pointer is consulted during a
    replay after the first plan has been persisted.
    """

    if not steps:
        raise ControlPlaneError("CONTROL_PLAN_STEPS_MISSING", "execution plan has no steps")
    existing = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == dependencies.workflow_id
        )
    )
    if existing is not None:
        return ResolvedExecutionPlan.model_validate(existing.canonical_document)

    logical = session.scalar(
        select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == preset_key)
    )
    if logical is None or logical.state != "ACTIVE" or logical.current_revision_id is None:
        raise ControlPlaneError(
            "CONTROL_PRESET_NOT_PUBLISHED", "execution preset has no published revision"
        )
    revision = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
    if revision is None or revision.preset_id != logical.preset_id or revision.state != "RELEASED":
        raise ControlPlaneError(
            "CONTROL_PRESET_POINTER_INVALID", "published execution preset is stale"
        )
    preset = ExecutionPresetRevision.model_validate(revision.canonical_document)
    policies = {policy.role: policy for policy in preset.role_policies}
    if len(policies) != len(preset.role_policies):
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "execution preset has duplicate role policies"
        )

    resolved_steps: list[ResolvedStepExecution] = []
    seen_keys: set[str] = set()
    for required in steps:
        if required.step_key in seen_keys:
            raise ControlPlaneError("CONTROL_PLAN_STEP_DUPLICATE", "execution step is duplicated")
        seen_keys.add(required.step_key)
        policy = policies.get(required.role)
        if policy is None:
            raise ControlPlaneError(
                "CONTROL_PRESET_ROLE_MISSING", "execution preset does not define a required role"
            )
        candidate = policy.model_candidates[0]
        resolved_steps.append(
            ResolvedStepExecution(
                step_key=required.step_key,
                role=required.role,
                model=candidate.model,
                reasoning_effort=candidate.reasoning_effort,
                instruction_bundle=policy.instruction_bundle,
                reference_bundle=policy.reference_bundle,
                worker_pool_key=policy.worker_pool_key,
                timeout_seconds=policy.timeout_seconds,
                sandbox=policy.sandbox,
                network=policy.network,
                general_knowledge_mode=(
                    "DENIED"
                    if preset.general_knowledge_policy == "DENY"
                    else "ALLOWED_WITH_PROVENANCE"
                ),
            )
        )

    actual_resolved_at = resolved_at or datetime.now(UTC)
    if actual_resolved_at.tzinfo is None or actual_resolved_at.utcoffset() is None:
        raise ControlPlaneError("CONTROL_TIMESTAMP_INVALID", "resolution timestamp is not UTC")
    document = {
        "schema_version": "resolved-execution-plan/1.0",
        "plan_id": new_execution_plan_id(),
        "workflow_id": dependencies.workflow_id,
        "preset_id": preset.preset_id,
        "preset_revision_id": preset.preset_revision_id,
        "preset_sha256": preset.content_sha256,
        "workflow_definition_key": dependencies.workflow_definition_key,
        "workflow_definition_version": dependencies.workflow_definition_version,
        "workflow_definition_sha256": dependencies.workflow_definition_sha256,
        "content_pack_release_id": dependencies.content_pack_release_id,
        "content_pack_sha256": dependencies.content_pack_sha256,
        "capacity_policy_revision_id": preset.capacity_policy_revision_id,
        "graph_snapshot_revision_id": dependencies.graph_snapshot_revision_id,
        "evidence_bundle_revision_id": dependencies.evidence_bundle_revision_id,
        "steps": [step.model_dump(mode="json") for step in resolved_steps],
        "resolver_version": RESOLVER_VERSION,
        "resolved_at": actual_resolved_at,
        "plan_sha256": "sha256:" + "0" * 64,
    }
    normalized = ResolvedExecutionPlan.model_validate(document).model_dump(mode="json")
    normalized["plan_sha256"] = compute_control_document_hash(normalized, "plan_sha256")
    model = ResolvedExecutionPlan.model_validate(normalized)
    record = record_resolved_execution_plan(
        session,
        document=model.model_dump(mode="json"),
        dependencies=dependencies,
    )
    return ResolvedExecutionPlan.model_validate(record.canonical_document)


def resolve_knowledge_analysis_plan(
    session: Session,
    *,
    workflow_id: str,
    workflow_definition_version: str,
    workflow_definition_sha256: str,
    workflow_role_schema_version: str,
    request: KnowledgeAnalysisRequestV2,
    resolved_at: datetime | None = None,
) -> ResolvedExecutionPlanV2:
    """Resolve one exact released support policy without consulting a mutable latest pointer."""

    existing = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == workflow_id
        )
    )
    if existing is not None:
        return ResolvedExecutionPlanV2.model_validate(existing.canonical_document)
    preset_record = session.get(ExecutionPresetRevisionRecord, request.execution_preset_revision_id)
    logical = session.get(ExecutionPresetRecord, request.execution_preset_id)
    if (
        preset_record is None
        or logical is None
        or preset_record.preset_id != logical.preset_id
        or preset_record.state != "RELEASED"
        or preset_record.content_sha256 != request.execution_preset_sha256
        or workflow_role_schema_version not in preset_record.compatible_workflow_protocols
    ):
        raise ControlPlaneError(
            "CONTROL_PRESET_POINTER_INVALID", "knowledge analysis preset pointer is stale"
        )
    preset = ExecutionPresetRevision.model_validate(preset_record.canonical_document)
    support_policies = [policy for policy in preset.role_policies if policy.role == "support"]
    if len(support_policies) != 1:
        raise ControlPlaneError(
            "CONTROL_PRESET_ROLE_MISSING", "knowledge analysis preset needs one support policy"
        )
    policy = support_policies[0]
    if policy.worker_pool_key != "support" or policy.reference_bundle is not None:
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID",
            "knowledge analysis support policy has an incompatible worker or reference bundle",
        )
    knowledge_allowed = request.general_knowledge_mode == "AUXILIARY_UNATTRIBUTED"
    if knowledge_allowed and preset.general_knowledge_policy == "DENY":
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "preset denies requested general knowledge mode"
        )
    candidate = policy.model_candidates[0]
    step = ResolvedStepExecution(
        step_key="analyze",
        role=WorkerRole.SUPPORT,
        model=candidate.model,
        reasoning_effort=candidate.reasoning_effort,
        instruction_bundle=policy.instruction_bundle,
        reference_bundle=None,
        worker_pool_key="support",
        timeout_seconds=policy.timeout_seconds,
        sandbox=policy.sandbox,
        network=policy.network,
        general_knowledge_mode=("ALLOWED_WITH_PROVENANCE" if knowledge_allowed else "DENIED"),
    )
    source = request.source.artifact_member
    actual_resolved_at = resolved_at or datetime.now(UTC)
    document: dict[str, object] = {
        "schema_version": "resolved-execution-plan/2.0",
        "plan_id": new_execution_plan_id(),
        "workflow_id": workflow_id,
        "workload_class": "KNOWLEDGE_ANALYSIS",
        "preset_id": preset.preset_id,
        "preset_revision_id": preset.preset_revision_id,
        "preset_sha256": preset.content_sha256,
        "workflow_definition_key": "knowledge-analysis",
        "workflow_definition_version": workflow_definition_version,
        "workflow_definition_sha256": workflow_definition_sha256,
        "analysis_request_id": request.analysis_request_id,
        "analysis_request_sha256": request.request_sha256,
        "source_artifact_id": source.artifact_id,
        "source_artifact_revision_id": source.artifact_revision_id,
        "source_member_path": source.member_path,
        "source_materialized_path": source.materialized_path,
        "source_sha256": source.sha256,
        "source_bytes": source.bytes,
        "source_media_type": source.media_type,
        "source_schema_ref": source.schema_ref,
        "capacity_policy_revision_id": preset.capacity_policy_revision_id,
        "steps": [step.model_dump(mode="json")],
        "resolver_version": "2.0.0",
        "resolved_at": actual_resolved_at,
        "plan_sha256": "sha256:" + "0" * 64,
    }
    document["plan_sha256"] = compute_control_document_hash(document, "plan_sha256")
    model = ResolvedExecutionPlanV2.model_validate(document)
    record = ResolvedExecutionPlanRecord(
        plan_id=model.plan_id,
        workflow_id=model.workflow_id,
        preset_id=model.preset_id,
        preset_revision_id=model.preset_revision_id,
        capacity_policy_revision_id=model.capacity_policy_revision_id,
        graph_snapshot_revision_id=None,
        evidence_bundle_revision_id=None,
        plan_sha256=model.plan_sha256,
        resolver_version=model.resolver_version,
        canonical_document=model.model_dump(mode="json"),
        resolved_at=model.resolved_at,
    )
    session.add(record)
    session.flush()
    session.add(
        ResolvedExecutionPlanStepRecord(
            plan_id=model.plan_id,
            step_key=step.step_key,
            role=step.role,
            model=step.model,
            reasoning_effort=step.reasoning_effort,
            instruction_bundle_revision_id=step.instruction_bundle.bundle_revision_id,
            reference_bundle_revision_id=None,
            worker_pool_key=step.worker_pool_key,
            timeout_seconds=step.timeout_seconds,
            sandbox=step.sandbox,
            network=step.network,
            general_knowledge_mode=step.general_knowledge_mode,
        )
    )
    session.flush()
    return model
