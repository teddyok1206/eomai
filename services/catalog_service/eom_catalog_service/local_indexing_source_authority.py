"""Catalog's narrow service data gate, reusing the official policy/Graph owners."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    SupportedLocalIndexingAccessPolicy,
)
from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    LocalIndexingPolicyContractError,
    require_local_indexing_source_policy,
)
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SegmentedLocalIndexingAccessPolicy,
)
from eom_identity_service import LocalIndexingFenceError, PostgresLocalIndexingServiceFence
from eom_operator_identity import LocalIndexingServiceIdentity, local_indexing_service_reference
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

type _IndexingPolicy = SupportedLocalIndexingAccessPolicy | SegmentedLocalIndexingAccessPolicy


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
    ) -> SupportedLocalIndexingAccessPolicy:
        identity = self.service_fence.fence_current_service(session)
        policy = self.retrieval.resolve_local_indexing_access_policy(
            session, revision_id, sha256=sha256
        )
        if type(policy) not in (LocalIndexingAccessPolicy, LocalIndexingMixedAccessPolicy):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        self._verify_source_policy(session, policy, identity)
        return policy

    def _current_segmented_policy(
        self, session: Session, revision_id: str, sha256: str
    ) -> SegmentedLocalIndexingAccessPolicy:
        identity = self.service_fence.fence_current_service(session)
        policy = self.retrieval.resolve_segmented_local_indexing_access_policy(
            session, revision_id, sha256=sha256
        )
        if type(policy) is not SegmentedLocalIndexingAccessPolicy:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        self._verify_source_policy(session, policy, identity)
        return policy

    def _verify_source_policy(
        self,
        session: Session,
        policy: _IndexingPolicy,
        identity: LocalIndexingServiceIdentity,
    ) -> None:
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

    def current_graph(
        self, session: Session, revision_id: str, sha256: str
    ) -> tuple[SupportedLocalIndexingAccessPolicy, KnowledgeGraphSnapshotPointer | None]:
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
    ) -> SupportedLocalIndexingAccessPolicy:
        policy = self._authorize_with_policy(session, intent, self._current_policy)
        if type(policy) not in (LocalIndexingAccessPolicy, LocalIndexingMixedAccessPolicy):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return cast(SupportedLocalIndexingAccessPolicy, policy)

    def authorize_segmented_scope(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
    ) -> SegmentedLocalIndexingAccessPolicy:
        """Explicit 1.3 page grant; callers must still prove the whole population."""
        policy = self._authorize_with_policy(session, intent, self._current_segmented_policy)
        if type(policy) is not SegmentedLocalIndexingAccessPolicy:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return policy

    def _authorize_with_policy(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
        policy_reader: Callable[[Session, str, str], _IndexingPolicy],
    ) -> _IndexingPolicy:
        if type(intent) is not LocalIndexingSourceReadIntent:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        try:
            intent.__post_init__()
            try:
                policy = policy_reader(
                    session, intent.service_policy_revision_id, intent.service_policy_sha256
                )
            except LocalIndexingPolicyContractError:
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN") from None
            page_cap = (
                policy.maximum_page_sources
                if isinstance(policy, SegmentedLocalIndexingAccessPolicy)
                else policy.maximum_sources
            )
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
                or intent.maximum_candidates > page_cap
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
