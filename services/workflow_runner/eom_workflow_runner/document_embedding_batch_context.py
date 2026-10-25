"""Shared original-parent/source closure for the two concrete routed INDEX adapters."""

from __future__ import annotations

from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_SECONDS,
    MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
    EmbeddingWorkBatchInput,
)
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import BATCH_PLAN_PROTOCOL, EmbeddingBatchBound
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingDecision
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_execution import OwnedDocumentEmbedding
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.models import WorkflowInstanceRecord


def require_document_batch_context(condition: bool) -> None:
    if not condition:
        raise ValueError("DOCUMENT_BATCH_CONTEXT_INVALID")


def document_embedding_batch_workflow_key(parent: SupportedEmbeddingBatchRequest) -> str:
    """Stable identity only. Existing actual owner remains responsible for current authority."""
    parent = parse_embedding_batch_plan_request(parent)
    require_document_batch_context(
        parent.purpose == "INDEX" and len(parent.child_selection_sha256s) == 1
    )
    return "embedding-batch-index:" + content_sha256(
        {
            "parent_request_sha256": parent.request_sha256,
            "child_selection_sha256": parent.child_selection_sha256s[0],
        }
    ).removeprefix("sha256:")


class OriginalDocumentEmbeddingBatchContext:
    """Operation-local immutable metadata, not physical allocation or cached permission."""

    def __init__(
        self,
        operation: CatalogEmbeddingBatchExecution,
        parent: SupportedEmbeddingBatchRequest,
        decision: EmbeddingDeviceRoutingDecision,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        request: SupportedLocalEmbeddingRequest,
    ) -> None:
        require_document_batch_context(
            type(owner) is CatalogLocalEmbeddingOwnerAdmission
            and operation.publisher.engine is owner.catalog.engine
            and operation.publisher.settings.nas_artifact_root == owner.settings.nas_artifact_root
        )
        self.operation, self.parent, self.owner = (
            operation,
            parse_embedding_batch_plan_request(parent),
            owner,
        )
        self.decision = EmbeddingDeviceRoutingDecision.model_validate(decision)
        self.request = parse_supported_local_embedding_request(request)
        with (
            operation.publisher.sessions.begin() as session,
            operation.admission.admit(session, self.parent) as sources,
        ):
            self.selection = sources.selection
        self.workflow_key = document_embedding_batch_workflow_key(self.parent)
        self.validate_request(self.request)

    def validate_request(self, request: SupportedLocalEmbeddingRequest) -> None:
        request = parse_supported_local_embedding_request(request)
        actor_kind, actor_id = supported_local_embedding_request_actor(request)
        registry, selection = self.owner.configuration.registry, self.selection
        profile, config = self.decision.selected.profile, self.owner.configuration
        require_document_batch_context(
            request == self.request
            and selection.views == (request.namespace.view,)
            and registry.namespace == request.namespace
            and registry.corpus_id == selection.corpus_id == request.corpus_id
            and registry.space == profile.space == request.space
            and registry.recipe == selection.recipe
            and request.graph_snapshot == selection.graph_snapshot
            and request.access_policy_revision_id == selection.access_policy_revision_id
            and request.access_policy_sha256 == selection.scope.access_policy_sha256
            and request.namespace.storage_partition == selection.scope.storage_partition
            and selection.scope.actor_kind
            == {"human": "OPERATOR", "local_indexing_service": "LOCAL_INDEXING_SERVICE"}[actor_kind]
            and selection.scope.actor_id == actor_id
            and request.runtime_bundle == profile.runtime_bundle
            and request.resource_profile == profile.resource_profile
            and request.native_execution_policy == config.native_execution_policy
            and request.native_execution_policy_sha256 == config.native_execution_policy_sha256
        )

    def validate_workflow(self, workflow: WorkflowInstanceRecord) -> None:
        actor_kind, actor_id = supported_local_embedding_request_actor(self.request)
        require_document_batch_context(
            workflow.idempotency_key == self.workflow_key
            and workflow.initial_request == self.request.model_dump(mode="json")
            and workflow.created_actor_type == actor_kind
            and workflow.created_actor_id == actor_id
        )

    def validate_intent(self, session: Session, intent: SupportedEmbeddingIntent) -> None:
        require_document_batch_context(
            intent.workflow_request_sha256 == self.request.request_sha256
            and intent.source_plan == self.request.source_plan
            and intent.source_plan_sha256 == self.request.source_plan_sha256
            and intent.resource_profile_sha256
            == self.request.resource_profile.resource_profile_sha256
        )
        workflow = session.get(WorkflowInstanceRecord, intent.workflow_id, populate_existing=True)
        require_document_batch_context(workflow is not None)
        assert workflow is not None
        self.validate_workflow(workflow)

    def authorize_work(
        self,
        work: OwnedDocumentEmbedding,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> None:
        require_document_batch_context(
            type(work) is OwnedDocumentEmbedding
            and type(source) is CatalogEncodingOwnerAdmission
            and source.owner is self.owner
            and source.execution.request == self.request
            and source.execution.intent == work.association.intent
        )
        self.validate_request(source.execution.request)
        with transaction() as session:
            current = source.resolve_launch(session, work.association)
            plan = current.scope.plan
            self.validate_intent(session, work.association.intent)
            require_document_batch_context(
                current.owned_input == work.request
                and plan.recipe == self.selection.recipe
                and {s.item_revision_id: s for s in plan.sources}
                == {a.source.item_revision_id: a.source for a in self.selection.anchors}
            )

    def binding(
        self, work: OwnedDocumentEmbedding, route_record_sha256: str
    ) -> tuple[EmbeddingBatchBound, EmbeddingWorkBatchInput]:
        """Validation materialization only. This does not commit or grant a numerical launch."""
        scope, resources = self.parent.scope, self.request.resource_profile
        body = dict(
            schema_version="embedding-work-batch-input/1.0",
            purpose="DOCUMENT",
            scope=scope.model_dump(mode="json"),
            routing_decision_sha256=self.decision.decision_sha256,
            resource_profile_sha256=resources.resource_profile_sha256,
            timeout_seconds=min(resources.timeout_seconds, MAX_EMBEDDING_WORK_BATCH_SECONDS),
            vector_max_bytes=MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
            children=[
                dict(scope_sha256=scope.scope_sha256, request=work.request.model_dump(mode="json"))
            ],
        )
        batch = EmbeddingWorkBatchInput.model_validate(
            body | {"request_sha256": content_sha256(body)}
        )
        intent = work.association.intent
        body = dict(
            schema_version=BATCH_PLAN_PROTOCOL,
            message_type="BOUND",
            request_sha256=self.parent.request_sha256,
            route_record_sha256=route_record_sha256,
            batch_request_sha256=batch.request_sha256,
            resource_profile_sha256=resources.resource_profile_sha256,
            children=[
                dict(
                    selection_sha256=self.parent.child_selection_sha256s[0],
                    workflow_id=intent.workflow_id,
                    step_run_id=intent.step_run_id,
                    native_job_id=intent.native_launch_job_id,
                    workflow_request_sha256=self.request.request_sha256,
                    launch_association_sha256=work.association.association_sha256,
                    native_input_sha256=work.request.request_sha256,
                )
            ],
        )
        binding = EmbeddingBatchBound.model_validate(body | {"record_sha256": content_sha256(body)})
        return binding, batch
