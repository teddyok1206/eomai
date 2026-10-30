"""Official Graph source admission followed by exact family-specific report reads."""

from collections.abc import Callable
from dataclasses import replace

from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    same_approved_item_source_identity,
)
from eom_catalog_contracts.public_solution_embedding import (
    AcceptedPublicSolutionEvidence,
    CreativePublicSolutionEvidence,
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import MAX_PUBLIC_SOLUTION_SOURCES
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_identifiers import content_sha256
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_proposal_read_set import MAX_CREATIVE_REPORT_CAPTURE
from eom_catalog_service.creative_report_batch import load_registered_creative_reports
from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
)
from eom_catalog_service.knowledge_retrieval_service import (
    ReadOnlyCandidatePoolScope,
    ReadOnlyKnowledgeCandidatePool,
)
from eom_catalog_service.local_indexing_source_paging import (
    CandidateSourcePage,
    candidate_source_page_statement,
    validate_candidate_source_page,
)
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceAuthorization,
    LocalIndexingSourceReadIntent,
)
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_capture_ports import (
    CapturedPublicSolutionSources as CapturedPublicSolutionSources,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.solution_embedding_projection import (
    PublicSolutionReport,
    project_public_solution_text,
)
from eom_catalog_service.solution_evidence_resolution import resolve_solution_evidence_by_base_run

MAX_PUBLIC_SOLUTION_CAPTURE_BYTES = 64 * 1024**2


class CatalogPublicSolutionSourceCapture:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sources = CatalogInferenceTransferSnapshotSourceAdapter(engine, settings)
        self.artifacts = CatalogArtifactService(engine, settings)

    def capture_population_in_session(
        self,
        session: Session,
        command: InferenceTransferCorpusReadCommand,
        recipe: PublicSolutionEmbeddingRecipe,
        *,
        identity_fence: OperatorAuthorizationFence,
        artifact_reader: PinnedArtifactReadContext,
        maximum_population_sources: int,
    ) -> CapturedPublicSolutionSources:
        """Keyset metadata pages, one root transaction, exact final population proof.

        The old per-page 1,024 bound is not widened. Each page uses the same
        canonical admission path and a bounded byte-reader lifetime. Shared locks
        retain admitted source/provenance rows until the caller finishes; final
        paging rejects membership changes instead of publishing partial coverage.
        """
        if (
            type(maximum_population_sources) is not int
            or not 1 <= maximum_population_sources <= MAX_PUBLIC_SOLUTION_SOURCES
            or command.source_revision_ids
        ):
            raise ValueError("PUBLIC_SOLUTION_POPULATION_BOUND_INVALID")
        scope = self.sources.authorize_scope_in_session(
            session, command, identity_fence=identity_fence, artifact_reader=artifact_reader
        )
        return self._capture_population_in_session(
            session,
            scope,
            artifact_reader=artifact_reader,
            maximum_population_sources=maximum_population_sources,
            capture_page=lambda keys, reader: self.capture_in_session(
                session,
                replace(command, source_revision_ids=keys),
                recipe,
                identity_fence=identity_fence,
                artifact_reader=reader,
            ),
            reauthorize=lambda: self.sources.authorize_scope_in_session(
                session, command, identity_fence=identity_fence, artifact_reader=artifact_reader
            ),
        )

    def capture_indexing_in_session(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        *,
        authority: LocalIndexingSourceAuthorization,
        artifact_reader: PinnedArtifactReadContext,
    ) -> CapturedPublicSolutionSources:
        policy = authority.authorize_scope(session, intent)
        if not isinstance(policy, PublicSolutionIndexingAccessPolicy) or not isinstance(
            intent.recipe, PublicSolutionEmbeddingRecipe
        ):
            raise ValueError("PUBLIC_SOLUTION_SERVICE_POLICY_INVALID")
        pool = self.sources.capture_public_solution_indexing_pool_in_session(
            session, intent, authority=authority, artifact_reader=artifact_reader
        )
        value = self._capture_reports_in_session(
            session, intent, pool, intent.recipe, artifact_reader=artifact_reader
        )
        artifact_reader.revalidate_provenance()
        if authority.authorize_scope(session, intent) != policy:
            raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
        return value

    def capture_indexing_population_in_session(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        *,
        authority: LocalIndexingSourceAuthorization,
        artifact_reader: PinnedArtifactReadContext,
        maximum_population_sources: int,
    ) -> CapturedPublicSolutionSources:
        policy = authority.authorize_scope(session, intent)
        if (
            not isinstance(policy, PublicSolutionIndexingAccessPolicy)
            or not 1 <= maximum_population_sources <= policy.maximum_sources
            or intent.source_revision_ids
            or intent.analysis_run_ids
        ):
            raise ValueError("PUBLIC_SOLUTION_SERVICE_POLICY_INVALID")

        def reauthorize() -> LocalIndexingSourceReadIntent:
            if authority.authorize_scope(session, intent) != policy:
                raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
            return intent

        return self._capture_population_in_session(
            session,
            intent,
            artifact_reader=artifact_reader,
            maximum_population_sources=maximum_population_sources,
            capture_page=lambda keys, reader: self.capture_indexing_in_session(
                session,
                replace(intent, source_revision_ids=keys),
                authority=authority,
                artifact_reader=reader,
            ),
            reauthorize=reauthorize,
        )

    def _capture_population_in_session(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        *,
        artifact_reader: PinnedArtifactReadContext,
        maximum_population_sources: int,
        capture_page: Callable[
            [tuple[str, ...], PinnedArtifactReadContext], CapturedPublicSolutionSources
        ],
        reauthorize: Callable[[], ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent],
    ) -> CapturedPublicSolutionSources:
        """One traversal for the two real caller kinds; callbacks confer no authority."""

        def read_page(after: str | None) -> CandidateSourcePage:
            return validate_candidate_source_page(
                tuple(
                    tuple(row)
                    for row in session.execute(
                        candidate_source_page_statement(scope, after_source_revision_id=after)
                    )
                ),
                maximum=scope.maximum_candidates,
                after_source_revision_id=after,
            )

        pages: list[tuple[str | None, CandidateSourcePage]] = []
        captured: list[CapturedPublicSolutionSources] = []
        total_sources = total_bytes = 0
        after: str | None = None
        while True:
            page = read_page(after)
            total_sources += len(page.members)
            if total_sources > maximum_population_sources:
                raise ValueError("PUBLIC_SOLUTION_POPULATION_BOUND_EXCEEDED")
            pages.append((after, page))
            if page.members:
                selected = tuple(source for source, _run in page.members)
                page_reader = PinnedArtifactReadContext(session, artifact_reader.settings)
                value = capture_page(selected, page_reader)
                if (
                    value.corpus is None
                    or tuple(
                        (row.source.item_revision_id, row.analysis_run_id)
                        for row in value.corpus.sources
                    )
                    != page.members
                ):
                    raise ValueError("PUBLIC_SOLUTION_SOURCE_SET_INVALID")
                total_bytes += sum(
                    len(entry.public_solution.text.encode("utf-8"))
                    for entry in value.entries
                    if entry.public_solution.text is not None
                )
                if total_bytes > MAX_PUBLIC_SOLUTION_CAPTURE_BYTES:
                    raise ValueError("PUBLIC_SOLUTION_CAPTURE_BUDGET_EXCEEDED")
                captured.append(value)
            if page.complete:
                break
            after = page.next_after_source_revision_id
        if any(read_page(cursor) != page for cursor, page in pages):
            raise ValueError("PUBLIC_SOLUTION_POPULATION_CHANGED")
        if reauthorize() != scope:
            raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
        artifact_reader.revalidate_provenance()
        sources = tuple(
            row for value in captured if value.corpus is not None for row in value.corpus.sources
        )
        missing = tuple(key for value in captured for key in value.missing_report_revision_ids)
        return CapturedPublicSolutionSources(
            tuple(entry for value in captured for entry in value.entries),
            missing,
            tuple(row.source.item_revision_id for row in sources),
            scope,
            AdmittedInferenceTransferCorpus((), (), False, len(missing), sources),
        )

    def capture_in_session(
        self,
        session: Session,
        command: InferenceTransferCorpusReadCommand,
        recipe: PublicSolutionEmbeddingRecipe,
        *,
        identity_fence: OperatorAuthorizationFence,
        artifact_reader: PinnedArtifactReadContext,
    ) -> CapturedPublicSolutionSources:
        """No invented V10 or REVIEW family; caller owns registration's transaction.

        Actual operator permissions and pinned source access are checked by the
        same Catalog owner as existing INDEX/QUERY. Report IO is bounded and
        batched; equal numerical text does not collapse the source proofs.
        """
        recipe = PublicSolutionEmbeddingRecipe.model_validate(recipe.model_dump(mode="json"))
        scope, pool = self.sources.capture_public_solution_pool_in_session(
            session, command, identity_fence=identity_fence, artifact_reader=artifact_reader
        )
        value = self._capture_reports_in_session(
            session, scope, pool, recipe, artifact_reader=artifact_reader
        )
        artifact_reader.revalidate_provenance()
        final_scope = self.sources.authorize_scope_in_session(
            session, command, identity_fence=identity_fence, artifact_reader=artifact_reader
        )
        if final_scope != scope:
            raise ValueError("PUBLIC_SOLUTION_AUTHORITY_CHANGED")
        return value

    def _capture_reports_in_session(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        pool: ReadOnlyKnowledgeCandidatePool,
        recipe: PublicSolutionEmbeddingRecipe,
        *,
        artifact_reader: PinnedArtifactReadContext,
    ) -> CapturedPublicSolutionSources:
        """Family projection after real admission; this helper is not a permission grant."""
        candidates = {
            value.source.item_revision_id: value
            for value in pool.candidates
            if isinstance(value.source, ApprovedItemKnowledgeSourceV2)
        }
        if len(candidates) != len(pool.candidates):
            raise ValueError("PUBLIC_SOLUTION_SOURCE_SET_INVALID")
        sources = {
            key: candidate.source
            for key, candidate in candidates.items()
            if isinstance(candidate.source, ApprovedItemKnowledgeSourceV2)
        }
        keys = tuple(sorted(candidates))
        revisions = {
            row.item_revision_id: row
            for row in session.scalars(
                select(ItemRevisionRecord)
                .where(ItemRevisionRecord.item_revision_id.in_(keys))
                .order_by(ItemRevisionRecord.item_revision_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        }
        if set(revisions) != set(keys) or any(
            row.revision_state != "APPROVED" or row.item_id != sources[key].item_id
            for key, row in revisions.items()
        ):
            raise ValueError("PUBLIC_SOLUTION_SOURCE_SET_INVALID")
        creative_keys = tuple(
            key for key in keys if revisions[key].metadata_json.get("source_kind") == "CREATIVE"
        )
        creative_set = frozenset(creative_keys)
        resolved = resolve_solution_evidence_by_base_run(
            session,
            artifact_reader,
            base_analysis_run_ids=tuple(
                candidate.analysis_run_id
                for key, candidate in candidates.items()
                if key not in creative_set
            ),
        )
        entries = {}
        missing = []
        total_bytes = 0

        def store(
            key: str,
            evidence: AcceptedPublicSolutionEvidence | CreativePublicSolutionEvidence,
            report: PublicSolutionReport,
        ) -> None:
            nonlocal total_bytes
            candidate = candidates[key]
            text = project_public_solution_text(report)
            total_bytes += 0 if text.text is None else len(text.text.encode("utf-8"))
            if total_bytes > MAX_PUBLIC_SOLUTION_CAPTURE_BYTES:
                raise ValueError("PUBLIC_SOLUTION_CAPTURE_BUDGET_EXCEEDED")
            body = {
                "schema_version": "public-solution-embedding-entry/1.0",
                "source": candidate.source,
                "base_analysis_run_id": candidate.analysis_run_id,
                "graph_snapshot": pool.graph_snapshot,
                "policy_revision_id": scope.access_policy_revision_id,
                "policy_sha256": scope.access_policy_sha256,
                "recipe": recipe,
                "evidence": evidence,
                "public_solution": text,
            }
            entries[key] = PublicSolutionEmbeddingEntry.model_validate(
                body | {"entry_sha256": content_sha256(body)}
            )

        for key in keys:
            if key in creative_set:
                continue
            candidate = candidates[key]
            solution = resolved.get(candidate.analysis_run_id)
            if solution is None:
                missing.append(key)
            elif not same_approved_item_source_identity(solution.source, sources[key]):
                raise ValueError("PUBLIC_SOLUTION_SOURCE_POINTER_MISMATCH")
            else:
                store(
                    key, AcceptedPublicSolutionEvidence(solution=solution.pointer), solution.report
                )
        for offset in range(0, len(creative_keys), MAX_CREATIVE_REPORT_CAPTURE):
            page = creative_keys[offset : offset + MAX_CREATIVE_REPORT_CAPTURE]
            reports = load_registered_creative_reports(
                session,
                self.artifacts,
                tuple(revisions[key] for key in page),
                artifact_reader=artifact_reader,
            )
            if set(reports) != set(page):
                raise ValueError("PUBLIC_SOLUTION_SOURCE_SET_INVALID")
            for key in page:
                captured = reports[key]
                lineage, proposal = captured.report.lineage, captured.report.proposal
                source = candidates[key].source
                if source.artifact_member.sha256 != lineage.registered_content_sha256:
                    raise ValueError("PUBLIC_SOLUTION_SOURCE_POINTER_MISMATCH")
                store(
                    key,
                    CreativePublicSolutionEvidence(
                        lineage=captured.lineage_pointer,
                        lineage_sha256=lineage.lineage_sha256,
                        role_result=lineage.role_result,
                        result_id=lineage.result_id,
                        result_sha256=lineage.result_sha256,
                    ),
                    proposal.role.output.learning_result,
                )
        return CapturedPublicSolutionSources(
            tuple(entries[key] for key in sorted(entries)),
            tuple(sorted(missing)),
            keys,
            scope,
            AdmittedInferenceTransferCorpus(
                profiles=(),
                graph_scores=(),
                truncated=False,
                missing_solution_reports=len(missing),
                sources=tuple(
                    AdmittedInferenceTransferSource(candidates[key].analysis_run_id, sources[key])
                    for key in keys
                ),
            ),
        )
