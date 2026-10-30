"""Original service request to a canonical finite INDEX parent; no physical dispatch here."""

from __future__ import annotations

import time
from dataclasses import dataclass

from eom_catalog_contracts.embedding_index_families import embedding_entry_source
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    EmbeddingRegistryServiceCaller,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import content_sha256
from eom_workflow.document_embedding_reconciliation import (
    DocumentEmbeddingReconciliationAttempt,
    DocumentEmbeddingReconciliationRequest,
)
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation
from eom_workflow.embedding_batch_plan_family import SupportedEmbeddingBatchRequest
from eom_workflow.embedding_batch_plan_v11 import (
    BATCH_PLAN_V11_PROTOCOL,
    EmbeddingBatchPlanRequestV11,
    EmbeddingBatchSelectionV11,
)
from eom_workflow.embedding_batch_plan_v13 import (
    BATCH_PLAN_V13_PROTOCOL,
    EmbeddingBatchPlanRequestV13,
    EmbeddingBatchSelectionV13,
    PublicSolutionBatchAnchor,
)
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.local_indexing_routed_owner_configuration import (
    RoutedLocalIndexingOwnerConfiguration,
    require_routed_indexing_policy,
    validate_supported_routed_indexing_configuration,
)

from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.embedding_batch_plan_admission import (
    CatalogEmbeddingBatchPlanAdmission,
    EmbeddingBatchPlanOwnerConfiguration,
    resolve_embedding_device_routing_policy,
)
from eom_workflow_runner.local_indexing_routed_sources import PairedIndexingNamespacePreparation


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("DOCUMENT_BATCH_PARENT_SOURCE_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedDocumentEmbeddingParent:
    operation: CatalogEmbeddingBatchExecution
    request: SupportedEmbeddingBatchRequest
    allocation: EmbeddingBatchAllocation
    reconciliation: DocumentEmbeddingReconciliationRequest | None = None
    intent: DocumentEmbeddingReconciliationAttempt | None = None

    def __post_init__(self) -> None:
        _require((self.reconciliation is None) == (self.intent is None))
        if self.reconciliation is not None:
            assert self.intent is not None
            _require(
                self.intent.reconciliation_request_sha256 == self.reconciliation.request_sha256
                and self.intent.parent_request_sha256 == self.request.request_sha256
                and self.reconciliation.source_request_sha256 == self.request.parent_request_sha256
            )


def prepare_document_embedding_parent(
    pair: PairedIndexingNamespacePreparation,
    request: SupportedLocalEmbeddingRequest,
    configuration: RoutedLocalIndexingOwnerConfiguration,
) -> PreparedDocumentEmbeddingParent:
    """Stable parent identity, new allocation candidate; the atomic store alone owns dispatch.

    Same source request/policy/controller reuses the same published selection and
    parent. On replay the original allocation wins, never this candidate's nonce.
    """
    _require(type(pair) is PairedIndexingNamespacePreparation)
    request = parse_supported_local_embedding_request(request)
    configuration = validate_supported_routed_indexing_configuration(configuration)
    cpu, cuda = pair.cpu, pair.cuda
    publisher, owner = cuda.publisher, cuda.owner
    _require(
        cpu.publisher.engine is publisher.engine
        and cpu.owner.settings.nas_artifact_root == owner.settings.nas_artifact_root
        and cpu.runtime_profile == configuration.cpu_configuration.runtime_profile
        and cuda.runtime_profile == configuration.cuda_runtime_profile
        and request.namespace == owner.configuration.registry.namespace
        and request.resource_profile == cuda.runtime_profile.resource_profile
        and type(pair.maximum_sources) is int
        and 1
        <= pair.maximum_sources
        <= (
            MAX_PUBLIC_SOLUTION_SOURCES
            if isinstance(pair.namespace, PublicSolutionIndexNamespace)
            else 1024
        )
    )
    scope = EmbeddingRegistryLookup(
        request.corpus_id,
        cpu.owner.configuration.registry.namespace,
        request.graph_snapshot,
        request.access_policy_revision_id,
        request.access_policy_sha256,
        pair.maximum_sources,
    )
    with publisher.sessions.begin() as session:
        original = owner.resolve_sources(session, request)
        caller = owner.registry_caller(request)
        _require(type(caller) is EmbeddingRegistryServiceCaller)
        assert isinstance(caller, EmbeddingRegistryServiceCaller)
        cpu.owner.catalog.authorize_scope(session, caller, scope)
        reader = PinnedArtifactReadContext.for_session(session, owner.settings)
        policy = resolve_embedding_device_routing_policy(reader, configuration.routing_policy)
        require_routed_indexing_policy(configuration, policy)
        plan = original.admission.plan
        entries = {embedding_entry_source(e).item_revision_id: e for e in original.entries}
        _require(plan.recipe == cpu.owner.configuration.registry.recipe and bool(plan.sources))
        anchors = []
        for source in plan.sources:
            entry = entries.get(source.item_revision_id)
            _require(entry is not None)
            assert entry is not None
            if isinstance(entry, PublicSolutionEmbeddingEntry):
                anchors.append(PublicSolutionBatchAnchor.from_entry(entry).model_dump(mode="json"))
            elif isinstance(entry, StagedExperimentEntry):
                anchors.append(
                    dict(
                        basis="APPROVED_REFERENCE_ITEM",
                        source=source.model_dump(mode="json"),
                        profile=InferenceTransferProfilePointer.from_profile(
                            entry.profile
                        ).model_dump(mode="json"),
                        solution_evidence=entry.profile.source_basis.solution_evidence.model_dump(
                            mode="json"
                        ),
                    )
                )
            else:
                anchors.append(
                    dict(
                        basis="REGISTERED_ITEM_REVIEW",
                        source=source.model_dump(mode="json"),
                        profile=RegisteredReviewProfilePointer.from_profile(
                            entry.profile
                        ).model_dump(mode="json"),
                        review_evidence=entry.profile.source_basis.review_evidence.model_dump(
                            mode="json"
                        ),
                    )
                )
        body: dict[str, object] = dict(
            actor_kind="LOCAL_INDEXING_SERVICE",
            actor_id=caller.service.service_id,
            storage_partition=request.namespace.storage_partition,
            access_policy_sha256=request.access_policy_sha256,
        )
        batch_scope = EmbeddingWorkBatchScope.model_validate(
            body | {"scope_sha256": content_sha256(body)}
        )
        public = isinstance(pair.namespace, PublicSolutionIndexNamespace)
        protocol = BATCH_PLAN_V13_PROTOCOL if public else BATCH_PLAN_V11_PROTOCOL
        body = dict(
            schema_version=protocol,
            message_type="SELECTION",
            purpose="INDEX",
            scope=batch_scope.model_dump(mode="json"),
            corpus_id=request.corpus_id,
            graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
            access_policy_revision_id=request.access_policy_revision_id,
            anchors=anchors,
            recipe=plan.recipe.model_dump(mode="json"),
            views=[request.namespace.view],
            query=None,
        )
        selection_type = EmbeddingBatchSelectionV13 if public else EmbeddingBatchSelectionV11
        selection = selection_type.model_validate(body | {"selection_sha256": content_sha256(body)})
        key = "embedding-batch-selection:" + content_sha256(
            {
                "selection": selection.selection_sha256,
                "original_request": request.request_sha256,
            }
        ).removeprefix("sha256:")
        saved = cuda.controls.reuse_or_publish_batch_selection(selection, idempotency_key=key)
        reader.revalidate_provenance()
        cpu.owner.catalog.authorize_scope(session, caller, scope)
        owner.fence_current_actor(session, request)
    identity = content_sha256(
        {
            "original_request": request.request_sha256,
            "selection": selection.selection_sha256,
            "routing_policy": configuration.routing_policy_sha256,
            "controller_release": configuration.controller_release,
        }
    )
    body = dict(
        schema_version=protocol,
        message_type="REQUEST",
        batch_id="embeddingbatch_" + identity.removeprefix("sha256:")[:32],
        parent_request_sha256=request.request_sha256,
        purpose="INDEX",
        scope=batch_scope.model_dump(mode="json"),
        selection_manifest=saved.model_dump(mode="json"),
        selection_sha256=selection.selection_sha256,
        routing_policy=configuration.routing_policy.model_dump(mode="json"),
        routing_policy_sha256=configuration.routing_policy_sha256,
        child_selection_sha256s=list(selection.child_selection_sha256s),
    )
    request_type = EmbeddingBatchPlanRequestV13 if public else EmbeddingBatchPlanRequestV11
    parent = request_type.model_validate(body | {"request_sha256": content_sha256(body)})
    allocation = new_embedding_batch_allocation_candidate(
        parent, policy, now_monotonic_ns=time.monotonic_ns()
    )
    admission = CatalogEmbeddingBatchPlanAdmission(
        cpu.owner.catalog,
        caller,
        EmbeddingBatchPlanOwnerConfiguration(
            scope, configuration.routing_policy, configuration.routing_policy_sha256
        ),
    )
    operation = CatalogEmbeddingBatchExecution(
        admission,
        publisher,
        source_commit=cuda.controls.source_commit,
        controller_release=configuration.controller_release,
    )
    return PreparedDocumentEmbeddingParent(operation, parent, allocation)
