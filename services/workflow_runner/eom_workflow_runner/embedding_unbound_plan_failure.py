"""Official root/schema-owner closure of an original failed unbound INDEX parent."""

from __future__ import annotations

from eom_catalog_service.embedding_unbound_failure_read import (
    read_unbound_embedding_control_failure,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
    read_embedding_batch_plan_metadata,
)
from eom_orchestrator.local_embedding_control_artifacts import batch_execution_publication_exists
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_plan import EmbeddingBatchFailure
from eom_workflow.embedding_unbound_control_failure import (
    UNBOUND_CONTROL_FAILURE_CODE,
    UNBOUND_CONTROL_FAILURE_SCHEMA,
    UnboundEmbeddingControlFailure,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_batch_context import (
    document_embedding_batch_workflow_key,
)
from eom_workflow_runner.embedding_batch_plan_admission import resolve_embedding_batch_plan_controls
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.native_workflow_maintenance_authority import (
    ALLOCATED_MAINTENANCE_TABLES,
    require_native_workflow_maintenance_owner,
)

UNBOUND_CONTROL_FAILURE_ARTIFACT = "control_embedding_unbound_controller_failure"
UNBOUND_CONTROL_FAILURE_MEMBER = "controller-failure.json"


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_UNBOUND_PLAN_FAILURE_INVALID")


def record_unbound_embedding_plan_failure(
    session: Session,
    proof: UnboundEmbeddingControlFailure,
    evidence: ArtifactMemberPointer,
) -> EmbeddingBatchPlanHistory:
    """Existing caller-owned root transaction; late physical fences roll it back.

    No source admission, retry allocation, Workflow, unit effect or success is
    created. The caller publishes the small immutable evidence via Orchestrator
    before entering this short transaction and reuses that pointer on replay.
    """
    require_native_workflow_maintenance_owner(session, ALLOCATED_MAINTENANCE_TABLES)
    proof = UnboundEmbeddingControlFailure.model_validate(proof)
    evidence = ArtifactMemberPointer.model_validate(evidence)
    _require(
        evidence.schema_ref == UNBOUND_CONTROL_FAILURE_SCHEMA
        and evidence.member_path == UNBOUND_CONTROL_FAILURE_MEMBER
        and evidence.media_type == "application/json"
    )
    original = read_embedding_batch_plan_metadata(session, proof.parent_plan_job_id)
    _require(original is not None)
    assert original is not None
    request, history = original
    _require(
        request.request_sha256 == proof.parent_request_sha256
        and request.purpose == "INDEX"
        and request.scope.actor_kind == "LOCAL_INDEXING_SERVICE"
        and history.job_id == proof.parent_plan_job_id
        and history.route is None
        and history.bound is None
        and history.state in {"CLAIMED", "FAILED"}
        and len(request.child_selection_sha256s) == 1
    )
    allocation = history.allocation

    def no_execution() -> None:
        _require(
            session.scalar(
                select(WorkflowInstanceRecord.workflow_id).where(
                    WorkflowInstanceRecord.idempotency_key
                    == document_embedding_batch_workflow_key(request)
                )
            )
            is None
        )
        _require(
            not batch_execution_publication_exists(
                session,
                parent_request_sha256=request.request_sha256,
                allocation_record_sha256=allocation.record_sha256,
            )
        )

    with read_unbound_embedding_control_failure(proof) as physical:
        _require(physical.proof == proof and physical.allocation == allocation.control_request)
        no_execution()
        reader = PinnedArtifactReadContext.for_session(session, CatalogSettings())
        selection, policy = resolve_embedding_batch_plan_controls(reader, request)
        reader.prefetch(((evidence.artifact_id, evidence.artifact_revision_id),))
        observed = reader.read_pinned(
            **evidence.model_dump(mode="python"),
            expected_artifact_types=(UNBOUND_CONTROL_FAILURE_ARTIFACT,),
            expected_primary_file=UNBOUND_CONTROL_FAILURE_MEMBER,
            max_bytes=8192,
        )
        _require(observed.payload == canonical_json_bytes(proof))
        body = dict(
            schema_version="embedding-batch-plan/1.0",
            message_type="FAILED",
            request_sha256=request.request_sha256,
            error_code=UNBOUND_CONTROL_FAILURE_CODE,
            evidence=evidence.model_dump(mode="json"),
        )
        record = EmbeddingBatchFailure.model_validate(
            body | {"record_sha256": content_sha256(body)}
        )
        result = EmbeddingBatchPlanStore(request, selection, policy).record_unbound_failure(
            session, record
        )
        no_execution()
        reader.revalidate_provenance()
    return result
