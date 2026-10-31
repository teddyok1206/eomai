"""Catalog-owned authorized snapshot producer, not an installed transport operation.

Identity/permission/source/report admission precedes bounded owner Artifact reads.
The CPU harness and workers never receive database or NAS access from this port.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, cast

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AssessmentItemContentContract,
    CreateEvidenceBundleCommand,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    MAX_GRAPH_BASELINE_CANDIDATES,
    ExperimentViewRecipe,
    StagedExperimentEntry,
    SuppliedGraphBaseline,
    profile_key,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotRecord,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_identifiers import content_sha256
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    ControlArtifactResolutionError,
    resolve_control_artifact_members,
)
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, or_, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactReader, CatalogModelArtifactReader
from eom_catalog_service.inference_transfer_catalog_adapter import (
    AcceptedInferenceTransferProfileInput,
    CatalogInferenceTransferSourceAdapter,
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_item_projection import project_staged_item_entry
from eom_catalog_service.inference_transfer_population_read_set import (
    InferenceTransferPopulationReadSet,
)
from eom_catalog_service.inference_transfer_population_read_set import (
    population_membership_statement as population_membership_statement,
)
from eom_catalog_service.inference_transfer_read_timing import (
    InferenceTransferReadStage,
    observe_read_stage,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_service import (
    AuthorizedSnapshotCapture,
    hashed_snapshot_value,
    prepare_snapshot_value,
    validate_snapshot_selection,
)
from eom_catalog_service.item_content_contract import (
    ITEM_CONTENT_SCHEMAS,
    read_item_content,
)
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
    ReadOnlyKnowledgeCandidatePool,
    ReadOnlyKnowledgeReuseContext,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_paging import (
    CandidateSourcePage,
    candidate_source_page_statement,
    validate_candidate_source_page,
)
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceAuthorization,
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_artifact_prefetch import prefetch_past_exam_artifact_closure
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    artifact_identity_hints,
)
from eom_catalog_service.segmented_local_indexing_population_read import (
    SegmentedPopulationReadError,
    read_segmented_candidate_source_page,
)
from eom_catalog_service.settings import CatalogSettings

_MAXIMUM_ITEM_MEMBER_BYTES = 16 * 1024**2
_MAXIMUM_ARTIFACT_BATCH_BYTES = 128 * 1024**2
_MAXIMUM_INDEXING_CAPTURE_PAGE_SOURCES = 128


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate canonical Item JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _decode_item_content(schema_ref: str, payload: bytes) -> AssessmentItemContentContract:
    document = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(document, dict):
        raise ValueError("canonical Item must be a JSON object")
    return read_item_content(schema_ref, document)


class InferenceTransferSessionCapturePhase(StrEnum):
    AUTHORIZE_SCOPE = "AUTHORIZE_SCOPE"
    CAPTURE_POPULATION = "CAPTURE_POPULATION"


@dataclass(frozen=True, slots=True)
class InferenceTransferSessionCapture:
    scope: ReadOnlyCandidatePoolScope
    corpus: AdmittedInferenceTransferCorpus | None = None
    entries: tuple[StagedExperimentEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class LocalIndexingSessionCapture:
    """Actual checked service read result; no operator role/permission projection."""

    scope: LocalIndexingSourceReadIntent
    corpus: AdmittedInferenceTransferCorpus | None = None
    entries: tuple[StagedExperimentEntry, ...] = ()


class CatalogInferenceTransferSnapshotSourceAdapter:
    """Actual-actor owner port; every capture recomputes the complete exact scope."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.engine = engine
        self.sources = CatalogInferenceTransferSourceAdapter(engine, settings)

    def _materialize_entries(
        self,
        request: InferenceTransferSnapshotPrepareRequest | ExperimentViewRecipe,
        inputs: tuple[AcceptedInferenceTransferProfileInput, ...],
        *,
        artifact_reader: CatalogArtifactReader | None = None,
    ) -> dict[str, StagedExperimentEntry]:
        """One explicit owner-local materialization; exact member checks precede parsing."""
        pointers: dict[ArtifactMemberPointer, int] = {}
        inputs_by_pointer: dict[
            ArtifactMemberPointer, list[AcceptedInferenceTransferProfileInput]
        ] = {}
        result: dict[str, StagedExperimentEntry] = {}
        for value in inputs:
            profile = value.profile
            run_id = profile.source_basis.solution_evidence.base_analysis_run_id
            member = profile.source_basis.source.artifact_member
            unavailable: str | None = None
            if member.media_type != "application/json":
                unavailable = "INFERENCE_ITEM_CONTENT_MEDIA_TYPE_UNAVAILABLE"
            elif member.schema_ref not in ITEM_CONTENT_SCHEMAS:
                unavailable = "INFERENCE_ITEM_CONTENT_SCHEMA_UNAVAILABLE"
            elif member.bytes > _MAXIMUM_ITEM_MEMBER_BYTES:
                unavailable = "INFERENCE_ITEM_CONTENT_BYTES_TOO_LARGE"
            else:
                pointer = ArtifactMemberPointer(
                    artifact_id=member.artifact_id,
                    artifact_revision_id=member.artifact_revision_id,
                    member_path=member.member_path,
                    schema_ref=cast(str, member.schema_ref),
                    media_type=member.media_type,
                    sha256=member.sha256,
                )
                if pointer in pointers and pointers[pointer] != member.bytes:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                pointers[pointer] = member.bytes
                inputs_by_pointer.setdefault(pointer, []).append(value)
            if unavailable is not None:
                result[run_id] = StagedExperimentEntry(
                    profile=profile,
                    content=None,
                    metadata=(),
                    limitations=(unavailable,),
                )
        batch: list[BoundedControlArtifactRead] = []
        batch_bytes = 0

        def project_member(
            pointer: ArtifactMemberPointer, item: AssessmentItemContentContract
        ) -> None:
            # Share decoding, not exact profile/report identity or its projection.
            for value in inputs_by_pointer[pointer]:
                run_id = value.profile.source_basis.solution_evidence.base_analysis_run_id
                result[run_id] = project_staged_item_entry(
                    profile=value.profile,
                    item=item,
                    accepted_report=value.report,
                    recipe=request.recipe
                    if isinstance(request, InferenceTransferSnapshotPrepareRequest)
                    else request,
                )

        def read_batch() -> None:
            if not batch:
                return
            try:
                if isinstance(artifact_reader, CatalogModelArtifactReader):
                    for read in batch:
                        pointer = cast(ArtifactMemberPointer, read.pointer)
                        project_member(
                            pointer,
                            artifact_reader.read_model_member(
                                pointer,
                                expected_bytes=pointers[pointer],
                                decoder=_decode_item_content,
                            ),
                        )
                    batch.clear()
                    return
                values = (
                    resolve_control_artifact_members(self.engine, tuple(batch))
                    if artifact_reader is None
                    else tuple(
                        artifact_reader.read_member(
                            artifact_id=read.pointer.artifact_id,
                            revision_id=read.pointer.artifact_revision_id,
                            member_path=read.pointer.member_path,
                            sha256=read.pointer.sha256,
                            schema_ref=read.pointer.schema_ref,
                            media_type=read.pointer.media_type,
                            max_bytes=read.maximum_bytes,
                        )
                        for read in batch
                    )
                )
            except (ControlArtifactResolutionError, OSError, ValueError) as exc:
                raise InferenceTransferServiceError(
                    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH"
                ) from exc
            if len(values) != len(batch):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
            for read, payload in zip(batch, values, strict=True):
                pointer = cast(ArtifactMemberPointer, read.pointer)
                if len(payload) != pointers[pointer]:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                try:
                    project_member(pointer, _decode_item_content(pointer.schema_ref, payload))
                except (UnicodeError, ValueError) as exc:
                    raise InferenceTransferServiceError(
                        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH"
                    ) from exc
            batch.clear()

        for pointer, size in pointers.items():
            if len(batch) == 128 or batch_bytes + size > _MAXIMUM_ARTIFACT_BATCH_BYTES:
                read_batch()
                batch_bytes = 0
            batch.append(BoundedControlArtifactRead(pointer, maximum_bytes=size))
            batch_bytes += size
        read_batch()
        return result

    def capture_in_session(
        self,
        session: Session,
        command: InferenceTransferCorpusReadCommand,
        recipe: ExperimentViewRecipe,
        *,
        identity_fence: OperatorAuthorizationFence | None,
        artifact_reader: PinnedArtifactReadContext,
        phase: InferenceTransferSessionCapturePhase = (
            InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
        ),
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> InferenceTransferSessionCapture:
        """One current-operator owner operation in the caller's Catalog transaction.

        Scope-only mode performs no source/member IO. Population capture fences
        mutable source rows and delegates eligibility/projection to existing rules.
        Published membership is a bounded metadata-prefetch hint, never admission.
        """
        if not isinstance(phase, InferenceTransferSessionCapturePhase):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        scope = self.authorize_scope_in_session(
            session, command, identity_fence=identity_fence, artifact_reader=artifact_reader
        )
        if phase is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
            return InferenceTransferSessionCapture(scope)
        if population_read_set is not None:
            reused = population_read_set.reuse(session, scope, recipe, artifact_reader)
            if reused is not None:
                return reused
        corpus, entries = self._capture_population(
            session,
            scope,
            recipe,
            artifact_reader=artifact_reader,
            read_pool=lambda: self.sources.retrieval.admit_read_only_candidate_pool(
                session,
                scope,
                artifact_reader=artifact_reader,
            ),
            population_read_set=population_read_set,
        )
        capture = InferenceTransferSessionCapture(scope, corpus, entries)
        if population_read_set is not None:
            population_read_set.complete(session, scope, recipe, artifact_reader, capture)
        return capture

    def authorize_scope_in_session(
        self,
        session: Session,
        command: InferenceTransferCorpusReadCommand,
        *,
        identity_fence: OperatorAuthorizationFence | None,
        artifact_reader: PinnedArtifactReadContext,
    ) -> ReadOnlyCandidatePoolScope:
        """Existing actual-principal and pinned policy/Graph boundary, without profiles."""
        if identity_fence is None:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_AUTHORITY_UNAVAILABLE")
        artifact_reader.require_session(session)
        identity_fence.fence_current_operator(session, command.actor_id)
        scope = self.sources._scope(session, command)
        policy = self.sources.retrieval.resolve_access_policy(
            session, scope.access_policy_revision_id, sha256=scope.access_policy_sha256
        )
        self.sources.retrieval._authorize(session, scope, policy)
        if (
            self.sources.retrieval.resolve_snapshot_pointer(
                session, scope.graph_snapshot.graph_snapshot_revision_id
            )
            != scope.graph_snapshot
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        return scope

    def capture_public_solution_pool_in_session(
        self,
        session: Session,
        command: InferenceTransferCorpusReadCommand,
        *,
        identity_fence: OperatorAuthorizationFence,
        artifact_reader: PinnedArtifactReadContext,
    ) -> tuple[ReadOnlyCandidatePoolScope, ReadOnlyKnowledgeCandidatePool]:
        """Source admission shared with existing INDEX/QUERY, not an old-profile conversion."""
        scope = self.authorize_scope_in_session(
            session, command, identity_fence=identity_fence, artifact_reader=artifact_reader
        )
        pool = self._capture_source_pool(
            session,
            scope,
            None,
            artifact_reader=artifact_reader,
            read_pool=lambda: self.sources.retrieval.admit_read_only_candidate_pool(
                session,
                scope,
                artifact_reader=artifact_reader,
            ),
        )
        return scope, pool

    def capture_public_solution_indexing_pool_in_session(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        *,
        authority: LocalIndexingSourceAuthorization,
        artifact_reader: PinnedArtifactReadContext,
    ) -> ReadOnlyKnowledgeCandidatePool:
        """Same actual service fence and canonical source admission; no legacy profiles."""
        artifact_reader.require_session(session)
        policy = authority.authorize_scope(session, intent)
        if (
            not isinstance(policy, PublicSolutionIndexingAccessPolicy)
            or not isinstance(intent.namespace, PublicSolutionIndexNamespace)
            or not isinstance(intent.recipe, PublicSolutionEmbeddingRecipe)
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        pool = self._capture_source_pool(
            session,
            intent,
            None,
            artifact_reader=artifact_reader,
            read_pool=lambda: self.sources.retrieval.admit_local_indexing_candidate_pool(
                session, intent, authority=authority, artifact_reader=artifact_reader
            ),
        )
        if authority.authorize_scope(session, intent) != policy:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return pool

    def capture_indexing_in_session(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        *,
        authority: LocalIndexingSourceAuthorization | None,
        artifact_reader: PinnedArtifactReadContext,
        phase: InferenceTransferSessionCapturePhase = (
            InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
        ),
    ) -> LocalIndexingSessionCapture:
        """Service purpose front door; reuse exact source locks, resolver and projection."""
        if authority is None or not isinstance(phase, InferenceTransferSessionCapturePhase):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        artifact_reader.require_session(session)
        policy = authority.authorize_scope(session, intent)
        if phase is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
            return LocalIndexingSessionCapture(intent)
        if not isinstance(intent.recipe, ExperimentViewRecipe):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        if not intent.source_revision_ids and not intent.analysis_run_ids:
            return self._capture_indexing_population_pages(
                session, intent, authority=authority, artifact_reader=artifact_reader
            )
        corpus, entries = self._capture_population(
            session,
            intent,
            intent.recipe,
            artifact_reader=artifact_reader,
            read_pool=lambda: self.sources.retrieval.admit_local_indexing_candidate_pool(
                session,
                intent,
                authority=authority,
                artifact_reader=artifact_reader,
            ),
        )
        if authority.authorize_scope(session, intent) != policy:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return LocalIndexingSessionCapture(intent, corpus, entries)

    def _capture_indexing_population_pages(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        *,
        authority: LocalIndexingSourceAuthorization,
        artifact_reader: PinnedArtifactReadContext,
    ) -> LocalIndexingSessionCapture:
        """Released population, bounded reader lifetimes; no segmented-policy reinterpretation."""
        policy = authority.authorize_scope(session, intent)
        page_scope = replace(
            intent,
            maximum_candidates=min(
                intent.maximum_candidates, _MAXIMUM_INDEXING_CAPTURE_PAGE_SOURCES
            ),
        )

        def read_page(after: str | None) -> CandidateSourcePage:
            return validate_candidate_source_page(
                tuple(
                    tuple(row)
                    for row in session.execute(
                        candidate_source_page_statement(page_scope, after_source_revision_id=after)
                    )
                ),
                maximum=page_scope.maximum_candidates,
                after_source_revision_id=after,
            )

        pages: list[tuple[str | None, CandidateSourcePage]] = []
        captured: list[LocalIndexingSessionCapture] = []
        total = 0
        after = None
        while True:
            page = read_page(after)
            total += len(page.members)
            if total > intent.maximum_candidates:
                raise InferenceTransferServiceError(
                    "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED"
                )
            pages.append((after, page))
            if page.members:
                page_reader = PinnedArtifactReadContext(session, artifact_reader.settings)
                value = self.capture_indexing_in_session(
                    session,
                    replace(intent, source_revision_ids=tuple(key for key, _ in page.members)),
                    authority=authority,
                    artifact_reader=page_reader,
                )
                if (
                    value.corpus is None
                    or tuple(
                        sorted(
                            (row.source.item_revision_id, row.analysis_run_id)
                            for row in value.corpus.sources
                        )
                    )
                    != page.members
                ):
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                page_reader.revalidate_provenance()
                captured.append(value)
            if page.complete:
                break
            after = page.next_after_source_revision_id
        if any(read_page(cursor) != page for cursor, page in pages):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        if authority.authorize_scope(session, intent) != policy:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        artifact_reader.revalidate_provenance()
        corpora = tuple(value.corpus for value in captured if value.corpus is not None)
        return LocalIndexingSessionCapture(
            intent,
            AdmittedInferenceTransferCorpus(
                profiles=tuple(profile for corpus in corpora for profile in corpus.profiles),
                graph_scores=(),
                truncated=False,
                missing_solution_reports=sum(corpus.missing_solution_reports for corpus in corpora),
                sources=tuple(source for corpus in corpora for source in corpus.sources),
            ),
            tuple(entry for value in captured for entry in value.entries),
        )

    def capture_segmented_indexing_page_in_session(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        *,
        authority: CatalogLocalIndexingSourceAuthority,
        artifact_reader: PinnedArtifactReadContext,
        after_source_revision_id: str | None = None,
    ) -> tuple[CandidateSourcePage, LocalIndexingSessionCapture]:
        """Resolve one 1.3 page through the existing profile/Artifact capture owner."""
        if intent.analysis_run_ids or intent.source_revision_ids:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_CONTEXT_INVALID")
        artifact_reader.require_session(session)
        # One page must not inherit the previous page's bounded Artifact cache.
        # The DB root stays fixed, while each page gets its own reader lifetime.
        if artifact_reader.provenance_identities():
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_CONTEXT_INVALID")
        policy, page = read_segmented_candidate_source_page(
            session,
            intent,
            authority=authority,
            after_source_revision_id=after_source_revision_id,
        )
        if not page.members:
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_INCOMPLETE")
        page_intent = replace(
            intent,
            analysis_run_ids=tuple(sorted(run for _, run in page.members)),
            source_revision_ids=tuple(sorted(source for source, _ in page.members)),
        )
        if not isinstance(page_intent.recipe, ExperimentViewRecipe):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        corpus, entries = self._capture_population(
            session,
            page_intent,
            page_intent.recipe,
            artifact_reader=artifact_reader,
            read_pool=lambda: self.sources.retrieval.admit_segmented_local_indexing_candidate_pool(
                session,
                page_intent,
                authority=authority,
                artifact_reader=artifact_reader,
            ),
        )
        observed = tuple(
            sorted((row.source.item_revision_id, row.analysis_run_id) for row in corpus.sources)
        )
        if observed != page.members:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        final_policy, final_page = read_segmented_candidate_source_page(
            session,
            intent,
            authority=authority,
            after_source_revision_id=after_source_revision_id,
        )
        if (final_policy, final_page) != (policy, page):
            raise SegmentedPopulationReadError("SEGMENTED_POPULATION_READ_UNAVAILABLE")
        artifact_reader.revalidate_provenance()
        return page, LocalIndexingSessionCapture(page_intent, corpus, entries)

    def _capture_source_pool(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        recipe: ExperimentViewRecipe | None,
        *,
        artifact_reader: PinnedArtifactReadContext,
        read_pool: Callable[[], ReadOnlyKnowledgeCandidatePool],
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> ReadOnlyKnowledgeCandidatePool:
        """One lock/prefetch/physical-byte source path before report-family projection."""
        with observe_read_stage(InferenceTransferReadStage.LOCK_POPULATION):
            if recipe is not None:
                recipe = ExperimentViewRecipe.model_validate(recipe.model_dump(mode="json"))
            memberships = tuple(session.scalars(population_membership_statement(scope)))
            if len(memberships) > scope.maximum_candidates:
                raise InferenceTransferServiceError(
                    "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED"
                )
            revisions = tuple(sorted({row.source_revision_id for row in memberships}))
            source_rows = tuple(
                session.execute(
                    select(ItemRecord, ItemRevisionRecord)
                    .join(ItemRevisionRecord, ItemRevisionRecord.item_id == ItemRecord.item_id)
                    .where(ItemRevisionRecord.item_revision_id.in_(revisions))
                    .order_by(ItemRecord.item_id, ItemRevisionRecord.item_revision_id)
                    .with_for_update(read=True, of=(ItemRecord, ItemRevisionRecord))
                    .execution_options(populate_existing=True)
                )
            )
            base_ids = tuple(sorted({row.analysis_run_id for row in memberships}))
            runs = tuple(
                session.scalars(
                    select(KnowledgeAnalysisRunRecord)
                    .where(
                        or_(
                            KnowledgeAnalysisRunRecord.analysis_run_id.in_(base_ids),
                            (KnowledgeAnalysisRunRecord.predecessor_analysis_run_id.in_(base_ids))
                            & (KnowledgeAnalysisRunRecord.state == "ACCEPTED")
                            & (
                                KnowledgeAnalysisRunRecord.canonical_request[
                                    "schema_version"
                                ].astext
                                == "knowledge-analysis-request/10.0"
                            ),
                        )
                    )
                    .order_by(KnowledgeAnalysisRunRecord.analysis_run_id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
            )
            components = tuple(
                session.scalars(
                    select(ItemComponentRecord).where(
                        ItemComponentRecord.item_revision_id.in_(revisions),
                        ItemComponentRecord.component_type == "ITEM_CONTENT",
                        ItemComponentRecord.ordinal == 0,
                    )
                )
            )
        identities = (
            {(row.source_artifact_id, row.source_artifact_revision_id) for row in memberships}
            | {
                (row.accepted_result_artifact_id, row.accepted_result_artifact_revision_id)
                for row in memberships
            }
            | {
                (revision.manifest_artifact_id, revision.manifest_artifact_revision_id)
                for _item, revision in source_rows
            }
            | {(row.artifact_id, row.artifact_revision_id) for row in components}
        )
        for run in runs:
            identities.update(artifact_identity_hints(run.canonical_request))
            for artifact, revision in (
                (run.accepted_result_artifact_id, run.accepted_result_artifact_revision_id),
                (run.proposal_artifact_id, run.proposal_artifact_revision_id),
            ):
                if artifact is not None and revision is not None:
                    identities.add((artifact, revision))
        graph_member = scope.graph_snapshot.manifest_artifact
        identities.add((graph_member.artifact_id, graph_member.artifact_revision_id))
        with observe_read_stage(InferenceTransferReadStage.PREFETCH_PROVENANCE):
            artifact_reader.prefetch(tuple(sorted(identities)))
            # Publication metadata pins this member; prove its actual immutable bytes
            # in this root transaction without granting any source permission.
            artifact_reader.verify_member(
                artifact_id=graph_member.artifact_id,
                revision_id=graph_member.artifact_revision_id,
                member_path=graph_member.member_path,
                sha256=graph_member.sha256,
                schema_ref=graph_member.schema_ref,
                media_type=graph_member.media_type,
                max_bytes=64 * 1024**2,
            )
            layout_observation_ids = prefetch_past_exam_artifact_closure(
                session, tuple(revision for _item, revision in source_rows), artifact_reader
            )
        if population_read_set is not None:
            if not isinstance(scope, ReadOnlyCandidatePoolScope) or recipe is None:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
            population_read_set.begin(
                session,
                scope,
                recipe,
                artifact_reader,
                layout_observation_ids=layout_observation_ids,
            )
            # Initial prefetch precedes the baseline. Refresh the same bounded
            # mutable lineage rows after it, so held ORM values cannot bless an
            # already changed acceptance/batch/bundle/layout under a new digest.
            if (
                prefetch_past_exam_artifact_closure(
                    session, tuple(revision for _item, revision in source_rows), artifact_reader
                )
                != layout_observation_ids
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        with observe_read_stage(InferenceTransferReadStage.ADMIT_CANDIDATES):
            pool = read_pool()
        if pool.truncated:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED")
        return pool

    def _capture_population(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        recipe: ExperimentViewRecipe,
        *,
        artifact_reader: PinnedArtifactReadContext,
        read_pool: Callable[[], ReadOnlyKnowledgeCandidatePool],
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> tuple[AdmittedInferenceTransferCorpus, tuple[StagedExperimentEntry, ...]]:
        """Released legacy profile projection over the unchanged shared source capture."""
        pool = self._capture_source_pool(
            session,
            scope,
            recipe,
            artifact_reader=artifact_reader,
            read_pool=read_pool,
            population_read_set=population_read_set,
        )
        with observe_read_stage(InferenceTransferReadStage.SOLUTION_PROFILES):
            inputs, missing = self.sources._resolve_profile_inputs(
                session, pool, artifact_reader=artifact_reader
            )
        admitted_rows = []
        for row in pool.candidates:
            if not isinstance(row.source, ApprovedItemKnowledgeSourceV2):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
            admitted_rows.append(AdmittedInferenceTransferSource(row.analysis_run_id, row.source))
        admitted = tuple(admitted_rows)
        corpus = AdmittedInferenceTransferCorpus(
            profiles=tuple(row.profile for row in inputs),
            graph_scores=(),
            truncated=False,
            missing_solution_reports=missing,
            sources=admitted,
        )
        with observe_read_stage(InferenceTransferReadStage.MATERIALIZE_ENTRIES):
            entries = self._materialize_entries(recipe, inputs, artifact_reader=artifact_reader)
        return corpus, tuple(entries[key] for key in sorted(entries))

    def _baselines(
        self,
        session: Session,
        request: InferenceTransferSnapshotPrepareRequest,
        scope: ReadOnlyCandidatePoolScope,
        entries: dict[str, StagedExperimentEntry],
        eligible_inputs: tuple[AcceptedInferenceTransferProfileInput, ...],
        admitted_sources: tuple[AdmittedInferenceTransferSource, ...],
        *,
        reuse_context: ReadOnlyKnowledgeReuseContext,
    ) -> tuple[tuple[SuppliedGraphBaseline, ...], tuple[str, ...]]:
        profiles_by_run = {}
        for row in eligible_inputs:
            run_id = row.profile.source_basis.solution_evidence.base_analysis_run_id
            profiles_by_run[run_id] = InferenceTransferProfilePointer.from_profile(row.profile)
        sources_by_run = {row.analysis_run_id: row.source for row in admitted_sources}
        baselines: list[SuppliedGraphBaseline] = []
        limitations: set[str] = set()
        selected_queries = tuple(
            value
            for value in entries.values()
            if value.profile.source_basis.source.item_revision_id in request.query_item_revision_ids
        )
        for entry in selected_queries:
            if entry.content is None:
                limitations.add(
                    "Requested query CONTENT is unavailable; no official Graph baseline "
                    "was materialized."
                )
                continue
            terms = knowledge_node_terms("", entry.content.text)
            if len(terms) > 128:
                limitations.add(
                    "Lexical seed recipe uses the first 128 sorted unique terms; "
                    "question text is not truncated."
                )
            topic_keys = self.sources.retrieval.topic_keys_for_terms(
                session,
                snapshot_id=request.graph_snapshot.graph_snapshot_revision_id,
                terms=terms[:128],
                source_classes=request.source_classes,
                allow_answer_bearing=True,
            )
            if not topic_keys:
                limitations.add(
                    "No supported Graph topic keys matched a requested query; "
                    "baseline is unavailable, not an empty result."
                )
                continue
            body = {
                "operation": "CREATE_EVIDENCE_BUNDLE",
                "graph_snapshot_revision_id": request.graph_snapshot.graph_snapshot_revision_id,
                "query_kind": "ITEM_PREPARATION",
                "curriculum_scope": None,
                "topic_keys": topic_keys,
                "target_item_revision_id": None,
                "required_item_elements": (),
                "source_classes": request.source_classes,
                "evidence_budget": scope.evidence_budget.model_dump(mode="json"),
                "access_policy_revision_id": scope.access_policy_revision_id,
                "requester_role": scope.requester_role,
                "requester_permission_keys": scope.requester_permission_keys,
                "requested_by": scope.requested_by,
            }
            digest = content_sha256(body)
            command = CreateEvidenceBundleCommand.model_validate(
                body
                | {
                    "submission_sha256": digest,
                    "idempotency_key": "snapshot-baseline:" + digest[7:],
                }
            )
            try:
                selection = self.sources.retrieval.retrieve_read_only(
                    session, command, reuse_context=reuse_context
                )
            except KnowledgeRetrievalServiceError as exc:
                if exc.code != "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE":
                    raise
                limitations.add(
                    "Official retrieval returned insufficient evidence; "
                    "a baseline was not materialized."
                )
                continue
            query = InferenceTransferProfilePointer.from_profile(entry.profile)
            ordered: list[InferenceTransferProfilePointer] = []
            seen: set[InferenceTransferProfilePointer] = set()
            for candidate in selection.candidates:
                pointer = profiles_by_run.get(candidate.analysis_run_id)
                if sources_by_run.get(candidate.analysis_run_id) != candidate.source:
                    pointer = None
                if pointer is None or pointer == query or pointer in seen:
                    continue
                seen.add(pointer)
                ordered.append(pointer)
            if len(ordered) < len(selection.candidates):
                limitations.add(
                    "Official Graph order is filtered to frozen eligible report profiles "
                    "and excludes the query; ranking/budget are unchanged."
                )
            if not ordered:
                limitations.add(
                    "A materialized official baseline has zero eligible comparison candidates."
                )
            if len(ordered) > MAX_GRAPH_BASELINE_CANDIDATES:
                # The supported read-only Graph port returns its candidate pool,
                # not the final published Evidence selection. This bounded
                # experiment records a declared prefix, never a complete-pool
                # claim or a second implementation of authoring budget rules.
                limitations.add(
                    f"Official read-only Graph candidate order has {len(ordered)} eligible "
                    f"comparisons; this bounded baseline retains the first "
                    f"{MAX_GRAPH_BASELINE_CANDIDATES} in unchanged order. Remaining "
                    "candidates are not recorded in this baseline; it is not the "
                    "final authoring Evidence selection."
                )
                ordered = ordered[:MAX_GRAPH_BASELINE_CANDIDATES]
            baselines.append(
                hashed_snapshot_value(
                    SuppliedGraphBaseline,
                    "result_sha256",
                    query=query,
                    command_sha256=command.submission_sha256,
                    ordered_candidates=tuple(ordered),
                )
            )
        return tuple(sorted(baselines, key=lambda value: profile_key(value.query))), tuple(
            sorted(limitations)
        )

    def capture(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotPrepareRequest,
        *,
        expected_header: InferenceTransferSnapshotHeader | None = None,
        selected_index_entries: tuple[InferenceTransferSnapshotIndexEntry, ...] = (),
        materialize_all: bool = False,
    ) -> AuthorizedSnapshotCapture:
        request = InferenceTransferSnapshotPrepareRequest.model_validate(
            request.model_dump(mode="json")
        )
        command = InferenceTransferCorpusReadCommand(
            actor_id=actor_id,
            graph_snapshot=request.graph_snapshot,
            access_policy_revision_id=request.access_policy_revision_id,
            access_policy_sha256=request.access_policy_sha256,
            source_classes=request.source_classes,
            maximum_candidates=request.max_sources,
            population_scope=InferenceTransferPopulationScope(request.population_scope),
        )
        with self.sources.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            scope = self.sources._scope(session, command)
            reuse_context = self.sources.retrieval.create_read_only_reuse_context(session, scope)
            pool = self.sources.retrieval.admit_read_only_candidate_pool(
                session, scope, reuse_context=reuse_context
            )
            inputs, missing = self.sources._resolve_profile_inputs(session, pool)
            admitted = []
            for value in pool.candidates:
                if not isinstance(value.source, ApprovedItemKnowledgeSourceV2):
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                admitted.append(
                    AdmittedInferenceTransferSource(value.analysis_run_id, value.source)
                )
            corpus = AdmittedInferenceTransferCorpus(
                profiles=tuple(value.profile for value in inputs),
                graph_scores=(),
                truncated=pool.truncated,
                missing_solution_reports=missing,
                sources=tuple(admitted),
            )
            current = prepare_snapshot_value(actor_id, request, corpus)
            validate_snapshot_selection(current, expected_header, selected_index_entries)
            selected = current.index if materialize_all else selected_index_entries
            if not selected:
                return AuthorizedSnapshotCapture(corpus)
            run_ids = {row.base_analysis_run_id for row in selected}
            entries = self._materialize_entries(
                request,
                tuple(
                    value
                    for value in inputs
                    if value.profile.source_basis.solution_evidence.base_analysis_run_id in run_ids
                ),
            )
            sources_by_run = {value.analysis_run_id: value.source for value in corpus.sources}
            records = tuple(
                InferenceTransferSnapshotRecord(
                    index_entry=row,
                    source=sources_by_run[row.base_analysis_run_id],
                    staged_entry=entries.get(row.base_analysis_run_id),
                )
                for row in selected
            )
            baselines, limits = self._baselines(
                session,
                request,
                scope,
                entries,
                inputs,
                corpus.sources,
                reuse_context=reuse_context,
            )
            limitations = set(limits)
            if any(
                row.profile is None
                and row.source_item_revision_id in request.query_item_revision_ids
                for row in selected
            ):
                limitations.add(
                    "Requested query has no accepted solution report; "
                    "its source remains in the full denominator."
                )
            return AuthorizedSnapshotCapture(corpus, records, baselines, tuple(sorted(limitations)))
