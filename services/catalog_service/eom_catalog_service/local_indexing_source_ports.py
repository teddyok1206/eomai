"""Owner-local read intent/port, with no user role or transferable source grant."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.local_indexing_mixed_policy import SupportedLocalIndexingAccessPolicy
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SegmentedLocalIndexingAccessPolicy,
)
from sqlalchemy.orm import Session

from eom_catalog_service.inference_transfer_scope import (
    InferenceTransferPopulationScope,
    require_item_revision_selection,
)

type LocalIndexingSourceErrorCode = Literal[
    "LOCAL_INDEXING_SOURCE_FORBIDDEN",
    "LOCAL_INDEXING_SOURCE_UNAVAILABLE",
    "LOCAL_INDEXING_SOURCE_SCOPE_INVALID",
]


class LocalIndexingSourceError(ValueError):
    def __init__(self, code: LocalIndexingSourceErrorCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LocalIndexingSourceReadIntent:
    """Bounded selection only. Authority always comes from the installed owner."""

    corpus_id: str
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str
    access_policy_sha256: str
    service_policy_revision_id: str
    service_policy_sha256: str
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    native_execution_policy_sha256: str
    resource_profile_sha256: str
    maximum_candidates: int = 1024
    analysis_run_ids: tuple[str, ...] = ()
    source_revision_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            require_item_revision_selection(self.source_revision_ids)
        except ValueError:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID") from None
        if (
            type(self.corpus_id) is not str
            or re.fullmatch(r"corpus_[0-9a-f]{32}", self.corpus_id) is None
            or type(self.access_policy_revision_id) is not str
            or re.fullmatch(r"accessrev_[0-9a-f]{32}", self.access_policy_revision_id) is None
            or type(self.service_policy_revision_id) is not str
            or re.fullmatch(r"accessrev_[0-9a-f]{32}", self.service_policy_revision_id) is None
            or any(
                type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                for value in (
                    self.access_policy_sha256,
                    self.service_policy_sha256,
                    self.native_execution_policy_sha256,
                    self.resource_profile_sha256,
                )
            )
            or type(self.maximum_candidates) is not int
            or not 1 <= self.maximum_candidates <= 1024
            or type(self.source_classes) is not tuple
            or not self.source_classes
            or any(type(value) is not str for value in self.source_classes)
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or not set(self.source_classes).issubset({"APPROVED_ITEM", "PAST_EXAM"})
            or type(self.analysis_run_ids) is not tuple
            or any(
                type(value) is not str or re.fullmatch(r"analysisrun_[0-9a-f]{32}", value) is None
                for value in self.analysis_run_ids
            )
            or self.analysis_run_ids != tuple(sorted(set(self.analysis_run_ids)))
            or len(self.analysis_run_ids) > self.maximum_candidates
            or len(self.source_revision_ids) > self.maximum_candidates
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        if type(self.namespace) not in (EmbeddingIndexNamespace, MixedEmbeddingIndexNamespace):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        for name, model in (
            ("graph_snapshot", KnowledgeGraphSnapshotPointer),
            ("namespace", type(self.namespace)),
            ("space", EmbeddingSpace),
            ("recipe", ExperimentViewRecipe),
        ):
            value = getattr(self, name)
            if type(value) is not model:
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
            try:
                checked = model.model_validate(raw_similarity_contract_value(value))
            except ValueError:
                raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID") from None
            object.__setattr__(self, name, checked)
        if (
            self.namespace.space_sha256 != self.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.space.purpose != "DOCUMENT"
            or self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")

    @property
    def population_scope(self) -> InferenceTransferPopulationScope:
        return InferenceTransferPopulationScope(self.namespace.population_scope)


class LocalIndexingSourceAuthorization(Protocol):
    """Trusted application composition only; never parsed from a worker/API message."""

    def authorize_scope(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
    ) -> SupportedLocalIndexingAccessPolicy:
        """Fence actual runtime/DB identity and resolve the exact current data policy."""
        ...


class SegmentedLocalIndexingSourceAuthorization(Protocol):
    """Same installed Catalog gate, but only for the explicit 1.3 page policy."""

    def authorize_segmented_scope(
        self,
        session: Session,
        intent: LocalIndexingSourceReadIntent,
    ) -> SegmentedLocalIndexingAccessPolicy:
        """No page, cursor or policy document supplied by a worker is authority."""
        ...
