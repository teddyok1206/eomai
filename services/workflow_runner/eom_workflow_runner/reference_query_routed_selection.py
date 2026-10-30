"""Actual operator → original device-index selection through existing Catalog/control owners."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import overload

from eom_catalog_contracts.embedding_index_families import embedding_entry_source
from eom_catalog_contracts.inference_transfer_experiment import VIEWS, StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityPurpose
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareRequestV2,
    ReferenceQueryPrepareRequestV4,
    ReferenceQueryPrepareRequestV11,
)
from eom_catalog_contracts.reference_query_prepare import (
    SingleReferenceQueryPrepareRequest as SupportedReferenceQueryPrepareRequest,
)
from eom_catalog_contracts.reference_query_prepare import (
    parse_single_reference_query_prepare_request as parse_supported_reference_query_prepare_request,
)
from eom_catalog_contracts.similarity_context import ApprovedReferenceItemAnchor
from eom_catalog_service.embedding_registry_ports import (
    AuthoringReferencePurpose,
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    ReferenceQueryContextPreparation,
    SelectedEmbeddingSources,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_similarity_read import (
    CatalogPublicSolutionSimilarityRead,
    PublicSolutionSimilarityPreparation,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    BATCH_SELECTION_ARTIFACT_TYPE,
    REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation
from eom_workflow.embedding_batch_plan_family import (
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
)
from eom_workflow.embedding_batch_plan_v12 import (
    BATCH_PLAN_V12_PROTOCOL,
    BATCH_SELECTION_V12_SCHEMA_REF,
    EmbeddingBatchSelectionV12,
)
from eom_workflow.embedding_batch_plan_v14 import (
    BATCH_PLAN_V14_PROTOCOL,
    BATCH_SELECTION_V14_SCHEMA_REF,
    EmbeddingBatchSelectionV14,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.reference_query_execution import ReferenceQueryExecutionPolicy
from eom_workflow.reference_query_routed_owner_configuration import (
    SupportedRoutedReferenceQueryOwnerConfiguration,
    require_supported_routed_reference_query_policy,
    supported_routed_reference_query_configuration_bytes,
    validate_supported_routed_reference_query_configuration,
)
from eom_workflow.reference_query_routed_preparation import (
    MAX_ROUTED_QUERY_PREPARATION_BYTES,
    PublicRoutedReferenceQueryPreparation,
    RoutedReferenceQueryPreparation,
    SupportedRoutedReferenceQueryPreparation,
    parse_supported_reference_query_routed_preparation,
    routed_reference_query_preparation_key,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.embedding_batch_plan_admission import (
    CatalogEmbeddingBatchPlanAdmission,
    EmbeddingBatchPlanOwnerConfiguration,
)
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_preparation import ReferenceQueryPreparationUnavailable
from eom_workflow_runner.reference_query_prepare_application import reference_query_prepare_identity


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_ROUTED_SELECTION_INVALID")


@dataclass(frozen=True, slots=True)
class PublicQuerySourceSelection:
    """Shared immutable request plus ordinal; no repeated wire/text or authority copy."""

    request: ReferenceQueryPrepareRequestV4
    ordinal: int

    @property
    def source_item_revision_id(self) -> str:
        return self.request.source_item_revision_ids[self.ordinal]

    @property
    def graph_snapshot(self) -> KnowledgeGraphSnapshotPointer:
        return self.request.graph_snapshot

    @property
    def policy_revision_id(self) -> str:
        return self.request.policy_revision_id

    @property
    def policy_sha256(self) -> str:
        return self.request.policy_sha256


type RoutedQuerySourceSelection = SupportedReferenceQueryPrepareRequest | PublicQuerySourceSelection


@overload
def _purpose(request: SupportedReferenceQueryPrepareRequest) -> AuthoringReferencePurpose: ...


@overload
def _purpose(request: PublicQuerySourceSelection) -> PublicSolutionSimilarityPurpose: ...


@overload
def _purpose(
    request: RoutedQuerySourceSelection,
) -> AuthoringReferencePurpose | PublicSolutionSimilarityPurpose: ...


def _purpose(
    request: RoutedQuerySourceSelection,
) -> AuthoringReferencePurpose | PublicSolutionSimilarityPurpose:
    if isinstance(request, PublicQuerySourceSelection):
        return request.request.consumer_purpose
    return (
        request.consumer_purpose
        if isinstance(request, ReferenceQueryPrepareRequestV11 | ReferenceQueryPrepareRequestV2)
        else "PAST_EXAM_VARIATION"
    )


@dataclass(frozen=True, slots=True)
class PreparedRoutedReferenceQuerySelection:
    manifest: ArtifactMemberPointer
    preparation: SupportedRoutedReferenceQueryPreparation
    selection: EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14
    operation: CatalogEmbeddingBatchExecution
    routing_policy: EmbeddingDeviceRoutingPolicy

    def allocation_candidate(self) -> EmbeddingBatchAllocation:
        """Same existing source/policy/physical admission still precedes any real dispatch."""
        return new_embedding_batch_allocation_candidate(
            self.preparation.parent, self.routing_policy
        )


class CatalogRoutedReferenceQuerySelection:
    """One operation-local capture, small immutable pins and the existing indexed publication.

    This application never starts a model, takes a GPU, creates a Workflow or
    stores user text/capture. Every replay re-enters actual source admission.
    A future executor must use operation.open(), not treat this result as a grant.
    """

    def __init__(
        self,
        *,
        cpu: CatalogReferenceQueryOwnerAdmission,
        cuda: CatalogReferenceQueryOwnerAdmission,
        publisher: ControlFileSetPublisher,
        configuration: SupportedRoutedReferenceQueryOwnerConfiguration,
        policy: EmbeddingDeviceRoutingPolicy,
        cpu_policy: ReferenceQueryExecutionPolicy,
        cuda_policy: ReferenceQueryExecutionPolicy,
    ) -> None:
        _require(type(cpu) is type(cuda) is CatalogReferenceQueryOwnerAdmission)
        configuration = validate_supported_routed_reference_query_configuration(configuration)
        require_supported_routed_reference_query_policy(
            configuration, policy, cpu_policy, cuda_policy
        )
        _require(
            publisher.engine is cpu.catalog.engine is cuda.catalog.engine
            and cpu.settings == cuda.settings
            and publisher.settings.nas_artifact_root == cpu.settings.nas_artifact_root
            and cpu.identity.capture is cuda.identity.capture
            and cpu.configuration.registry.space == cpu_policy.spaces.document
            and cuda.configuration.registry.space == cuda_policy.spaces.document
            and cpu.configuration.registry.corpus_id
            == cuda.configuration.registry.corpus_id
            == configuration.cpu_configuration.corpus_id
            and cpu.configuration.registry.recipe
            == cuda.configuration.registry.recipe
            == configuration.cpu_configuration.recipe
            and cpu.configuration.registry.source_classes
            == cuda.configuration.registry.source_classes
            == configuration.cpu_configuration.source_classes
            and type(cpu.configuration.registry.namespace)
            is type(cuda.configuration.registry.namespace)
            and cpu.configuration.registry.namespace == configuration.cpu_configuration.namespace
            and cuda.configuration.registry.namespace
            == type(cpu.configuration.registry.namespace).model_validate(
                cpu.configuration.registry.namespace.model_dump(mode="json")
                | {"space_sha256": cuda_policy.spaces.document.space_sha256}
            )
        )
        for owner, execution, pointer, digest in (
            (
                cpu,
                cpu_policy,
                configuration.cpu_configuration.native_execution_policy,
                configuration.cpu_configuration.native_execution_policy_sha256,
            ),
            (
                cuda,
                cuda_policy,
                configuration.cuda_native_execution_policy,
                configuration.cuda_native_execution_policy_sha256,
            ),
        ):
            _require(
                owner.configuration.native_execution_policy == pointer
                and owner.configuration.native_execution_policy_sha256 == digest
                and owner.configuration.runtime_bundle == execution.runtime_bundle
            )
        self.cpu, self.cuda, self.publisher = cpu, cuda, publisher
        self.configuration, self.policy = configuration, policy
        self.spaces = (cpu_policy.spaces, cuda_policy.spaces)
        self.controls = LocalEmbeddingControlArtifactPublisher(
            publisher, source_commit=configuration.cpu_configuration.owner_source_commit
        )

    def _scope(
        self,
        owner: CatalogReferenceQueryOwnerAdmission,
        request: RoutedQuerySourceSelection,
    ) -> EmbeddingRegistryLookup:
        registry = owner.configuration.registry
        return EmbeddingRegistryLookup(
            registry.corpus_id,
            registry.namespace,
            request.graph_snapshot,
            request.policy_revision_id,
            request.policy_sha256,
            16384 if isinstance(request, PublicQuerySourceSelection) else 1024,
        )

    def _authorize(
        self, session: Session, request: RoutedQuerySourceSelection
    ) -> EmbeddingRegistryCaller:
        caller = EmbeddingRegistryCaller(self.cpu.identity.capture.operator_id)
        for owner in (self.cpu, self.cuda):
            owner.identity.fence_current_operator(session, caller.operator_id)
            owner.catalog.authorize_scope(session, caller, self._scope(owner, request))
        return caller

    def _new_selection(
        self, requests: tuple[SupportedReferenceQueryPrepareRequest, ...], key: str
    ) -> EmbeddingBatchSelectionV12:
        first = requests[0]
        ids = tuple(request.source_item_revision_id for request in requests)
        with self.publisher.sessions.begin() as session:
            caller = self._authorize(session, first)
            contexts, captured = [], []
            for owner, spaces in zip((self.cpu, self.cuda), self.spaces, strict=True):
                scope = self._scope(owner, first)
                captured.append(
                    owner.catalog.resolve_selected_sources(
                        session, caller, SelectedEmbeddingSources(scope, tuple(sorted(ids)))
                    )
                )
                _key, logical_id = reference_query_prepare_identity(caller.operator_id, key)
                context = owner.catalog.prepare_reference_query_context_in_session(
                    session,
                    caller,
                    ReferenceQueryContextPreparation(
                        logical_id,
                        SelectedEmbeddingSources(scope, (ids[0],)),
                        spaces,
                        VIEWS,
                        "REQUIRED",
                        8,
                        consumer_purpose=_purpose(first),
                    ),
                )
                if any(row.index is None for row in context.views):
                    raise ReferenceQueryPreparationUnavailable("INDEX_NOT_PREPARED")
                contexts.append(context)
            left, right = captured
            _require(
                not left.truncated
                and not right.truncated
                and left.sources == right.sources
                and left.entries == right.entries
            )
            sources = {source.item_revision_id: source for source in left.sources}
            entries = {
                embedding_entry_source(entry).item_revision_id: entry for entry in left.entries
            }
            _require(set(sources) == set(ids) and len(sources) == len(left.sources))
            anchors = []
            for source_id in ids:
                entry = entries.get(source_id)
                if entry is None:
                    raise ReferenceQueryPreparationUnavailable("ANCHOR_REPORT_MISSING")
                _require(isinstance(entry, StagedExperimentEntry))
                assert isinstance(entry, StagedExperimentEntry)
                anchors.append(
                    ApprovedReferenceItemAnchor(
                        source=sources[source_id],
                        profile=InferenceTransferProfilePointer.from_profile(entry.profile),
                        solution_evidence=entry.profile.source_basis.solution_evidence,
                    ).model_dump(mode="json")
                )
            one, two = contexts
            _require(
                one.anchor == two.anchor
                and tuple(row.view for row in one.views)
                == tuple(row.view for row in two.views)
                == VIEWS
            )
            scope_body = dict(
                actor_kind="OPERATOR",
                actor_id=caller.operator_id,
                storage_partition=self.cpu.configuration.registry.namespace.storage_partition,
                access_policy_sha256=first.policy_sha256,
            )
            scope_body["scope_sha256"] = content_sha256(scope_body)
            body = dict(
                schema_version=BATCH_PLAN_V12_PROTOCOL,
                message_type="SELECTION",
                purpose="REFERENCE_QUERY",
                scope=scope_body,
                corpus_id=left.corpus_id,
                graph_snapshot=first.graph_snapshot.model_dump(mode="json"),
                access_policy_revision_id=first.policy_revision_id,
                anchors=anchors,
                recipe=left.recipe.model_dump(mode="json"),
                views=list(VIEWS),
                source_classes=list(self.cpu.configuration.registry.source_classes),
                index_pairs=[
                    dict(cpu=a.model_dump(mode="json"), cuda=b.model_dump(mode="json"))
                    for a, b in zip(one.views, two.views, strict=True)
                ],
                query=dict(
                    consumer_purpose=_purpose(first),
                    topics=[],
                    unit_ids=[],
                    maximum_sources=1024,
                    top_k=8,
                ),
            )
            selection = EmbeddingBatchSelectionV12.model_validate(
                body | {"selection_sha256": content_sha256(body)}
            )
            self._authorize(session, first)
            return selection

    def _new_public_selection(
        self, request: ReferenceQueryPrepareRequestV4, key: str
    ) -> EmbeddingBatchSelectionV14:
        """One bulk canonical index/source read per device; no per-item full-index scan."""
        first = PublicQuerySourceSelection(request, 0)
        with self.publisher.sessions.begin() as session:
            caller = self._authorize(session, first)
            contexts = []
            for owner, spaces in zip((self.cpu, self.cuda), self.spaces, strict=True):
                scope = self._scope(owner, first)
                preparations = []
                for ordinal, source_id in enumerate(request.source_item_revision_ids):
                    _key, logical_id = reference_query_prepare_identity(
                        caller.operator_id, key + ":public:" + str(ordinal)
                    )
                    preparations.append(
                        PublicSolutionSimilarityPreparation(
                            logical_id,
                            SelectedEmbeddingSources(scope, (source_id,)),
                            spaces,
                            request.consumer_purpose,
                            request.top_k,
                        )
                    )
                contexts.append(
                    CatalogPublicSolutionSimilarityRead(owner.catalog).prepare_many_in_session(
                        session, caller, tuple(preparations)
                    )
                )
            cpu, cuda = contexts
            _require(
                tuple(row.anchor for row in cpu) == tuple(row.anchor for row in cuda)
                and all(row.views == cpu[0].views for row in cpu)
                and all(row.views == cuda[0].views for row in cuda)
            )
            scope_body = dict(
                actor_kind="OPERATOR",
                actor_id=caller.operator_id,
                storage_partition=self.cpu.configuration.registry.namespace.storage_partition,
                access_policy_sha256=request.policy_sha256,
            )
            scope_body["scope_sha256"] = content_sha256(scope_body)
            body = dict(
                schema_version=BATCH_PLAN_V14_PROTOCOL,
                message_type="SELECTION",
                purpose="REFERENCE_QUERY",
                scope=scope_body,
                corpus_id=self.cpu.configuration.registry.corpus_id,
                graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
                access_policy_revision_id=request.policy_revision_id,
                anchors=[row.anchor.model_dump(mode="json") for row in cpu],
                recipe=cpu[0].views[0].recipe.model_dump(mode="json"),
                views=["CONCRETE_FACETS"],
                source_classes=list(self.cpu.configuration.registry.source_classes),
                query=dict(
                    consumer_purpose=request.consumer_purpose,
                    maximum_sources=16384,
                    top_k=request.top_k,
                ),
                index_pairs=[
                    dict(
                        cpu=cpu[0].views[0].model_dump(mode="json"),
                        cuda=cuda[0].views[0].model_dump(mode="json"),
                    )
                ],
            )
            selected = EmbeddingBatchSelectionV14.model_validate(
                body | {"selection_sha256": content_sha256(body)}
            )
            self._authorize(session, first)
            return selected

    def _read_original_selection(
        self, pointer: ArtifactMemberPointer, request: RoutedQuerySourceSelection
    ) -> EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14:
        with self.publisher.sessions.begin() as session:
            self._authorize(session, request)
            reader = PinnedArtifactReadContext.for_session(session, self.cpu.settings)
            reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                (pointer.member_path,),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
            )
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(BATCH_SELECTION_ARTIFACT_TYPE,),
                expected_primary_file="selection.json",
                max_bytes=512 * 1024,
            ).payload
            selected = parse_embedding_batch_selection(json.loads(raw))
            _require(isinstance(selected, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14))
            assert isinstance(selected, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14)
            _require(
                isinstance(selected, EmbeddingBatchSelectionV14)
                == isinstance(request, PublicQuerySourceSelection)
            )
            _require(canonical_json_bytes(selected) == raw)
            reader.revalidate_provenance()
            self._authorize(session, request)
            return selected

    @staticmethod
    def _require_requested_selection(
        selection: EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14,
        requests: tuple[RoutedQuerySourceSelection, ...],
    ) -> None:
        if isinstance(selection, EmbeddingBatchSelectionV14):
            first = requests[0]
            _require(isinstance(first, PublicQuerySourceSelection))
            assert isinstance(first, PublicQuerySourceSelection)
            _require(
                selection.query.consumer_purpose == first.request.consumer_purpose
                and selection.query.maximum_sources == 16384
                and selection.query.top_k == first.request.top_k
                and selection.views == ("CONCRETE_FACETS",)
                and tuple(anchor.source.item_revision_id for anchor in selection.anchors)
                == first.request.source_item_revision_ids
            )
            return
        _require(not isinstance(requests[0], PublicQuerySourceSelection))
        query = selection.query
        _require(
            query is not None
            and query.consumer_purpose == _purpose(requests[0])
            and query.topics == query.unit_ids == ()
            and query.maximum_sources == 1024
            and query.top_k == 8
            and selection.views == VIEWS
            and tuple(anchor.source.item_revision_id for anchor in selection.anchors)
            == tuple(request.source_item_revision_id for request in requests)
        )

    def prepare_public(
        self, request: ReferenceQueryPrepareRequestV4
    ) -> PreparedRoutedReferenceQuerySelection:
        request = ReferenceQueryPrepareRequestV4.model_validate(request)
        return self.prepare(
            tuple(
                PublicQuerySourceSelection(request, index)
                for index in range(len(request.source_item_revision_ids))
            ),
            idempotency_key=request.idempotency_key,
        )

    def prepare(
        self, requests: tuple[RoutedQuerySourceSelection, ...], *, idempotency_key: str
    ) -> PreparedRoutedReferenceQuerySelection:
        _require(type(requests) is tuple and 1 <= len(requests) <= 32)
        if isinstance(requests[0], PublicQuerySourceSelection):
            original = requests[0].request
            _require(
                all(
                    isinstance(value, PublicQuerySourceSelection)
                    and value.request is original
                    and type(value.ordinal) is int
                    and value.ordinal == ordinal
                    for ordinal, value in enumerate(requests)
                )
            )
            checked = ReferenceQueryPrepareRequestV4.model_validate(original)
            _require(
                len(requests) == len(checked.source_item_revision_ids)
                and idempotency_key == checked.idempotency_key
            )
            requests = tuple(
                PublicQuerySourceSelection(checked, index) for index in range(len(requests))
            )
        else:
            requests = tuple(
                parse_supported_reference_query_prepare_request(request) for request in requests
            )
        first = requests[0]
        _require(
            isinstance(first, PublicQuerySourceSelection)
            == isinstance(self.cpu.configuration.registry.namespace, PublicSolutionIndexNamespace)
        )
        _require(
            isinstance(first, ReferenceQueryPrepareRequestV2)
            == isinstance(self.cpu.configuration.registry.namespace, MixedEmbeddingIndexNamespace)
        )
        _require(len({request.source_item_revision_id for request in requests}) == len(requests))
        _require(
            all(
                request.graph_snapshot == first.graph_snapshot
                and request.policy_revision_id == first.policy_revision_id
                and request.policy_sha256 == first.policy_sha256
                and _purpose(request) == _purpose(first)
                and isinstance(request, ReferenceQueryPrepareRequestV2)
                == isinstance(first, ReferenceQueryPrepareRequestV2)
                for request in requests
            )
        )
        operator_id = self.cpu.identity.capture.operator_id
        routed_reference_query_preparation_key(operator_id, idempotency_key)
        intent = content_sha256(
            dict(
                operator_id=operator_id,
                idempotency_key=idempotency_key,
                requests=first.request.model_dump(
                    mode="json", exclude={"operation_id", "request_sha256"}
                )
                if isinstance(first, PublicQuerySourceSelection)
                else [
                    request.model_dump(mode="json", exclude={"operation_id", "request_sha256"})
                    for request in requests
                    if not isinstance(request, PublicQuerySourceSelection)
                ],
            )
        )
        admission = CatalogEmbeddingBatchPlanAdmission(
            self.cpu.catalog,
            EmbeddingRegistryCaller(operator_id),
            EmbeddingBatchPlanOwnerConfiguration(
                self._scope(self.cpu, first),
                self.configuration.routing_policy,
                self.configuration.routing_policy_sha256,
            ),
        )
        operation = CatalogEmbeddingBatchExecution(
            admission,
            self.publisher,
            source_commit=self.configuration.cpu_configuration.owner_source_commit,
            controller_release=self.configuration.controller_release,
        )
        with self.publisher.sessions.begin() as session:
            self._authorize(session, first)
        finder = (
            self.controls.find_public_routed_reference_query_preparation
            if isinstance(first, PublicQuerySourceSelection)
            else self.controls.find_routed_reference_query_preparation
        )
        pointer = finder(operator_id=operator_id, idempotency_key=idempotency_key)
        selection: EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14
        prepared: SupportedRoutedReferenceQueryPreparation
        if pointer is None:
            selection_key = "routed-query-selection:" + intent[7:]
            original_selection = self.controls.publisher.find_published(
                idempotency_key=selection_key, artifact_type=BATCH_SELECTION_ARTIFACT_TYPE
            )
            if original_selection is None:
                if isinstance(first, PublicQuerySourceSelection):
                    selection = self._new_public_selection(first.request, idempotency_key)
                else:
                    legacy_requests = tuple(
                        value
                        for value in requests
                        if not isinstance(value, PublicQuerySourceSelection)
                    )
                    _require(len(legacy_requests) == len(requests))
                    selection = self._new_selection(legacy_requests, idempotency_key)
                selected = self.controls.reuse_or_publish_batch_selection(
                    selection, idempotency_key=selection_key
                )
            else:
                _require(original_selection.primary_file == "selection.json")
                selected = ArtifactMemberPointer(
                    artifact_id=original_selection.artifact_id,
                    artifact_revision_id=original_selection.artifact_revision_id,
                    member_path="selection.json",
                    sha256=original_selection.primary_sha256,
                    schema_ref=BATCH_SELECTION_V14_SCHEMA_REF
                    if isinstance(first, PublicQuerySourceSelection)
                    else BATCH_SELECTION_V12_SCHEMA_REF,
                    media_type="application/json",
                )
                selection = self._read_original_selection(selected, first)
            body = dict(
                schema_version=BATCH_PLAN_V14_PROTOCOL
                if isinstance(first, PublicQuerySourceSelection)
                else BATCH_PLAN_V12_PROTOCOL,
                message_type="REQUEST",
                batch_id="embeddingbatch_"
                + content_sha256(dict(operator_id=operator_id, key=idempotency_key))[7:39],
                parent_request_sha256=intent,
                purpose="REFERENCE_QUERY",
                scope=selection.scope.model_dump(mode="json"),
                selection_manifest=selected.model_dump(mode="json"),
                selection_sha256=selection.selection_sha256,
                routing_policy=self.configuration.routing_policy.model_dump(mode="json"),
                routing_policy_sha256=self.configuration.routing_policy_sha256,
                child_selection_sha256s=list(selection.child_selection_sha256s),
            )
            parent = parse_embedding_batch_plan_request(
                body | {"request_sha256": content_sha256(body)}
            )
            with (
                self.publisher.sessions.begin() as session,
                admission.admit(session, parent) as current,
            ):
                _require(
                    isinstance(
                        current.selection, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14
                    )
                )
                assert isinstance(
                    current.selection, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14
                )
                self._require_requested_selection(current.selection, requests)
            body = dict(
                schema_version="reference-query-routed-preparation/2.0"
                if isinstance(first, PublicQuerySourceSelection)
                else "reference-query-routed-preparation/1.0",
                operator_id=operator_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                owner_configuration_sha256=sha256_bytes(
                    supported_routed_reference_query_configuration_bytes(self.configuration)
                ),
                parent=parent.model_dump(mode="json"),
            )
            if isinstance(first, PublicQuerySourceSelection):
                prepared = PublicRoutedReferenceQueryPreparation.model_validate(
                    body | {"preparation_sha256": content_sha256(body)}
                )
                pointer = self.controls.publish_public_routed_reference_query_preparation(
                    prepared
                ).member
            else:
                prepared = RoutedReferenceQueryPreparation.model_validate(
                    body | {"preparation_sha256": content_sha256(body)}
                )
                pointer = self.controls.publish_routed_reference_query_preparation(prepared).member
        with self.publisher.sessions.begin() as session:
            self._authorize(session, first)
            reader = PinnedArtifactReadContext.for_session(session, self.cpu.settings)
            reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                (pointer.member_path,),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
            )
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE,),
                expected_primary_file="preparation.json",
                max_bytes=MAX_ROUTED_QUERY_PREPARATION_BYTES,
            ).payload
            prepared = parse_supported_reference_query_routed_preparation(raw)
            _require(
                prepared.operator_id == operator_id
                and prepared.idempotency_key == idempotency_key
                and prepared.intent_sha256 == intent
            )
            with admission.admit(session, prepared.parent) as current:
                _require(
                    isinstance(
                        current.selection, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14
                    )
                )
                assert isinstance(
                    current.selection, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14
                )
                selection = current.selection
                self._require_requested_selection(selection, requests)
            reader.revalidate_provenance()
            self._authorize(session, first)
        return PreparedRoutedReferenceQuerySelection(
            pointer, prepared, selection, operation, self.policy
        )
