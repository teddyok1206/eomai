"""Owner-local bounded values and the official-source/Artifact verification seam."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingBinding,
    SupportedEmbeddingProfilePointer,
)
from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingEntry as SupportedEmbeddingEntry,
)
from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingIndex as SupportedEmbeddingIndex,
)
from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSpace,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    VIEWS,
    ExperimentView,
    ExperimentViewRecipe,
    PopulationSource,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.mixed_embedding_registry import (
    MixedEmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommandV2,
)
from eom_catalog_contracts.private_chat_query_basis import PrivateChatQueryBasis
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_embedding_registry import (
    RegisterPublicSolutionIndexCommand,
)
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityView
from eom_catalog_contracts.registered_public_solution_registry import (
    RegisterPublicSolutionIndexCommandV4,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_catalog_contracts.similarity_context import SimilarityContext, SimilarityViewSelection
from eom_catalog_contracts.similarity_context_v2 import SimilarityViewSelectionV2
from eom_catalog_contracts.similarity_materials import SimilarityReferenceMaterials
from eom_operator_identity import LocalIndexingServiceReference, local_indexing_service_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.inference_transfer_scope import require_item_revision_selection


class EmbeddingRegistryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EmbeddingPopulationTruncated(EmbeddingRegistryError):
    """Explicit bounded discovery only; never a generic identity/scope mismatch."""

    def __init__(self) -> None:
        super().__init__("EMBEDDING_REGISTRY_SCOPE_LIMIT")


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryCaller:
    """Captured by the authentication owner, never parsed from a worker/request DTO.

    Identity possession is not a grant; the verification owner checks current
    actual operator permissions. It is not a background service identity.
    """

    operator_id: str


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryServiceCaller:
    """Exact owner-local selection/audit only; actual runtime/data fences are mandatory."""

    service: LocalIndexingServiceReference


type EmbeddingRegistryActor = EmbeddingRegistryCaller | EmbeddingRegistryServiceCaller
type SupportedEmbeddingRegistrationCommand = (
    RegisterEmbeddingIndexCommand
    | RegisterEmbeddingIndexCommandV2
    | RegisterPublicSolutionIndexCommand
    | RegisterPublicSolutionIndexCommandV4
)

type AuthoringReferencePurpose = Literal["PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"]
AUTHORING_REFERENCE_PURPOSES: tuple[AuthoringReferencePurpose, ...] = (
    "PAST_EXAM_VARIATION",
    "ITEM_AUTHORING",
    "ITEM_REVIEW",
)


def validate_embedding_registry_actor(caller: EmbeddingRegistryActor) -> None:
    """Validate a closed small value, NOT authenticate or authorize an operation."""
    if type(caller) is EmbeddingRegistryCaller:
        if type(caller.operator_id) is str and re.fullmatch(
            r"operator_[0-9a-f]{32}", caller.operator_id
        ):
            return
    elif (
        type(caller) is EmbeddingRegistryServiceCaller
        and type(caller.service) is LocalIndexingServiceReference
    ):
        try:
            local_indexing_service_bytes(caller.service)
            return
        except ValueError:
            pass
    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CALLER_INVALID")


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryOwnerConfiguration:
    """Owner numerical/isolation configuration, never a source permission grant."""

    corpus_id: str
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace | PublicSolutionIndexNamespace
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe | PublicSolutionEmbeddingRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingRegistration:
    corpus_id: str
    index: SupportedEmbeddingIndex
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    previous: tuple[ArtifactMemberPointer, SupportedEmbeddingIndex] | None
    sources: tuple[PopulationSource, ...]
    entries: tuple[SupportedEmbeddingEntry, ...]
    truncated: bool = False
    base_analysis_run_ids: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryLookup:
    """Internal pinned scope; not a public wire schema or authority grant."""

    corpus_id: str
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace | PublicSolutionIndexNamespace
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str
    policy_sha256: str
    maximum_sources: int = 1024


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingLookup:
    corpus_id: str
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe | PublicSolutionEmbeddingRecipe
    sources: tuple[PopulationSource, ...]
    entries: tuple[SupportedEmbeddingEntry, ...]
    truncated: bool = False
    base_analysis_run_ids: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SelectedEmbeddingSources:
    """Native plan targets, NOT a full-population/coverage query or authority grant."""

    scope: EmbeddingRegistryLookup
    source_revision_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_item_revision_selection(self.source_revision_ids)
        if (
            type(self.scope) is not EmbeddingRegistryLookup
            or not self.source_revision_ids
            or len(self.source_revision_ids) > self.scope.maximum_sources
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")


@dataclass(frozen=True, slots=True)
class ReferenceQueryContextPreparation:
    """Initial owner-local selection only; never authority, wire input or replay state."""

    request_id: str
    selection: SelectedEmbeddingSources
    spaces: ReferenceQuerySpaces
    views: tuple[ExperimentView, ...]
    vector_mode: Literal["OPTIONAL", "REQUIRED"]
    top_k: int
    consumer_purpose: AuthoringReferencePurpose = "PAST_EXAM_VARIATION"

    def __post_init__(self) -> None:
        if (
            type(self.request_id) is not str
            or re.fullmatch(r"similarityrequest_[0-9a-f]{32}", self.request_id) is None
            or type(self.selection) is not SelectedEmbeddingSources
            or len(self.selection.source_revision_ids) != 1
            or type(self.views) is not tuple
            or not self.views
            or self.views != tuple(view for view in VIEWS if view in self.views)
            or self.vector_mode not in {"OPTIONAL", "REQUIRED"}
            or type(self.top_k) is not int
            or not 1 <= self.top_k <= 64
            or type(self.selection.scope.maximum_sources) is not int
            or not 1 <= self.selection.scope.maximum_sources <= 1024
            or type(self.consumer_purpose) is not str
            or self.consumer_purpose not in AUTHORING_REFERENCE_PURPOSES
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
        self.selection.__post_init__()
        spaces = ReferenceQuerySpaces.model_validate(raw_similarity_contract_value(self.spaces))
        object.__setattr__(self, "spaces", spaces)


@dataclass(frozen=True, slots=True)
class PrivateChatContextPreparation:
    """Initial owner-local pins, never Chat ownership, wire input or a replay grant."""

    request_id: str
    query_basis: PrivateChatQueryBasis
    scope: EmbeddingRegistryLookup
    spaces: ReferenceQuerySpaces
    top_k: int

    def __post_init__(self) -> None:
        if (
            type(self.request_id) is not str
            or re.fullmatch(r"similarityrequest_[0-9a-f]{32}", self.request_id) is None
            or type(self.scope) is not EmbeddingRegistryLookup
            or type(self.scope.namespace) is not EmbeddingIndexNamespace
            or self.scope.namespace.view != "CONTENT_ONLY"
            or type(self.scope.maximum_sources) is not int
            or not 1 <= self.scope.maximum_sources <= 1024
            or type(self.top_k) is not int
            or not 1 <= self.top_k <= 64
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
        try:
            object.__setattr__(
                self,
                "query_basis",
                PrivateChatQueryBasis.model_validate(
                    raw_similarity_contract_value(self.query_basis)
                ),
            )
            object.__setattr__(
                self,
                "spaces",
                ReferenceQuerySpaces.model_validate(raw_similarity_contract_value(self.spaces)),
            )
        except (ValueError, TypeError, SchemaError):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID") from None


class SimilarityMaterialsReadPort(Protocol):
    """Existing selected-source owner integration, not the DB-independent composer port."""

    def read_similarity_materials_in_session(
        self, session: Session, caller: EmbeddingRegistryCaller, context: SimilarityContext
    ) -> SimilarityReferenceMaterials: ...


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryRead:
    """Owner-local exact immutable selection, never a wire query or authority grant."""

    scope: EmbeddingRegistryLookup
    selection: (
        SimilarityViewSelection
        | SimilarityViewSelectionV2
        | PublicSolutionSimilarityView
        | PublicSolutionSimilarityViewV4
    )


@dataclass(frozen=True, slots=True)
class RegisteredEmbeddingIndexRead:
    """Internal registered metadata; historical counts never become disclosed coverage."""

    corpus_id: str
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace | PublicSolutionIndexNamespace
    index_id: str
    index_revision_id: str
    index_manifest: ArtifactMemberPointer
    index_sha256: str
    graph_snapshot_revision_id: str
    policy_revision_id: str
    policy_sha256: str
    binding_count: int
    binding_set_sha256: str


@dataclass(frozen=True, slots=True)
class AuthorizedEmbeddingReadProfile:
    source_item_revision_id: str
    profile: SupportedEmbeddingProfilePointer


@dataclass(frozen=True, slots=True)
class MaterializedEmbeddingReadRow:
    """Owner-local decoded row at the explicit numeric read boundary, not a wire/DB value.

    The existing owner codec verifies finite/shape/raw SHA/unit norm before producing
    this value. It is neither serialized as JSON nor normalized to conceal corruption.
    """

    row: RegisteredEmbeddingRow
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ResolvedPinnedEmbeddingIndex:
    """Only the current authorized population and selected rows, no whole historical index."""

    intent: EmbeddingRegistryRead
    sources: tuple[PopulationSource, ...]
    profiles: tuple[AuthorizedEmbeddingReadProfile, ...]
    bindings: tuple[SupportedEmbeddingBinding, ...]
    numerical_rows: tuple[MaterializedEmbeddingReadRow, ...]

    @property
    def authorized_source_count(self) -> int:
        return len(self.sources)

    @property
    def accepted_profile_count(self) -> int:
        return len(self.profiles)

    @property
    def missing_report_count(self) -> int:
        return len(self.sources) - len(self.profiles)

    @property
    def available_binding_count(self) -> int:
        return len(self.bindings)


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
class RegisteredReviewEmbeddingBindingLookupKey:
    """Real accepted base and REVIEW association; no nullable solution-run placeholder."""

    item_revision_id: str
    graph_snapshot_revision_id: str
    policy_revision_id: str
    recipe_sha256: str
    view: str
    projection_version: str
    base_analysis_run_id: str
    profile_revision_id: str
    encoding_sha256: str
    review_job_id: str
    review_evidence_sha256: str

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
            self.encoding_sha256,
            self.review_job_id,
            self.review_evidence_sha256,
        )


@dataclass(frozen=True, slots=True)
class PublicSolutionEmbeddingBindingLookupKey:
    item_revision_id: str
    graph_snapshot_revision_id: str
    policy_revision_id: str
    recipe_sha256: str
    view: str
    projection_version: str
    base_analysis_run_id: str
    profile_revision_id: str
    encoding_sha256: str
    solution_pointer_sha256: str

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
            self.encoding_sha256,
            self.solution_pointer_sha256,
        )


type SupportedEmbeddingBindingLookupKey = (
    EmbeddingBindingLookupKey
    | RegisteredReviewEmbeddingBindingLookupKey
    | PublicSolutionEmbeddingBindingLookupKey
)


def embedding_binding_lookup_sort_key(key: SupportedEmbeddingBindingLookupKey) -> tuple[str, ...]:
    """Stable cross-family ordering, never cross-dataclass comparison or NULL sorting."""
    if type(key) not in {
        EmbeddingBindingLookupKey,
        RegisteredReviewEmbeddingBindingLookupKey,
        PublicSolutionEmbeddingBindingLookupKey,
    } or any(type(value) is not str or not value for value in key.columns()):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
    if type(key) is EmbeddingBindingLookupKey:
        return ("ACCEPTED_SOLUTION_ANALYSIS", *key.columns())
    if type(key) is RegisteredReviewEmbeddingBindingLookupKey:
        return ("REGISTERED_ITEM_REVIEW_SOLUTION", *key.columns())
    if type(key) is PublicSolutionEmbeddingBindingLookupKey:
        return ("PUBLIC_SOLUTION_REPORT", *key.columns())
    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")


@dataclass(frozen=True, slots=True)
class EmbeddingBindingOrigin:
    binding_sha256: str
    manifest: ArtifactMemberPointer


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingBindingOrigin:
    origin: EmbeddingBindingOrigin
    binding: SupportedEmbeddingBinding


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingReferences:
    origins: tuple[ResolvedEmbeddingBindingOrigin, ...]
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]


@dataclass(frozen=True, slots=True)
class MissingEmbeddingBindings:
    missing: tuple[SupportedEmbeddingBindingLookupKey, ...]
    reusable_rows: tuple[RegisteredEmbeddingRow, ...]
    eligible_source_count: int
    available_view_count: int


@dataclass(frozen=True, slots=True)
class PreparedEmbeddingBindingLookup:
    """One current-root materialization for planning, never a transferable grant."""

    observation: MissingEmbeddingBindings
    resolved: ResolvedEmbeddingLookup
    bindings: tuple[SupportedEmbeddingBinding, ...]


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
        caller: EmbeddingRegistryActor,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
    ) -> None:
        """Authenticate/currently authorize this exact intent before any registry lookup.

        Read/lock only. A successful call is not an exported grant or a substitute
        for source/member validation in the subsequent capture/reference methods.
        """
        ...

    def resolve_registration(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        command: SupportedEmbeddingRegistrationCommand,
    ) -> ResolvedEmbeddingRegistration: ...

    def resolve_lookup(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        query: EmbeddingRegistryLookup,
    ) -> ResolvedEmbeddingLookup: ...

    def resolve_pinned_read(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: EmbeddingRegistryRead,
        registered: RegisteredEmbeddingIndexRead,
    ) -> ResolvedPinnedEmbeddingIndex:
        """Resolve the exact committed index and current eligible subset under this owner.

        Reuse actual read authorization, official source/report capture and the
        existing immutable member/numeric validator. No historical out-of-scope
        source, global index count or unselected numeric row may escape this call.
        """
        ...

    def verify_registered_references(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        rows: tuple[RegisteredEmbeddingRow, ...],
        origins: tuple[EmbeddingBindingOrigin, ...],
    ) -> ResolvedEmbeddingReferences:
        """Reauthorize and resolve retained canonical references, including historical origins.

        Return exactly one full binding for each requested immutable ledger origin
        and its exact unique sorted shard closure. Reconstruct current bindings,
        compare all canonical ledger scalars/origin pointers, and resolve unchanged
        physical origin bytes; no full historical index DTO reinterpretation.
        Row resolution also verifies each requested row's same-file-set shard/
        binary and exact encoding, including rows with no registered binding yet;
        such row-only shards are verified internally, not extra returned pointers.
        No result or boolean is transferable authority outside this transaction.
        """
        ...
