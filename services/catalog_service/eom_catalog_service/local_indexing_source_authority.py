"""Catalog's narrow service data gate, reusing the official policy/Graph owners."""

from __future__ import annotations

from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    LocalIndexingPolicyContractError,
    require_local_indexing_source_policy,
)
from eom_identity_service import LocalIndexingFenceError, PostgresLocalIndexingServiceFence
from eom_operator_identity import local_indexing_service_reference
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceError,
    LocalIndexingSourceErrorCode,
    LocalIndexingSourceReadIntent,
)


class CatalogLocalIndexingSourceAuthority:
    """Installed owner composition, never a default SYSTEM/ADMIN or DTO authority."""

    def __init__(
        self,
        retrieval: KnowledgeRetrievalApplicationService,
        service_fence: PostgresLocalIndexingServiceFence,
    ) -> None:
        if type(service_fence) is not PostgresLocalIndexingServiceFence:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        self.retrieval, self.service_fence = retrieval, service_fence

    def _current_policy(
        self, session: Session, revision_id: str, sha256: str
    ) -> LocalIndexingAccessPolicy:
        identity = self.service_fence.fence_current_service(session)
        policy = self.retrieval.resolve_local_indexing_access_policy(
            session, revision_id, sha256=sha256
        )
        source_policy = self.retrieval.resolve_access_policy(
            session,
            policy.source_access_policy_revision_id,
            sha256=policy.source_access_policy_sha256,
        )
        require_local_indexing_source_policy(policy, source_policy)
        if (
            policy.service != local_indexing_service_reference(identity)
            or policy.runtime_configuration_sha256 != self.service_fence.pin.configuration_sha256
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        return policy

    def current_graph(
        self, session: Session, revision_id: str, sha256: str
    ) -> tuple[LocalIndexingAccessPolicy, KnowledgeGraphSnapshotPointer | None]:
        """Authenticate before discovering a head; saved work never calls latest."""
        try:
            policy = self._current_policy(session, revision_id, sha256)
            corpus = session.scalar(
                select(KnowledgeCorpusRecord)
                .where(KnowledgeCorpusRecord.corpus_id == policy.corpus_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or corpus.graph_id != policy.graph_id
            ):
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
            graph = (
                self.retrieval.resolve_snapshot_pointer(
                    session, corpus.current_graph_snapshot_revision_id
                )
                if corpus.current_graph_snapshot_revision_id is not None
                else None
            )
            self.service_fence.fence_current_service(session)
            return policy, graph
        except LocalIndexingSourceError:
            raise
        except LocalIndexingPolicyContractError:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN") from None
        except LocalIndexingFenceError as error:
            code: LocalIndexingSourceErrorCode = (
                "LOCAL_INDEXING_SOURCE_FORBIDDEN"
                if error.code == "LOCAL_INDEXING_FENCE_FORBIDDEN"
                else "LOCAL_INDEXING_SOURCE_UNAVAILABLE"
            )
            raise LocalIndexingSourceError(code) from None
        except (KnowledgeRetrievalServiceError, SQLAlchemyError, ValueError, TypeError, KeyError):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE") from None

    def authorize_scope(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
    ) -> LocalIndexingAccessPolicy:
        if type(intent) is not LocalIndexingSourceReadIntent:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        try:
            intent.__post_init__()
            try:
                policy = self._current_policy(
                    session, intent.service_policy_revision_id, intent.service_policy_sha256
                )
            except LocalIndexingPolicyContractError:
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN") from None
            if (
                policy.source_access_policy_revision_id != intent.access_policy_revision_id
                or policy.source_access_policy_sha256 != intent.access_policy_sha256
                or intent.corpus_id != policy.corpus_id
                or intent.graph_snapshot.graph_id != policy.graph_id
                or intent.namespace not in policy.namespaces
                or intent.space != policy.space
                or intent.recipe != policy.recipe
                or intent.native_execution_policy_sha256 != policy.native_execution_policy_sha256
                or intent.resource_profile_sha256 != policy.resource_profile_sha256
                or not set(intent.source_classes).issubset(policy.source_classes)
                or intent.maximum_candidates > policy.maximum_sources
            ):
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
            corpus = session.scalar(
                select(KnowledgeCorpusRecord)
                .where(KnowledgeCorpusRecord.corpus_id == intent.corpus_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            publication = session.scalar(
                select(KnowledgeGraphPublicationRecord)
                .where(
                    KnowledgeGraphPublicationRecord.corpus_id == intent.corpus_id,
                    KnowledgeGraphPublicationRecord.graph_snapshot_revision_id
                    == intent.graph_snapshot.graph_snapshot_revision_id,
                )
                .execution_options(populate_existing=True)
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or corpus.graph_id != policy.graph_id
                or publication is None
                or self.retrieval.resolve_snapshot_pointer(
                    session,
                    intent.graph_snapshot.graph_snapshot_revision_id,
                )
                != intent.graph_snapshot
            ):
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
            return policy
        except LocalIndexingSourceError:
            raise
        except LocalIndexingFenceError as error:
            code: LocalIndexingSourceErrorCode = (
                "LOCAL_INDEXING_SOURCE_FORBIDDEN"
                if error.code == ("LOCAL_INDEXING_FENCE_FORBIDDEN")
                else "LOCAL_INDEXING_SOURCE_UNAVAILABLE"
            )
            raise LocalIndexingSourceError(code) from None
        except (KnowledgeRetrievalServiceError, SQLAlchemyError, ValueError, TypeError, KeyError):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE") from None
