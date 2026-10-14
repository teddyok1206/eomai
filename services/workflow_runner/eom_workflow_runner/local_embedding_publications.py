"""Publication adapters bound to immutable original code provenance; no authority cache."""

from dataclasses import dataclass

from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.native_embedding_coordinator import NativeArtifactProducerIdentity


@dataclass(frozen=True, slots=True)
class NativeEmbeddingPublications:
    """Same original code provenance for every immutable publication across recovery."""

    controls: LocalEmbeddingControlArtifactPublisher
    artifacts: EmbeddingArtifactStore
    completions: NativeEmbeddingCompletionPublisher


def native_publication_identity(value: NativeArtifactProducerIdentity) -> ControlFileSetIdentity:
    return ControlFileSetIdentity(value.job_id, value.artifact_id, value.artifact_revision_id)


def new_native_artifact_producer() -> NativeArtifactProducerIdentity:
    """Allocation only; the current owner separately authorizes a publication."""
    return NativeArtifactProducerIdentity(
        job_id=new_job_id(),
        artifact_id=new_logical_artifact_id(),
        artifact_revision_id=new_revision_id(),
    )


def native_embedding_publications(
    publisher: ControlFileSetPublisher, source_commit: str
) -> NativeEmbeddingPublications:
    return NativeEmbeddingPublications(
        LocalEmbeddingControlArtifactPublisher(publisher, source_commit=source_commit),
        EmbeddingArtifactStore(publisher, source_commit=source_commit),
        NativeEmbeddingCompletionPublisher(publisher, source_commit=source_commit),
    )
