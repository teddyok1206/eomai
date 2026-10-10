"""Catalog infrastructure adapter for exact, authorized inference-transfer inputs."""

from __future__ import annotations

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    CreateEvidenceBundleCommand,
    KnowledgeAnalysisResultV10,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferSourceBasis,
)
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.inference_transfer_projection import project_accepted_solution_report
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferSearchCommand,
    InferenceTransferServiceError,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalCandidate,
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.solution_evidence_resolution import (
    ResolvedSolutionEvidence,
    resolve_solution_evidence_by_base_run,
)


class CatalogInferenceTransferSourceAdapter:
    """Real supported read-only Catalog boundary; no worker DB/NAS access."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sessions = build_session_factory(engine)
        self.retrieval = KnowledgeRetrievalApplicationService(engine, settings)

    def _scope(
        self,
        session: Session,
        command: InferenceTransferSearchCommand,
        *,
        analysis_run_ids: tuple[str, ...] = (),
    ) -> ReadOnlyCandidatePoolScope:
        actor = session.get(OperatorRecord, command.actor_id)
        permissions = effective_permissions(session, command.actor_id)
        required = {
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        }
        if "PAST_EXAM" in command.source_classes:
            required.add(PermissionKey.CONTENT_INTAKE_READ)
        if (
            actor is None
            or actor.status != "ACTIVE"
            or actor.deleted_at is not None
            or actor.must_change_password
            or not required.issubset(permissions)
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
        policy = self.retrieval.resolve_access_policy(
            session, command.access_policy_revision_id, sha256=command.access_policy_sha256
        )
        roles = {
            role.role_key
            for _assignment, role in active_role_assignments(session, command.actor_id)
        }
        role = next(
            (
                role
                for role in ("ADMIN", "EDITOR", "REVIEWER")
                if role in roles
                and role in policy.allowed_requester_roles
                and role in policy.answer_bearing_roles
            ),
            None,
        )
        if role is None or command.top_k > policy.maximum_budget.max_item_revisions:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
        return ReadOnlyCandidatePoolScope(
            graph_snapshot=command.graph_snapshot,
            access_policy_revision_id=command.access_policy_revision_id,
            access_policy_sha256=command.access_policy_sha256,
            requested_by=command.actor_id,
            requester_role=role,
            requester_permission_keys=tuple(sorted(permission.value for permission in permissions)),
            source_classes=command.source_classes,
            evidence_budget=policy.maximum_budget,
            maximum_candidates=command.maximum_candidates,
            analysis_run_ids=analysis_run_ids,
        )

    @staticmethod
    def _basis(
        candidate: KnowledgeRetrievalCandidate,
        solution: ResolvedSolutionEvidence,
        graph: KnowledgeGraphSnapshotPointer,
    ) -> InferenceTransferSourceBasis:
        source = solution.source
        if (
            candidate.analysis_run_id != solution.pointer.base_analysis_run_id
            or candidate.source.source_class != source.source_class
            or getattr(candidate.source, "item_id", None) != source.item_id
            or getattr(candidate.source, "item_revision_id", None) != source.item_revision_id
            or candidate.source.artifact_member != source.artifact_member
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        return InferenceTransferSourceBasis(
            source=source, graph_snapshot=graph, solution_evidence=solution.pointer
        )

    def load(self, command: InferenceTransferSearchCommand) -> AdmittedInferenceTransferCorpus:
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            scope = self._scope(session, command)
            pool = self.retrieval.admit_read_only_candidate_pool(session, scope)
            solutions = resolve_solution_evidence_by_base_run(
                session,
                self.retrieval.artifacts,
                base_analysis_run_ids=tuple(
                    candidate.analysis_run_id for candidate in pool.candidates
                ),
            )
            revisions = {
                row.revision_id: row
                for row in session.scalars(
                    select(ArtifactRevisionRecord).where(
                        ArtifactRevisionRecord.revision_id.in_(
                            tuple(
                                value.pointer.accepted_result_artifact.artifact_revision_id
                                for value in solutions.values()
                            )
                        )
                    )
                )
            }
            profiles: list[InferenceTransferProfile] = []
            missing = 0
            for candidate in pool.candidates:
                solution = solutions.get(candidate.analysis_run_id)
                if solution is None:
                    missing += 1
                    continue
                accepted_pointer = solution.pointer.accepted_result_artifact
                revision = revisions.get(accepted_pointer.artifact_revision_id)
                if revision is None or revision.content_hash != accepted_pointer.sha256:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                accepted = KnowledgeAnalysisResultV10.model_validate(revision.result)
                profiles.append(
                    project_accepted_solution_report(
                        source_basis=self._basis(candidate, solution, pool.graph_snapshot),
                        report=solution.report,
                        created_at=accepted.accepted_at,
                    )
                )
            graph_scores: dict[str, int] = {}
            if command.topic_keys:
                body = {
                    "operation": "CREATE_EVIDENCE_BUNDLE",
                    "graph_snapshot_revision_id": command.graph_snapshot.graph_snapshot_revision_id,
                    "query_kind": "ITEM_PREPARATION",
                    "curriculum_scope": None,
                    "topic_keys": command.topic_keys,
                    "target_item_revision_id": None,
                    "required_item_elements": (),
                    "source_classes": command.source_classes,
                    "evidence_budget": scope.evidence_budget.model_dump(mode="json"),
                    "access_policy_revision_id": scope.access_policy_revision_id,
                    "requester_role": scope.requester_role,
                    "requester_permission_keys": scope.requester_permission_keys,
                    "requested_by": scope.requested_by,
                }
                digest = content_sha256(body)
                query = CreateEvidenceBundleCommand.model_validate(
                    {
                        **body,
                        "submission_sha256": digest,
                        "idempotency_key": "transfer-read:" + digest[7:],
                    }
                )
                try:
                    selection = self.retrieval.retrieve_read_only(session, query)
                except KnowledgeRetrievalServiceError as exc:
                    if exc.code != "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE":
                        raise
                else:
                    for candidate in selection.candidates:
                        revision_id = getattr(candidate.source, "item_revision_id", None)
                        if isinstance(revision_id, str):
                            graph_scores[revision_id] = max(
                                graph_scores.get(revision_id, 0), candidate.relevance_milli
                            )
            admitted_sources: list[AdmittedInferenceTransferSource] = []
            for candidate in pool.candidates:
                if not isinstance(candidate.source, ApprovedItemKnowledgeSourceV2):
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                admitted_sources.append(
                    AdmittedInferenceTransferSource(candidate.analysis_run_id, candidate.source)
                )
            return AdmittedInferenceTransferCorpus(
                tuple(profiles),
                tuple(sorted(graph_scores.items())),
                pool.truncated,
                missing,
                tuple(admitted_sources),
            )

    def reauthorize(
        self,
        command: InferenceTransferSearchCommand,
        corpus: AdmittedInferenceTransferCorpus,
    ) -> None:
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            # Full scope is required because even unranked source counts/hash are
            # returned. An exact-ID-only query would also lose the truncated pin.
            scope = self._scope(session, command)
            pool = self.retrieval.admit_read_only_candidate_pool(session, scope)
            expected = {row.analysis_run_id: row.source for row in corpus.sources}
            candidates = {candidate.analysis_run_id: candidate for candidate in pool.candidates}
            if (
                pool.truncated != corpus.truncated
                or {run_id: value.source for run_id, value in candidates.items()} != expected
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
            run_ids = tuple(
                sorted(
                    profile.source_basis.solution_evidence.base_analysis_run_id
                    for profile in corpus.profiles
                )
            )
            solutions = resolve_solution_evidence_by_base_run(
                session, self.retrieval.artifacts, base_analysis_run_ids=run_ids
            )
            for profile in corpus.profiles:
                base_id = profile.source_basis.solution_evidence.base_analysis_run_id
                candidate, solution = candidates.get(base_id), solutions.get(base_id)
                if (
                    candidate is None
                    or solution is None
                    or self._basis(candidate, solution, pool.graph_snapshot) != profile.source_basis
                ):
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
