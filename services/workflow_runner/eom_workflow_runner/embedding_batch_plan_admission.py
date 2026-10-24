"""Canonical controls and current Catalog sources before allocation; never compute authority."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context import ApprovedReferenceItemAnchor
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryActor,
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
    SelectedEmbeddingSources,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import (
    BATCH_SELECTION_ARTIFACT_TYPE,
    DEVICE_ROUTING_POLICY_ARTIFACT_TYPE,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_plan import (
    MAX_BATCH_PLAN_BYTES,
    EmbeddingBatchPlanRequest,
    EmbeddingBatchSelection,
    RegisteredReviewBatchAnchor,
    validate_embedding_batch_plan_controls,
)
from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    MAX_EMBEDDING_DEVICE_ROUTING_BYTES,
    EmbeddingDeviceRoutingPolicy,
)
from pydantic import TypeAdapter
from sqlalchemy.orm import Session


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_PLAN_ADMISSION_INVALID")


@dataclass(frozen=True, slots=True)
class EmbeddingBatchPlanOwnerConfiguration:
    """Trusted pinned source scope and installed routing selection, not request authority."""

    source_scope: EmbeddingRegistryLookup
    routing_policy: ArtifactMemberPointer
    routing_policy_sha256: str

    def __post_init__(self) -> None:
        _require(type(self.source_scope) is EmbeddingRegistryLookup)
        pointer = ArtifactMemberPointer.model_validate(self.routing_policy)
        _require(
            pointer.member_path == "policy.json"
            and pointer.schema_ref == EMBEDDING_DEVICE_ROUTING_SCHEMA_REF
            and pointer.media_type == "application/json"
        )
        TypeAdapter(Sha256).validate_python(self.routing_policy_sha256)
        object.__setattr__(self, "routing_policy", pointer)


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingBatchPlanSources:
    """Only this root's materialization; no cached permission, claim or GPU grant."""

    selection: EmbeddingBatchSelection
    policy: EmbeddingDeviceRoutingPolicy
    sources: ResolvedEmbeddingLookup


