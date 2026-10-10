"""Catalog-owned exact Graph metadata read; no population/content or control mutation."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_metadata import (
    InferenceTransferMetadataResolveRequest,
    InferenceTransferMetadataResolveResult,
    parse_metadata_request,
    validate_metadata_result,
)
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select, text

from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.settings import CatalogSettings


class CatalogInferenceTransferMetadataService:
    """The actual API principal is reauthorized on every read, including replay."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sessions = build_session_factory(engine)
        self.retrieval = KnowledgeRetrievalApplicationService(engine, settings)

    def resolve(
        self, actor_id: str, request: InferenceTransferMetadataResolveRequest
    ) -> InferenceTransferMetadataResolveResult:
        request = parse_metadata_request(request.model_dump(mode="json"))
        with self.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            actor = session.get(OperatorRecord, actor_id)
            permissions = effective_permissions(session, actor_id)
            required = {
                PermissionKey.ITEM_READ,
                PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
                PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            }
            if "PAST_EXAM" in request.source_classes:
                required.add(PermissionKey.CONTENT_INTAKE_READ)
            if (
                actor is None
                or actor.status != "ACTIVE"
                or actor.deleted_at is not None
                or actor.must_change_password
                or not required.issubset(permissions)
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
            try:
                policy = self.retrieval.resolve_access_policy(
                    session, request.access_policy_revision_id, sha256=request.access_policy_sha256
                )
            except KnowledgeRetrievalServiceError as exc:
                raise InferenceTransferServiceError(
                    "INFERENCE_TRANSFER_METADATA_POLICY_INVALID"
                ) from exc
            roles = {
                role.role_key for _assignment, role in active_role_assignments(session, actor_id)
            }
            if (
                not roles.intersection(policy.allowed_requester_roles).intersection(
                    policy.answer_bearing_roles
                )
                or "ITEM_PREPARATION" not in policy.allowed_query_kinds
                or not set(request.source_classes).issubset(policy.allowed_source_classes)
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
            snapshot = session.get(KnowledgeGraphSnapshotRecord, request.graph_snapshot_revision_id)
            if snapshot is None or snapshot.state != "PUBLISHED":
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_METADATA_NOT_FOUND")
            if snapshot.snapshot_sha256 != request.expected_snapshot_sha256:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_METADATA_PIN_MISMATCH")
            corpus_revision = session.get(
                KnowledgeCorpusRevisionRecord, snapshot.corpus_revision_id
            )
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(
                    KnowledgeCorpusRecord.graph_id == snapshot.graph_id
                )
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or corpus.graph_id != snapshot.graph_id
                or corpus_revision is None
                or corpus_revision.state != "PUBLISHED"
                or corpus_revision.corpus_id != corpus.corpus_id
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_METADATA_NOT_FOUND")
            try:
                graph = self.retrieval.resolve_snapshot_pointer(
                    session, request.graph_snapshot_revision_id
                )
            except KnowledgeRetrievalServiceError as exc:
                raise InferenceTransferServiceError(
                    "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH"
                ) from exc
            if (
                graph.graph_id != snapshot.graph_id
                or graph.manifest_sha256 != snapshot.manifest_sha256
                or graph.graph_snapshot_revision_id != request.graph_snapshot_revision_id
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_METADATA_PIN_MISMATCH")
            body = {
                "schema_version": "inference-transfer-metadata-result/1.0",
                "request_sha256": request.request_sha256,
                "graph_snapshot": graph.model_dump(mode="json"),
                "snapshot_sha256": snapshot.snapshot_sha256,
                "access_policy_revision_id": policy.access_policy_revision_id,
                "access_policy_sha256": policy.content_sha256,
                "source_classes": request.source_classes,
            }
            result = InferenceTransferMetadataResolveResult.model_validate(
                body | {"result_sha256": content_sha256(body)}
            )
            validate_metadata_result(request, result)
            return result
