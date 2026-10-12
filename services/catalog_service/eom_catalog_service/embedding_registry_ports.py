"""Owner-local bounded values and the official-source/Artifact verification seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingSpace,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentViewRecipe,
    PopulationSource,
    StagedExperimentEntry,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow


class EmbeddingRegistryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryCaller:
    """Captured by the authentication owner, never parsed from a worker/request DTO.

    Identity possession is not a grant; the verification owner checks current
    actual operator permissions. Background service identity is not supported here.
    """

    operator_id: str


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingRegistration:
    corpus_id: str
    index: EmbeddingIndexManifest
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None
    sources: tuple[PopulationSource, ...]
    entries: tuple[StagedExperimentEntry, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryLookup:
    """Internal pinned scope; not a public wire schema or authority grant."""

    corpus_id: str
    namespace: EmbeddingIndexNamespace
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str
    policy_sha256: str
    maximum_sources: int = 1024


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingLookup:
    corpus_id: str
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    sources: tuple[PopulationSource, ...]
    entries: tuple[StagedExperimentEntry, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingBindingLookupKey:
    item_revision_id: str
    graph_snapshot_revision_id: str
    policy_revision_id: str
    recipe_sha256: str
    view: str
    projection_version: str
    base_analysis_run_id: str
    profile_revision_id: str
    solution_analysis_run_id: str
    encoding_sha256: str

    def columns(self) -> tuple[str, ...]:
        return (
            self.item_revision_id,
            self.graph_snapshot_revision_id,
            self.policy_revision_id,
            self.recipe_sha256,
            self.view,
            self.projection_version,
            self.base_analysis_run_id,
            self.profile_revision_id,
            self.solution_analysis_run_id,
            self.encoding_sha256,
        )


@dataclass(frozen=True, slots=True)
class EmbeddingBindingOrigin:
    binding_sha256: str
    manifest: ArtifactMemberPointer


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingBindingOrigin:
    origin: EmbeddingBindingOrigin
    binding: EmbeddingSourceBinding


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingReferences:
    origins: tuple[ResolvedEmbeddingBindingOrigin, ...]
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]


@dataclass(frozen=True, slots=True)
class MissingEmbeddingBindings:
    missing: tuple[EmbeddingBindingLookupKey, ...]
    reusable_rows: tuple[RegisteredEmbeddingRow, ...]
    eligible_source_count: int
    available_view_count: int


class EmbeddingRegistryVerificationPort(Protocol):
    """Trusted Catalog owner adapter, deliberately not installed/composed yet.

    Each method binds this authenticated caller and exact immutable intent. It
    must use the official Graph/source/report resolution boundary, check current
    actual permissions, approved lifecycle/accepted analysis, committed approved
    Artifact/revision, schema/media/size/raw hashes and numeric shard integrity.
    Perform required reauthorization under this same Catalog transaction; use
    appropriate source/authority row locking so a concurrent revocation cannot
    race verification against metadata commit. Never accept DTO role/approval claims.
    """

    def authorize_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
    ) -> None:
        """Authenticate/currently authorize this exact intent before any registry lookup.

        Read/lock only. A successful call is not an exported grant or a substitute
        for source/member validation in the subsequent capture/reference methods.
        """
        ...

    def resolve_registration(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        command: RegisterEmbeddingIndexCommand,
    ) -> ResolvedEmbeddingRegistration: ...

    def resolve_lookup(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        query: EmbeddingRegistryLookup,
    ) -> ResolvedEmbeddingLookup: ...

    def verify_registered_references(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        rows: tuple[RegisteredEmbeddingRow, ...],
        origins: tuple[EmbeddingBindingOrigin, ...],
    ) -> ResolvedEmbeddingReferences:
        """Reauthorize and resolve retained canonical references, including historical origins.

        Return exactly one full binding for each requested origin and its exact
        unique sorted shard closure. Never repeat full manifests per binding.
        Row resolution also verifies each requested row's same-file-set shard/
        binary and exact encoding, including rows with no registered binding yet;
        such row-only shards are verified internally, not extra returned pointers.
        No result or boolean is transferable authority outside this transaction.
        """
        ...