class CatalogEmbeddingBatchPlanAdmission:
    """Reuse the actual human/service Catalog authority, never reconstruct it from a DTO.

    Enter this window before locking a parent planning Job. Every replay reopens
    it. Trusted composition supplies the original source scope and actual caller;
    the concrete Catalog still checks current runtime, actor and source authority.
    """

    def __init__(
        self,
        catalog: CatalogEmbeddingRegistryVerifier,
        caller: EmbeddingRegistryActor,
        configuration: EmbeddingBatchPlanOwnerConfiguration,
    ) -> None:
        _require(type(catalog) is CatalogEmbeddingRegistryVerifier)
        configuration.__post_init__()
        validate_embedding_registry_actor(caller)
        scope, registry = configuration.source_scope, catalog.configuration
        _require(scope.corpus_id == registry.corpus_id and scope.namespace == registry.namespace)
        self.catalog = catalog
        self.caller = caller
        self.configuration = configuration

    @staticmethod
    def _read_control(
        reader: PinnedArtifactReadContext,
        pointer: ArtifactMemberPointer,
        artifact_type: str,
        maximum: int,
    ) -> object:
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            (pointer.member_path,),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(artifact_type,),
            expected_primary_file=pointer.member_path,
            max_bytes=maximum,
        ).payload
        value: object = json.loads(raw)
        _require(canonical_json_bytes(value) == raw)
        return value

    def _validate_selection(
        self, request: EmbeddingBatchPlanRequest, selection: EmbeddingBatchSelection
    ) -> SelectedEmbeddingSources:
        scope = self.configuration.source_scope
        actor_kind, actor_id = (
            ("OPERATOR", self.caller.operator_id)
            if isinstance(self.caller, EmbeddingRegistryCaller)
            else ("LOCAL_INDEXING_SERVICE", self.caller.service.service_id)
        )
        _require(
            request.scope.actor_kind == actor_kind
            and request.scope.actor_id == actor_id
            and selection.corpus_id == scope.corpus_id
            and selection.graph_snapshot == scope.graph_snapshot
            and selection.access_policy_revision_id == scope.policy_revision_id
            and selection.scope.access_policy_sha256 == scope.policy_sha256
            and selection.scope.storage_partition == scope.namespace.storage_partition
            and selection.recipe == self.catalog.configuration.recipe
            and (
                selection.query is None or selection.query.maximum_sources <= scope.maximum_sources
            )
        )
        return SelectedEmbeddingSources(
            scope, tuple(sorted(anchor.source.item_revision_id for anchor in selection.anchors))
        )

    @staticmethod
    def _validate_sources(
        selection: EmbeddingBatchSelection, current: ResolvedEmbeddingLookup
    ) -> None:
        sources = {source.item_revision_id: source for source in current.sources}
        entries = {
            entry.profile.source_basis.source.item_revision_id: entry for entry in current.entries
        }
        _require(
            not current.truncated
            and current.corpus_id == selection.corpus_id
            and current.recipe == selection.recipe
            and len(sources) == len(current.sources) == len(selection.anchors)
            and len(entries) == len(current.entries)
            and set(entries).issubset(sources)
        )
        for anchor in selection.anchors:
            revision = anchor.source.item_revision_id
            _require(sources.get(revision) == anchor.source)
            entry = entries.get(revision)
            if isinstance(anchor, ApprovedReferenceItemAnchor):
                if entry is None:
                    _require(anchor.profile is None and anchor.solution_evidence is None)
                    continue
                _require(isinstance(entry, StagedExperimentEntry))
                assert isinstance(entry, StagedExperimentEntry)
                _require(
                    anchor.profile == InferenceTransferProfilePointer.from_profile(entry.profile)
                    and anchor.solution_evidence == entry.profile.source_basis.solution_evidence
                )
            else:
                _require(isinstance(anchor, RegisteredReviewBatchAnchor))
                _require(entry is not None and not isinstance(entry, StagedExperimentEntry))
                assert entry is not None and not isinstance(entry, StagedExperimentEntry)
                _require(
                    anchor.profile == RegisteredReviewProfilePointer.from_profile(entry.profile)
                    and anchor.review_evidence == entry.profile.source_basis.review_evidence
                )
            _require(entry.profile.source_basis.graph_snapshot == selection.graph_snapshot)

    @contextmanager
    def admit(
        self, session: Session, request: EmbeddingBatchPlanRequest
    ) -> Iterator[ResolvedEmbeddingBatchPlanSources]:
        request = EmbeddingBatchPlanRequest.model_validate(request)
        root = session.get_transaction()
        _require(
            root is not None
            and root.is_active
            and not session.in_nested_transaction()
            and session.get_bind() is self.catalog.engine
            and request.routing_policy == self.configuration.routing_policy
            and request.routing_policy_sha256 == self.configuration.routing_policy_sha256
        )
        assert root is not None
        scope = self.configuration.source_scope
        self.catalog.authorize_scope(session, self.caller, scope)
        reader = PinnedArtifactReadContext.for_session(session, self.catalog.settings)
        selection, policy = resolve_embedding_batch_plan_controls(reader, request)
        _require(policy.cpu.profile.space == self.catalog.configuration.space)
        selected = self._validate_selection(request, selection)
        current = self.catalog.resolve_selected_sources(session, self.caller, selected)
        self._validate_sources(selection, current)
        yield ResolvedEmbeddingBatchPlanSources(selection, policy, current)
        _require(session.get_transaction() is root and root.is_active)
        # Do not repeat immutable file reads/hashes. Recheck current metadata and
        # the official actual source authority before the caller commits this root.
        reader.revalidate_provenance()
        _require(self.catalog.resolve_selected_sources(session, self.caller, selected) == current)
        self.catalog.authorize_scope(session, self.caller, scope)
        _require(session.get_transaction() is root and root.is_active)


def resolve_embedding_batch_plan_controls(
    reader: PinnedArtifactReadContext, request: EmbeddingBatchPlanRequest
) -> tuple[EmbeddingBatchSelection, EmbeddingDeviceRoutingPolicy]:
    """Canonical original controls only, not current actor/source or compute authority.

    Admission and historical child completion use one file/schema/hash rule.
    Each caller retains its actual current authority and late provenance fence.
    """
    request = EmbeddingBatchPlanRequest.model_validate(request)
    pointers = (request.selection_manifest, request.routing_policy)
    reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in pointers))
    selection = EmbeddingBatchSelection.model_validate(
        CatalogEmbeddingBatchPlanAdmission._read_control(
            reader, request.selection_manifest, BATCH_SELECTION_ARTIFACT_TYPE, MAX_BATCH_PLAN_BYTES
        )
    )
    policy = EmbeddingDeviceRoutingPolicy.model_validate(
        CatalogEmbeddingBatchPlanAdmission._read_control(
            reader,
            request.routing_policy,
            DEVICE_ROUTING_POLICY_ARTIFACT_TYPE,
            MAX_EMBEDDING_DEVICE_ROUTING_BYTES,
        )
    )
    validate_embedding_batch_plan_controls(request, selection, policy)
    return selection, policy
