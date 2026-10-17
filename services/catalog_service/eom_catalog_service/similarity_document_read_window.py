"""One root-local immutable decode window shared by official DOCUMENT read adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryActor
    from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
        InferenceTransferSessionCapture,
    )
    from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext


@dataclass(frozen=True, slots=True)
class SimilarityDocumentReadWindow:
    """Not a current authority/membership cache or a transferable read capability."""

    session: Session
    transaction: object
    caller: EmbeddingRegistryActor
    reader: PinnedArtifactReadContext
    capture: InferenceTransferSessionCapture
    source_revision_ids: tuple[str, ...] = ()
