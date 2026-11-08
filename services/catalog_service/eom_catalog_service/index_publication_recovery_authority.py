"""Exact retired publication reads under explicit schema-owner maintenance authority.

This is not a runtime service capture. The caller's Workflow owner fences the
one original, already-computed request in each retained SQL root.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_operator_identity import LocalIndexingServiceReference
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
)

_RELEASE_METADATA = frozenset(
    {
        "access_policy_revision_id",
        "service",
        "runtime_configuration_sha256",
        "native_execution_policy_sha256",
        "created_at",
        "content_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class IndexPublicationRecoveryAuthority:
    """Application-local selection and mandatory current maintenance fence.

    The historical service is an audit subject, never an impersonated principal.
    This adapter cannot discover a head or authorize a different Graph/policy.
    """

    original_service: LocalIndexingServiceReference
    current_service: LocalIndexingServiceReference
    original_policy_revision_id: str
    original_policy_sha256: str
    current_policy_revision_id: str
    current_policy_sha256: str
    graph: KnowledgeGraphSnapshotPointer
    fence: Callable[[Session], None]

    def policy(
        self,
        session: Session,
        retrieval: KnowledgeRetrievalApplicationService,
        revision_id: str,
        sha256: str,
    ) -> PublicSolutionIndexingAccessPolicy:
        if os.getresuid() != (0, 0, 0):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        self.fence(session)
        if (revision_id, sha256) != (
            self.original_policy_revision_id,
            self.original_policy_sha256,
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        original = retrieval.resolve_local_indexing_access_policy(
            session, revision_id, sha256=sha256
        )
        current = retrieval.resolve_local_indexing_access_policy(
            session, self.current_policy_revision_id, sha256=self.current_policy_sha256
        )
        if (
            type(original) is not PublicSolutionIndexingAccessPolicy
            or type(current) is not PublicSolutionIndexingAccessPolicy
            or original.service != self.original_service
            or current.service != self.current_service
            or original.service.service_id != current.service.service_id
            or original.service.service_revision_id == current.service.service_revision_id
            or original.model_dump(exclude=set(_RELEASE_METADATA))
            != current.model_dump(exclude=set(_RELEASE_METADATA))
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        return original

    def require_scope(self, intent: LocalIndexingSourceReadIntent) -> None:
        if intent.graph_snapshot != self.graph:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
