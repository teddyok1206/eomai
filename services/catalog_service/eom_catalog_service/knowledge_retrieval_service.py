"""Deterministic bounded retrieval and immutable Evidence Bundle publication."""

from __future__ import annotations

import json
import re
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import get_ident
from typing import Any, Literal

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    ContentIntakeKnowledgeSourceV2,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CurriculumRetrievalScope,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationRetrievalAccessPolicy,
    EducationRetrievalRequestV2,
    EvidenceBudget,
    EvidenceBundleManifestV2,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundleManifestV5,
    EvidenceBundleMaterialsV2,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
    EvidenceBundlePublicationResultV5,
    EvidenceEntryV2,
    EvidenceEntryV3,
    EvidenceEntryV4,
    EvidenceEntryV5,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisSourceV3,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotPointer,
    validate_contract,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.local_indexing_mixed_policy import (
    SupportedLocalIndexingAccessPolicy,
    parse_supported_local_indexing_access_policy,
)
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SegmentedLocalIndexingAccessPolicy,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, Select, distinct, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.artifacts import (
    CatalogArtifact,
    CatalogArtifactReader,
    CatalogArtifactService,
    CatalogModelArtifactReader,
)
from eom_catalog_service.inference_transfer_scope import (
    InferenceTransferPopulationScope,
    require_item_revision_selection,
)
from eom_catalog_service.knowledge_analysis_sources import (
    EducationalDocumentSourceResolutionCache,
    ItemSourceReadRelations,
    KnowledgeAnalysisSourceError,
    read_item_source_relations,
    resolve_content_intake_source,
    resolve_educational_document_source,
    resolve_historically_approved_item_source,
)
from eom_catalog_service.knowledge_graph_models import (
    AssessmentItemOccurrenceReferenceRecord,
    CurriculumUnitClosureRecord,
    CurriculumUnitRecord,
    EducationRetrievalAccessPolicyRevisionRecord,
    EducationRetrievalRequestRecord,
    EvidenceBundleEntryRecord,
    EvidenceBundleRecord,
    EvidenceBundleRevisionRecord,
    ItemElementReferenceRecord,
    KnowledgeCorpusRecord,
    KnowledgeEdgeRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeNodeTermRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceAuthorization,
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
    SegmentedLocalIndexingSourceAuthorization,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_source_provenance import PastExamSourceResolutionCache
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.solution_evidence_resolution import (
    ResolvedSolutionEvidence,
    SolutionEvidenceResolutionError,
    resolve_solution_evidence_by_base_run,
)

KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.0"
KNOWLEDGE_RETRIEVAL_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/2.0",
            "evidence-bundle-publication-result/1.0",
        ],
    }
)


def _exact_target_placement_node_id(
    session: Session,
    *,
    snapshot_id: str,
    item_revision_id: str,
) -> str:
    """Resolve the one Graph placement that gives a past-exam Item its source identity."""

    reference = session.scalar(
        select(AssessmentItemOccurrenceReferenceRecord).where(
            AssessmentItemOccurrenceReferenceRecord.graph_snapshot_revision_id == snapshot_id,
            AssessmentItemOccurrenceReferenceRecord.item_revision_id == item_revision_id,
        )
    )
    if reference is None:
        raise KnowledgeRetrievalServiceError(
            "KNOWLEDGE_RETRIEVAL_ITEM_PLACEMENT_MISSING",
            "target past-exam Item Revision has no pinned Graph placement",
        )
    return str(reference.placement_node_id)


KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.1"
KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/3.0",
            "evidence-bundle-publication-result/3.0",
        ],
    }
)
KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.2"
KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/4.0",
            "evidence-bundle-publication-result/4.0",
        ],
    }
)
KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.3"
KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/5.0",
            "evidence-bundle-publication-result/5.0",
            "knowledge-analysis-result/10.0",
            "knowledge-analysis-proposal-receipt/9.0",
            "knowledge-analysis-solution-report/1.0",
        ],
    }
)
type EvidenceEntryContract = EvidenceEntryV2 | EvidenceEntryV3 | EvidenceEntryV4 | EvidenceEntryV5
type EvidenceManifestContract = (
    EvidenceBundleManifestV2
    | EvidenceBundleManifestV3
    | EvidenceBundleManifestV4
    | EvidenceBundleManifestV5
)
type EvidencePublicationContract = (
    EvidenceBundlePublicationResult
    | EvidenceBundlePublicationResultV3
    | EvidenceBundlePublicationResultV4
    | EvidenceBundlePublicationResultV5
)
type ItemProductionEvidencePublicationContract = (
    EvidenceBundlePublicationResultV2
    | EvidenceBundlePublicationResultV3
    | EvidenceBundlePublicationResultV4
    | EvidenceBundlePublicationResultV5
)
MAX_RETRIEVAL_CANDIDATES = 256
MAX_POINTER_ROWS_PER_NODE = 32
MAX_CONTEXT_BYTES = 64 * 1024
MAX_REQUEST_ARTIFACT_CACHE_BYTES = 64 * 1024 * 1024
# Retention bound only: members beyond it still receive the full original validation.
MAX_REQUEST_ARTIFACT_CACHE_MEMBERS = 4096


class KnowledgeRetrievalServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _rank_lexical_seed_rows(
    rows: tuple[tuple[str, str, int], ...], *, limit: int
) -> tuple[tuple[str, int], ...]:
    """Rank lexical seeds by bounded inverse-frequency evidence, then stable identity."""
    term_frequencies_by_node: dict[str, dict[str, int]] = {}
    for term, node_id, term_frequency in rows:
        node_terms = term_frequencies_by_node.setdefault(node_id, {})
        node_terms[term] = min(node_terms.get(term, term_frequency), term_frequency)
    ranked = (
        (
            node_id,
            min(
                1000,
                500
                + sum(
                    max(1, 1000 // max(term_frequency, 1))
                    for term_frequency in frequencies.values()
                ),
            ),
        )
        for node_id, frequencies in term_frequencies_by_node.items()
    )
    return tuple(sorted(ranked, key=lambda item: (-item[1], item[0]))[:limit])


def _bounded_seed_scores(seed_scores: dict[str, int], *, limit: int) -> dict[str, int]:
    """Keep the strongest deterministic seeds when the evidence budget is bounded."""
    return dict(sorted(seed_scores.items(), key=lambda item: (-item[1], item[0]))[:limit])


@dataclass(frozen=True)
class KnowledgeRetrievalCandidate:
    analysis_run_id: str
    source: (
        KnowledgeAnalysisSourceV3
        | EducationalDocumentKnowledgeSourceV4
        | ApprovedPastExamItemKnowledgeSourceV3
    )
    node_ids: tuple[str, ...]
    anchor_ids: tuple[str, ...]
    node_labels: tuple[str, ...]
    node_types: tuple[str, ...]
    relevance_milli: int
    answer_bearing: bool
    solution: ResolvedSolutionEvidence | None = None


# Keep the existing internal/test name; consumers use the supported public type.
_Candidate = KnowledgeRetrievalCandidate


@dataclass(frozen=True, slots=True)
class ReadOnlyKnowledgeSelection:
    request: EducationRetrievalRequestV2
    candidates: tuple[KnowledgeRetrievalCandidate, ...]


@dataclass(frozen=True, slots=True)
class ReadOnlyCandidatePoolScope:
    """Trusted application scope, never model-supplied authority or a V2 request.

    The actor and effective permission/role values are injected by the Catalog
    application use case. Candidate admission does not publish a retrieval or
    replace the released lexical/multihop retrieval algorithm.
    """

    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str
    access_policy_sha256: str
    requested_by: str
    requester_role: Literal["ADMIN", "EDITOR", "REVIEWER", "WORKER"]
    requester_permission_keys: tuple[str, ...]
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    evidence_budget: EvidenceBudget
    maximum_candidates: int = 1024
    analysis_run_ids: tuple[str, ...] = ()
    query_kind: Literal["ITEM_PREPARATION"] = "ITEM_PREPARATION"
    population_scope: InferenceTransferPopulationScope = (
        InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS
    )
    source_revision_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_item_revision_selection(self.source_revision_ids)
        if not isinstance(self.population_scope, InferenceTransferPopulationScope):
            raise ValueError("candidate pool population scope must be a typed value")
        if type(self.maximum_candidates) is not int or not 1 <= self.maximum_candidates <= 1024:
            raise ValueError("candidate pool limit must be between 1 and 1024")
        for values in (self.source_classes, self.requester_permission_keys):
            if not values or values != tuple(sorted(set(values))):
                raise ValueError("candidate pool authority/sources must be sorted and unique")
        if not set(self.source_classes).issubset({"APPROVED_ITEM", "PAST_EXAM"}):
            raise ValueError("candidate pool supports only approved Item source classes")
        if (
            self.analysis_run_ids != tuple(sorted(set(self.analysis_run_ids)))
            or len(self.analysis_run_ids) > self.maximum_candidates
            or len(self.source_revision_ids) > self.maximum_candidates
        ):
            raise ValueError("candidate pool exact analysis selection is invalid")


@dataclass(frozen=True, slots=True)
class ReadOnlyKnowledgeCandidatePool:
    graph_snapshot: KnowledgeGraphSnapshotPointer
    candidates: tuple[KnowledgeRetrievalCandidate, ...]
    truncated: bool


type _ResolvedKnowledgeSource = (
    KnowledgeAnalysisSourceV3
    | EducationalDocumentKnowledgeSourceV4
    | ApprovedPastExamItemKnowledgeSourceV3
)


@dataclass(frozen=True, order=True, slots=True)
class _ImmutableSourcePointerKey:
    """Identity needed to validate one Graph source member without implicit latest lookup."""

    graph_snapshot_revision_id: str
    analysis_run_id: str
    source_revision_id: str
    source_class: str
    source_artifact_id: str
    artifact_revision_id: str
    source_sha256: str
    member_path: str

    @classmethod
    def from_record(
        cls,
        graph_snapshot_revision_id: str,
        pointer: KnowledgeNodeSourcePointerRecord,
    ) -> _ImmutableSourcePointerKey:
        return cls(
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            analysis_run_id=pointer.analysis_run_id,
            source_revision_id=pointer.source_revision_id,
            source_class=pointer.source_class,
            source_artifact_id=pointer.source_artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            source_sha256=pointer.source_sha256,
            member_path=pointer.member_path,
        )


@dataclass(frozen=True, slots=True)
class _ArtifactMemberValidationKey:
    artifact_id: str
    artifact_revision_id: str
    member_path: str
    sha256: str
    media_type: str
    schema_ref: str
    max_bytes: int


class _RequestScopedArtifactValidationCache:
    """Reuse a completed exact immutable-member check only inside one retrieval request."""

    def __init__(self, delegate: CatalogArtifactReader) -> None:
        self._delegate = delegate
        self._member_bytes: dict[_ArtifactMemberValidationKey, bytes] = {}
        self._member_bytes_total = 0
        self._verified_members: set[_ArtifactMemberValidationKey] = set()

    @property
    def settings(self) -> CatalogSettings:
        """Preserve the immutable reader's storage boundary for nested pointer checks."""

        return self._delegate.settings

    @staticmethod
    def _key(
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> _ArtifactMemberValidationKey:
        return _ArtifactMemberValidationKey(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )

    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes:
        key = self._key(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )
        if key in self._member_bytes:
            return self._member_bytes[key]
        value = self._delegate.read_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )
        if len(self._verified_members) < MAX_REQUEST_ARTIFACT_CACHE_MEMBERS:
            self._verified_members.add(key)
        if (
            key in self._verified_members
            and self._member_bytes_total + len(value) <= MAX_REQUEST_ARTIFACT_CACHE_BYTES
        ):
            self._member_bytes[key] = value
            self._member_bytes_total += len(value)
            # The typed port asks for the exact size after a bounded provenance
            # read. An alias to the SAME bytes avoids another scalar-adapter IO;
            # it grants no broader bound and consumes the existing member budget.
            exact = replace(key, max_bytes=len(value))
            if exact not in self._verified_members and (
                len(self._verified_members) < MAX_REQUEST_ARTIFACT_CACHE_MEMBERS
            ):
                self._verified_members.add(exact)
                self._member_bytes[exact] = value
        return value

    def verify_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> None:
        key = self._key(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )
        if key in self._verified_members:
            return
        self._delegate.verify_member(
            artifact_id=artifact_id,
            revision_id=revision_id,
            member_path=member_path,
            sha256=sha256,
            media_type=media_type,
            schema_ref=schema_ref,
            max_bytes=max_bytes,
        )
        if len(self._verified_members) < MAX_REQUEST_ARTIFACT_CACHE_MEMBERS:
            self._verified_members.add(key)


class _RequestScopedModelArtifactValidationCache(_RequestScopedArtifactValidationCache):
    """Preserve an actual delegate capability, without inventing a scalar decode path."""

    def __init__(self, delegate: CatalogModelArtifactReader) -> None:
        super().__init__(delegate)
        self._model_delegate = delegate

    def read_model_member[Model: BaseModel](
        self,
        pointer: ArtifactMemberPointer,
        *,
        expected_bytes: int,
        decoder: Callable[[str, bytes], Model],
    ) -> Model:
        return self._model_delegate.read_model_member(
            pointer, expected_bytes=expected_bytes, decoder=decoder
        )


def _request_scoped_artifact_validation_cache(
    delegate: CatalogArtifactReader,
) -> _RequestScopedArtifactValidationCache:
    if isinstance(delegate, CatalogModelArtifactReader):
        return _RequestScopedModelArtifactValidationCache(delegate)
    return _RequestScopedArtifactValidationCache(delegate)


@dataclass(frozen=True, slots=True)
class _ReadOnlyKnowledgeReuseScope:
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str
    policy_sha256: str
    actor_id: str
    role: str
    permissions: tuple[str, ...]
    source_classes: tuple[str, ...]
    query_kind: str
    evidence_budget: tuple[int, ...]

    @classmethod
    def from_command(
        cls,
        command: CreateEvidenceBundleCommand | ReadOnlyCandidatePoolScope,
        *,
        graph_snapshot: KnowledgeGraphSnapshotPointer,
        policy_sha256: str,
    ) -> _ReadOnlyKnowledgeReuseScope:
        budget = command.evidence_budget
        return cls(
            graph_snapshot=graph_snapshot,
            policy_revision_id=command.access_policy_revision_id,
            policy_sha256=policy_sha256,
            actor_id=command.requested_by,
            role=command.requester_role,
            permissions=tuple(command.requester_permission_keys),
            source_classes=tuple(command.source_classes),
            query_kind=command.query_kind,
            evidence_budget=(
                budget.max_documents,
                budget.max_item_revisions,
                budget.max_graph_nodes,
                budget.max_claims,
                budget.max_context_tokens,
            ),
        )


def _active_root_transaction(session: Session) -> SessionTransaction:
    current = session.get_transaction()
    if current is None or not current.is_active or session.get_nested_transaction() is not None:
        raise KnowledgeRetrievalServiceError(
            "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID",
            "immutable read reuse requires one active root transaction",
        )
    return current


@dataclass(frozen=True, slots=True, eq=False)
class ReadOnlyKnowledgeReuseContext:
    """Opaque owner-local decoding reuse, never authorization or a durable cache.

    Create through the retrieval service inside the caller-owned read transaction.
    Each public call reauthorizes and reloads current source relations before using
    these bounded exact immutable member/provenance caches. No resolved-source or
    association/run maps, EducationalDocument values, or query ranking are shared.
    """

    _service: KnowledgeRetrievalApplicationService = field(repr=False)
    _reader: CatalogArtifactReader = field(repr=False)
    _session: Session = field(repr=False)
    _transaction: SessionTransaction = field(repr=False)
    _thread_id: int = field(repr=False)
    _scope: _ReadOnlyKnowledgeReuseScope = field(repr=False)
    _artifacts: _RequestScopedArtifactValidationCache = field(repr=False)
    _past_exam: PastExamSourceResolutionCache = field(repr=False)

    def _require_owner(
        self, service: KnowledgeRetrievalApplicationService, session: Session
    ) -> None:
        if (
            self._service is not service
            or self._reader is not service.artifacts
            or self._session is not session
            or self._thread_id != get_ident()
            or self._transaction is not _active_root_transaction(session)
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID",
                "immutable read reuse does not belong to the actual owner transaction",
            )

    def _require(
        self,
        service: KnowledgeRetrievalApplicationService,
        session: Session,
        command: CreateEvidenceBundleCommand | ReadOnlyCandidatePoolScope,
        *,
        graph_snapshot: KnowledgeGraphSnapshotPointer,
        policy_sha256: str,
    ) -> None:
        self._require_owner(service, session)
        if self._scope != _ReadOnlyKnowledgeReuseScope.from_command(
            command, graph_snapshot=graph_snapshot, policy_sha256=policy_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID",
                "immutable read reuse does not belong to the actual transaction and scope",
            )


@dataclass
class _SnapshotSourceResolutionCache:
    """One retrieval's immutable Graph association, run, and source-resolution indexes."""

    associations_by_run_id: dict[str, KnowledgeSnapshotAnalysisRecord]
    runs_by_id: dict[str, KnowledgeAnalysisRunRecord]
    artifacts: _RequestScopedArtifactValidationCache
    educational_documents: EducationalDocumentSourceResolutionCache = field(
        default_factory=EducationalDocumentSourceResolutionCache
    )
    past_exam_provenance: PastExamSourceResolutionCache = field(
        default_factory=PastExamSourceResolutionCache
    )
    item_relations: ItemSourceReadRelations | None = None
    declared_sources_by_run_id: dict[str, _ResolvedKnowledgeSource] = field(default_factory=dict)
    resolved_sources_by_run_id: dict[str, _ResolvedKnowledgeSource] = field(default_factory=dict)
    validated_sources_by_pointer: dict[_ImmutableSourcePointerKey, _ResolvedKnowledgeSource] = (
        field(default_factory=dict)
    )


def _typed_id(prefix: str, value: dict[str, object]) -> str:
    return prefix + content_sha256(value).removeprefix("sha256:")[:32]


def _utc_json(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _context_tokens(value: str) -> int:
    return max(1, (len(value.encode("utf-8")) + 1) // 2)


def _artifact_member_schema_ref(
    revision: ArtifactRevisionRecord,
    *,
    member_path: str,
    allowed: frozenset[str],
) -> str:
    files = revision.manifest.get("files")
    if not isinstance(files, list):
        raise KnowledgeRetrievalServiceError(
            "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
            "published Artifact manifest has no member inventory",
        )
    matches = [
        item for item in files if isinstance(item, dict) and item.get("file_name") == member_path
    ]
    if len(matches) != 1 or matches[0].get("schema_ref") not in allowed:
        raise KnowledgeRetrievalServiceError(
            "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
            "published Artifact member schema is incompatible",
        )
    return str(matches[0]["schema_ref"])


class KnowledgeRetrievalApplicationService:
    """Own one closed retrieval query and publish only immutable pointer-oriented output."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def read_released_access_policy(
        self, access_policy_revision_id: str
    ) -> EducationRetrievalAccessPolicy:
        """Resolve exact supported policy metadata, not permission or a query grant."""
        with self.sessions() as session:
            return self._policy(session, access_policy_revision_id)

    def create_read_only_reuse_context(
        self, session: Session, scope: ReadOnlyCandidatePoolScope
    ) -> ReadOnlyKnowledgeReuseContext:
        """Bind empty decoding caches, without granting or memoizing authority.

        The snapshot owner sets REPEATABLE READ / READ ONLY before calling this.
        The first and every subsequent public operation still resolves Graph and
        policy, authorizes the actual actor, and checks the bound values.
        """
        return ReadOnlyKnowledgeReuseContext(
            _service=self,
            _reader=self.artifacts,
            _session=session,
            _transaction=_active_root_transaction(session),
            _thread_id=get_ident(),
            _scope=_ReadOnlyKnowledgeReuseScope.from_command(
                scope,
                graph_snapshot=scope.graph_snapshot,
                policy_sha256=scope.access_policy_sha256,
            ),
            _artifacts=_request_scoped_artifact_validation_cache(self.artifacts),
            _past_exam=PastExamSourceResolutionCache(),
        )

    def create_item_production(
        self, command: CreateItemProductionEvidenceCommand
    ) -> ItemProductionEvidencePublicationContract:
        """Resolve a stable educational intent without accepting a raw snapshot control."""

        solution_evidence_required = (
            command.solution_evidence_requirement == "REQUIRE_ACCEPTED_SOLUTION_REPORT"
        )
        internal_key = "item-evidence:" + content_sha256(
            {"idempotency_key": command.idempotency_key}
        ).removeprefix("sha256:")
        with self.sessions() as session:
            existing = session.scalar(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key == internal_key
                )
            )
            if existing is not None:
                self._validate_item_production_replay(session, command, existing)
                revision = session.scalar(
                    select(EvidenceBundleRevisionRecord).where(
                        EvidenceBundleRevisionRecord.retrieval_request_id
                        == existing.retrieval_request_id
                    )
                )
                if revision is None:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                        "item production retrieval has no published Evidence Bundle",
                    )
                result = self._result_v2(session, existing, revision)
                self._require_solution_evidence_result(
                    result,
                    required=solution_evidence_required,
                )
                return result
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(
                    KnowledgeCorpusRecord.corpus_key == command.requirement.corpus_key
                )
            )
            snapshot = (
                session.get(KnowledgeGraphSnapshotRecord, corpus.current_graph_snapshot_revision_id)
                if corpus is not None and corpus.current_graph_snapshot_revision_id is not None
                else None
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or snapshot is None
                or snapshot.state != "PUBLISHED"
                or snapshot.graph_id != corpus.graph_id
            ):
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_CORPUS_UNAVAILABLE",
                    "requested knowledge corpus has no published current snapshot",
                )
            policy_row = session.get(
                EducationRetrievalAccessPolicyRevisionRecord,
                command.access_policy_revision_id,
            )
            if (
                policy_row is None
                or policy_row.state != "RELEASED"
                or policy_row.content_sha256 != command.access_policy_sha256
            ):
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                    "preset-selected retrieval policy pointer is stale",
                )
            curriculum_scope: CurriculumRetrievalScope | None = None
            if command.requirement.curriculum_root_key is not None:
                root_node = session.scalar(
                    select(KnowledgeNodeRecord).where(
                        KnowledgeNodeRecord.graph_snapshot_revision_id
                        == snapshot.graph_snapshot_revision_id,
                        KnowledgeNodeRecord.stable_key == command.requirement.curriculum_root_key,
                    )
                )
                root_unit = (
                    session.scalar(
                        select(CurriculumUnitRecord).where(
                            CurriculumUnitRecord.graph_snapshot_revision_id
                            == snapshot.graph_snapshot_revision_id,
                            CurriculumUnitRecord.node_id == root_node.node_id,
                        )
                    )
                    if root_node is not None
                    else None
                )
                if root_unit is None:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_CURRICULUM_SCOPE_INVALID",
                        "curriculum root key is absent from the pinned snapshot",
                    )
                curriculum_scope = CurriculumRetrievalScope(
                    framework_revision_id=root_unit.framework_revision_id,
                    root_unit_id=root_unit.curriculum_unit_id,
                    include_descendants=True,
                )
            graph_snapshot_revision_id = snapshot.graph_snapshot_revision_id

        inner_value: dict[str, Any] = {
            "operation": "CREATE_EVIDENCE_BUNDLE",
            "graph_snapshot_revision_id": graph_snapshot_revision_id,
            "query_kind": command.requirement.query_kind,
            "curriculum_scope": (
                curriculum_scope.model_dump(mode="json") if curriculum_scope is not None else None
            ),
            "topic_keys": list(command.requirement.topic_keys),
            "target_item_revision_id": (
                command.requirement.past_exam_variation.source_item_revision_id
                if command.requirement.schema_version == "educational-retrieval-requirement/2.0"
                else None
            ),
            "required_item_elements": list(command.requirement.required_item_elements),
            "source_classes": list(command.requirement.source_classes),
            "evidence_budget": command.evidence_budget.model_dump(mode="json"),
            "access_policy_revision_id": command.access_policy_revision_id,
            "requester_role": command.requester_role,
            "requester_permission_keys": list(command.requester_permission_keys),
            "requested_by": command.requested_by,
            "idempotency_key": internal_key,
            "submission_sha256": "sha256:" + "0" * 64,
        }
        inner_value["submission_sha256"] = content_sha256(
            {
                key: value
                for key, value in inner_value.items()
                if key not in {"idempotency_key", "submission_sha256"}
            }
        )
        published = self.create(
            CreateEvidenceBundleCommand.model_validate(inner_value),
            include_solution_evidence=solution_evidence_required,
            require_solution_evidence=solution_evidence_required,
        )
        with self.sessions() as session:
            request = session.get(EducationRetrievalRequestRecord, published.retrieval_request_id)
            revision = session.get(
                EvidenceBundleRevisionRecord, published.evidence_bundle_revision_id
            )
            if request is None or revision is None:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                    "published item production Evidence Bundle cannot be reloaded",
                )
            result = self._result_v2(session, request, revision)
            self._require_solution_evidence_result(
                result,
                required=solution_evidence_required,
            )
            return result

    def read_published_item_evidence_in_session(
        self,
        session: Session,
        publication: EvidenceBundlePublicationResultV5,
        *,
        requested_by: str,
        artifact_reader: PinnedArtifactReadContext,
    ) -> EvidenceBundleManifestV5:
        """Resolve exact original evidence; caller owns current authority before/after IO.

        This does not authorize an actor, change the Graph head, rerun retrieval,
        publish or cache a permission. The shared Catalog root is mandatory.
        """
        _active_root_transaction(session)
        artifact_reader.require_session(session)
        raw = similarity_contract_document(
            publication, "evidence-bundle-publication-result-v5", 8191
        )
        publication = EvidenceBundlePublicationResultV5.model_validate(raw)
        bundle = session.get(EvidenceBundleRecord, publication.evidence_bundle_id)
        revision = session.get(
            EvidenceBundleRevisionRecord, publication.evidence_bundle_revision_id
        )
        request = session.get(EducationRetrievalRequestRecord, publication.retrieval_request_id)
        if (
            bundle is None
            or revision is None
            or request is None
            or bundle.retrieval_request_id != request.retrieval_request_id
            or bundle.created_by_operator_id != requested_by
            or revision.evidence_bundle_id != bundle.evidence_bundle_id
            or revision.retrieval_request_id != request.retrieval_request_id
            or request.requester_operator_id != requested_by
            or request.state != "PUBLISHED"
            or revision.state != "PUBLISHED"
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID", "original Item evidence differs"
            )
        original = EducationRetrievalRequestV2.model_validate(request.canonical_request)
        if (
            original.requester_operator_id != requested_by
            or original.retrieval_request_id != request.retrieval_request_id
            or original.query_kind != "ITEM_PREPARATION"
            or request.query_kind != original.query_kind
            or request.requester_role != original.requester_role
            or original.target_item_revision_id is not None
            or original.request_sha256 != request.request_sha256
            or original.graph_snapshot != publication.graph_snapshot
            or request.graph_snapshot_revision_id
            != original.graph_snapshot.graph_snapshot_revision_id
            or revision.graph_snapshot_revision_id
            != original.graph_snapshot.graph_snapshot_revision_id
            or request.access_policy_revision_id != original.access_policy_revision_id
            or revision.access_policy_revision_id != original.access_policy_revision_id
            or request.requester_permissions_sha256 != original.requester_permissions_sha256
            or revision.requester_permissions_sha256 != original.requester_permissions_sha256
            or self._result_v2(session, request, revision) != publication
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID", "original Item evidence differs"
            )
        artifact_reader.prefetch(
            tuple(
                (pointer.artifact_id, pointer.artifact_revision_id)
                for pointer in (publication.manifest_artifact, publication.context_artifact)
            )
        )
        payloads: list[bytes] = []
        for pointer, kind in (
            (publication.manifest_artifact, "manifest"),
            (publication.context_artifact, "context"),
        ):
            member = artifact_reader.read_pinned(
                **pointer.model_dump(mode="python", exclude={"logical_name"}),
                expected_artifact_types=(f"evidence-bundle-{kind}",),
                expected_primary_file=pointer.member_path,
                max_bytes=4 * 1024 * 1024,
            )
            artifact_reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                (pointer.member_path,),
                manifest_version=f"evidence-bundle-{kind}-file-set/1.0",
            )
            payloads.append(member.payload)
        document = json.loads(payloads[0])
        validate_contract("evidence-bundle-manifest-v5", document)
        manifest = EvidenceBundleManifestV5.model_validate(document)
        if (
            canonical_json_bytes(manifest) != payloads[0]
            or any(
                getattr(manifest, field) != getattr(publication, field)
                for field in (
                    "evidence_bundle_id",
                    "evidence_bundle_revision_id",
                    "revision_number",
                    "retrieval_request_id",
                    "retrieval_request_sha256",
                    "graph_snapshot",
                    "access_policy_revision_id",
                    "access_policy_sha256",
                    "requester_permissions_sha256",
                    "budget",
                    "manifest_sha256",
                )
            )
            or manifest.materials.context_markdown != publication.context_artifact
            or manifest.created_at != publication.published_at
            or any(
                entry.source.source_class not in original.source_classes
                for entry in manifest.entries
            )
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID", "immutable Item evidence differs"
            )
        return manifest

    @staticmethod
    def _require_solution_evidence_result(
        result: EvidencePublicationContract | EvidenceBundlePublicationResultV2,
        *,
        required: bool,
    ) -> None:
        if required and not isinstance(result, EvidenceBundlePublicationResultV5):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOLUTION_EVIDENCE_REQUIRED",
                "item production requires an Evidence Bundle with accepted solution evidence",
            )

    @staticmethod
    def _validate_item_production_replay(
        session: Session,
        command: CreateItemProductionEvidenceCommand,
        record: EducationRetrievalRequestRecord,
    ) -> None:
        """Reject same-key replay unless it resolves to the original educational intent."""

        try:
            request = EducationRetrievalRequestV2.model_validate(record.canonical_request)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_RESULT_INVALID",
                "persisted item production retrieval request is invalid",
            ) from exc
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == command.requirement.corpus_key
            )
        )
        curriculum_key: str | None = None
        if request.curriculum_scope is not None:
            curriculum_key = session.scalar(
                select(KnowledgeNodeRecord.stable_key)
                .join(
                    CurriculumUnitRecord,
                    CurriculumUnitRecord.node_id == KnowledgeNodeRecord.node_id,
                )
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id
                    == request.graph_snapshot.graph_snapshot_revision_id,
                    CurriculumUnitRecord.graph_snapshot_revision_id
                    == request.graph_snapshot.graph_snapshot_revision_id,
                    CurriculumUnitRecord.framework_revision_id
                    == request.curriculum_scope.framework_revision_id,
                    CurriculumUnitRecord.curriculum_unit_id
                    == request.curriculum_scope.root_unit_id,
                )
            )
        if (
            corpus is None
            or corpus.graph_id != request.graph_snapshot.graph_id
            or curriculum_key != command.requirement.curriculum_root_key
            or request.query_kind != command.requirement.query_kind
            or request.topic_keys != command.requirement.topic_keys
            or request.required_item_elements != command.requirement.required_item_elements
            or request.source_classes != command.requirement.source_classes
            or request.evidence_budget != command.evidence_budget
            or request.access_policy_revision_id != command.access_policy_revision_id
            or request.access_policy_sha256 != command.access_policy_sha256
            or request.requester_role != command.requester_role
            or request.requester_operator_id != command.requested_by
            or request.requester_permission_keys != command.requester_permission_keys
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT",
                "item production evidence key has different immutable input",
            )

    def create(
        self,
        command: CreateEvidenceBundleCommand,
        *,
        include_solution_evidence: bool = True,
        require_solution_evidence: bool = False,
    ) -> EvidencePublicationContract:
        existing = self._existing(command)
        if existing is not None:
            self._require_solution_evidence_result(
                existing,
                required=require_solution_evidence,
            )
            return existing
        created_at = datetime.now(UTC)
        retrieval_request_id = _typed_id(
            "retrieval_",
            {
                "submission_sha256": command.submission_sha256,
                "idempotency_key": command.idempotency_key,
            },
        )
        evidence_bundle_id = _typed_id("evidence_", {"retrieval_request_id": retrieval_request_id})
        evidence_bundle_revision_id = _typed_id(
            "evidencerev_", {"retrieval_request_id": retrieval_request_id, "revision_number": 1}
        )
        with self.sessions() as session:
            snapshot_pointer = self._snapshot_pointer(session, command.graph_snapshot_revision_id)
            policy = self._policy(session, command.access_policy_revision_id)
            self._authorize(session, command, policy)
            request = self._request(
                command,
                snapshot_pointer=snapshot_pointer,
                policy=policy,
                retrieval_request_id=retrieval_request_id,
                created_at=created_at,
            )
            candidates = self._candidates(
                session,
                command,
                policy,
                include_solution_evidence=include_solution_evidence,
            )
            entries, context_markdown = self._rank_and_render(
                request=request,
                candidates=candidates,
            )
            if require_solution_evidence and not any(
                isinstance(entry, EvidenceEntryV5) and entry.solution_evidence is not None
                for entry in entries
            ):
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_SOLUTION_EVIDENCE_REQUIRED",
                    "retrieval selected no evidence with an accepted solution report",
                )

        context_artifact = self._commit_context(request, context_markdown, entries=entries)
        context_pointer = KnowledgeArtifactMemberPointer(
            artifact_id=context_artifact.artifact_id,
            artifact_revision_id=context_artifact.revision_id,
            sha256=context_artifact.content_hash,
            schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
            media_type="text/markdown",
            logical_name="context.md",
            member_path="evidence/context.md",
        )
        node_ids = {node_id for entry in entries for node_id in entry.graph_node_ids}
        document_sources = {
            (
                entry.source.document_revision_id
                if isinstance(
                    entry.source,
                    EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
                )
                else entry.source.source_file_id
            )
            for entry in entries
            if not isinstance(entry.source, ApprovedItemKnowledgeSourceV2)
        }
        budget = {
            "document_count": len(document_sources),
            "item_revision_count": len(
                {
                    entry.source.item_revision_id
                    for entry in entries
                    if isinstance(entry.source, ApprovedItemKnowledgeSourceV2)
                }
            ),
            "graph_node_count": len(node_ids),
            "claim_count": sum(entry.evidence_kind == "CLAIM" for entry in entries),
            "estimated_context_tokens": _context_tokens(context_markdown),
        }
        manifest_value: dict[str, Any] = {
            "schema_version": self._manifest_schema_version(entries),
            "evidence_bundle_id": evidence_bundle_id,
            "evidence_bundle_revision_id": evidence_bundle_revision_id,
            "revision_number": 1,
            "retrieval_request_id": request.retrieval_request_id,
            "retrieval_request_sha256": request.request_sha256,
            "graph_snapshot": request.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": policy.access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "requester_permissions_sha256": request.requester_permissions_sha256,
            "materials": EvidenceBundleMaterialsV2(context_markdown=context_pointer).model_dump(
                mode="json"
            ),
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "budget": budget,
            "manifest_sha256": "sha256:" + "0" * 64,
            "created_at": _utc_json(created_at),
        }
        manifest_value["manifest_sha256"] = content_sha256(
            {key: value for key, value in manifest_value.items() if key != "manifest_sha256"}
        )
        manifest: EvidenceManifestContract
        try:
            if manifest_value["schema_version"] == "evidence-bundle-manifest/5.0":
                validate_contract("evidence-bundle-manifest-v5", manifest_value)
                manifest = EvidenceBundleManifestV5.model_validate(manifest_value)
            elif manifest_value["schema_version"] == "evidence-bundle-manifest/4.0":
                validate_contract("evidence-bundle-manifest-v4", manifest_value)
                manifest = EvidenceBundleManifestV4.model_validate(manifest_value)
            elif manifest_value["schema_version"] == "evidence-bundle-manifest/3.0":
                validate_contract("evidence-bundle-manifest-v3", manifest_value)
                manifest = EvidenceBundleManifestV3.model_validate(manifest_value)
            else:
                validate_contract("evidence-bundle-manifest-v2", manifest_value)
                manifest = EvidenceBundleManifestV2.model_validate(manifest_value)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_RESULT_INVALID",
                "Evidence Bundle manifest is invalid",
            ) from exc
        manifest_artifact = self._commit_manifest(request, manifest)
        try:
            return self._commit_database(
                command=command,
                request=request,
                manifest=manifest,
                context_artifact=context_artifact,
                manifest_artifact=manifest_artifact,
            )
        except IntegrityError as exc:
            replay = self._existing(command)
            if replay is not None:
                return replay
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_CONCURRENCY_CONFLICT",
                "Evidence Bundle publication conflicted with another transaction",
            ) from exc

    @staticmethod
    def _manifest_schema_version(entries: tuple[EvidenceEntryContract, ...]) -> str:
        if any(isinstance(entry, EvidenceEntryV5) for entry in entries):
            return "evidence-bundle-manifest/5.0"
        if any(isinstance(entry.source, EducationalDocumentKnowledgeSourceV4) for entry in entries):
            return "evidence-bundle-manifest/4.0"
        if any(isinstance(entry.source, EducationalDocumentKnowledgeSourceV3) for entry in entries):
            return "evidence-bundle-manifest/3.0"
        return "evidence-bundle-manifest/2.0"

    def _existing(self, command: CreateEvidenceBundleCommand) -> EvidencePublicationContract | None:
        with self.sessions() as session:
            record = session.scalar(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key == command.idempotency_key
                )
            )
            if record is None:
                return None
            if record.submission_sha256 != command.submission_sha256:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT",
                    "retrieval idempotency key has different input",
                )
            revision = session.scalar(
                select(EvidenceBundleRevisionRecord).where(
                    EvidenceBundleRevisionRecord.retrieval_request_id == record.retrieval_request_id
                )
            )
            if revision is None:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                    "retrieval request has no published Evidence Bundle",
                )
            return self._result(session, record, revision)

    def resolve_snapshot_pointer(
        self, session: Session, graph_snapshot_revision_id: str
    ) -> KnowledgeGraphSnapshotPointer:
        """Public read-only resolution shared by trusted Catalog consumers."""
        return self._snapshot_pointer(session, graph_snapshot_revision_id)

    def resolve_access_policy(
        self, session: Session, revision_id: str, *, sha256: str
    ) -> EducationRetrievalAccessPolicy:
        """Resolve an explicitly pinned released policy, never a latest policy."""
        policy = self._policy(session, revision_id)
        if policy.content_sha256 != sha256:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_STALE", "pinned policy hash differs"
            )
        return policy

    @staticmethod
    def _pinned_local_indexing_policy_record(
        session: Session,
        revision_id: str,
        *,
        sha256: str,
    ) -> EducationRetrievalAccessPolicyRevisionRecord:
        """Shared exact metadata read, not a policy parser or service grant."""
        if (
            type(revision_id) is not str
            or re.fullmatch(r"accessrev_[0-9a-f]{32}", revision_id) is None
            or type(sha256) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", sha256) is None
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "bounded exact policy pins required",
            )
        # Released revisions are append-only. FOR SHARE would require UPDATE
        # privilege, which the runtime must not gain merely to read a policy.
        record = session.scalar(
            select(EducationRetrievalAccessPolicyRevisionRecord)
            .where(
                EducationRetrievalAccessPolicyRevisionRecord.access_policy_revision_id
                == revision_id
            )
            .execution_options(populate_existing=True)
        )
        if record is None or record.state != "RELEASED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "indexing policy is absent or unsupported",
            )
        return record

    @staticmethod
    def resolve_local_indexing_access_policy(
        session: Session,
        revision_id: str,
        *,
        sha256: str,
    ) -> SupportedLocalIndexingAccessPolicy:
        """Exact runtime families; 1.3's unselected segmented policy stays separate."""
        record = KnowledgeRetrievalApplicationService._pinned_local_indexing_policy_record(
            session, revision_id, sha256=sha256
        )
        if record.schema_version not in (
            "education-retrieval-access-policy/1.1",
            "education-retrieval-access-policy/1.2",
            "education-retrieval-access-policy/1.4",
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "indexing policy is absent or unsupported",
            )
        try:
            policy = parse_supported_local_indexing_access_policy(record.canonical_document)
        except ValueError:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "indexing policy document is invalid",
            ) from None
        if (
            policy.schema_version != record.schema_version
            or policy.access_policy_revision_id != revision_id
            or policy.content_sha256 != record.content_sha256
            or policy.content_sha256 != sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_STALE",
                "exact indexing policy identity/hash differs",
            )
        return policy

    @staticmethod
    def resolve_segmented_local_indexing_access_policy(
        session: Session,
        revision_id: str,
        *,
        sha256: str,
    ) -> SegmentedLocalIndexingAccessPolicy:
        """Read pinned 1.3 bytes; runtime authorization remains a separate gate."""
        record = KnowledgeRetrievalApplicationService._pinned_local_indexing_policy_record(
            session, revision_id, sha256=sha256
        )
        if record.schema_version != "education-retrieval-access-policy/1.3":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "segmented indexing policy is absent or unsupported",
            )
        try:
            policy = SegmentedLocalIndexingAccessPolicy.model_validate(record.canonical_document)
        except ValueError:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "segmented indexing policy document is invalid",
            ) from None
        if (
            policy.access_policy_revision_id != revision_id
            or policy.content_sha256 != record.content_sha256
            or policy.content_sha256 != sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_STALE",
                "exact segmented indexing policy identity/hash differs",
            )
        return policy

    @staticmethod
    def lock_source_access_policy(
        session: Session,
        revision_id: str,
        *,
        sha256: str,
    ) -> EducationRetrievalAccessPolicy:
        """Fresh source-policy metadata retained by a writable service-operation root."""
        record = session.scalar(
            select(EducationRetrievalAccessPolicyRevisionRecord)
            .where(
                EducationRetrievalAccessPolicyRevisionRecord.access_policy_revision_id
                == revision_id
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if record is None or record.schema_version != "education-retrieval-access-policy/1.0":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "source policy family is unsupported",
            )
        policy = KnowledgeRetrievalApplicationService._policy(session, revision_id)
        if policy.content_sha256 != sha256:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_STALE",
                "pinned source policy hash differs",
            )
        return policy

    @staticmethod
    def topic_keys_for_terms(
        session: Session,
        *,
        snapshot_id: str,
        terms: tuple[str, ...],
        source_classes: tuple[str, ...],
        allow_answer_bearing: bool,
    ) -> tuple[str, ...]:
        """Adapt indexed human terms to real authoring topic keys, without invented seeds.

        The caller authorizes the actor/policy before metadata discovery. The existing
        immutable lexical index and source-class membership constrain the SQL top-K.
        """
        node = KnowledgeNodeRecord
        term = KnowledgeNodeTermRecord
        pointer = KnowledgeNodeSourcePointerRecord
        membership = select(pointer.pointer_id).where(
            pointer.graph_snapshot_revision_id == snapshot_id,
            pointer.node_id == node.node_id,
            pointer.source_class.in_(source_classes),
        )
        statement = (
            select(node.stable_key)
            .join(
                term,
                (term.graph_snapshot_revision_id == node.graph_snapshot_revision_id)
                & (term.node_id == node.node_id),
            )
            .where(
                node.graph_snapshot_revision_id == snapshot_id,
                term.term.in_(terms),
                membership.exists(),
                func.length(node.stable_key) <= 128,
            )
            .group_by(node.stable_key)
            .order_by(func.count(distinct(term.term)).desc(), node.stable_key)
            .limit(20)
        )
        if not allow_answer_bearing:
            statement = statement.where(node.answer_bearing.is_(False))
        return tuple(
            sorted(
                key
                for key in session.scalars(statement)
                if re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", key)
            )
        )

    def retrieve_read_only(
        self,
        session: Session,
        command: CreateEvidenceBundleCommand,
        *,
        reuse_context: ReadOnlyKnowledgeReuseContext | None = None,
    ) -> ReadOnlyKnowledgeSelection:
        """Reuse authoring authorization/ranking/source checks without publishing anything.

        The caller owns its read-only transaction and subsequent bounded analysis
        materialization. No retrieval row, evidence bundle or Artifact is created.
        """
        snapshot = self._snapshot_pointer(session, command.graph_snapshot_revision_id)
        policy = self._policy(session, command.access_policy_revision_id)
        self._authorize(session, command, policy)
        if reuse_context is not None:
            reuse_context._require(
                self,
                session,
                command,
                graph_snapshot=snapshot,
                policy_sha256=policy.content_sha256,
            )
        request = self._request(
            command,
            snapshot_pointer=snapshot,
            policy=policy,
            retrieval_request_id=_typed_id("retrieval_", {"read_only": command.submission_sha256}),
            created_at=datetime.now(UTC),
        )
        candidates = self._candidates(
            session,
            command,
            policy,
            include_solution_evidence=False,
            reuse_context=reuse_context,
        )
        # Candidate order and source resolution are the exact existing authoring
        # algorithm. The conversational projection applies its smaller text budget.
        return ReadOnlyKnowledgeSelection(request=request, candidates=candidates)

    def admit_read_only_candidate_pool(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope,
        *,
        reuse_context: ReadOnlyKnowledgeReuseContext | None = None,
        artifact_reader: CatalogArtifactReader | None = None,
    ) -> ReadOnlyKnowledgeCandidatePool:
        """Admit bounded exact Item sources without requiring lexical overlap.

        The distinct *analysis* limit is applied after source-class, lifecycle,
        occurrence-scope and answer-bearing filters. Pointer-row limits never
        silently truncate the source population: an overlarge source raises a bounded-read error.
        Canonical source resolution remains the existing Catalog boundary.
        """
        if reuse_context is not None and artifact_reader is not None:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID",
                "a reader injection cannot override an existing immutable reuse context",
            )
        snapshot_id = scope.graph_snapshot.graph_snapshot_revision_id
        snapshot = self.resolve_snapshot_pointer(session, snapshot_id)
        if snapshot != scope.graph_snapshot:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SNAPSHOT_STALE", "candidate pool Graph pin differs"
            )
        policy = self.resolve_access_policy(
            session, scope.access_policy_revision_id, sha256=scope.access_policy_sha256
        )
        self._authorize(session, scope, policy)
        if reuse_context is not None:
            reuse_context._require(
                self,
                session,
                scope,
                graph_snapshot=snapshot,
                policy_sha256=policy.content_sha256,
            )
        return self._read_candidate_pool(
            session,
            scope,
            snapshot=snapshot,
            allow_answer_bearing=scope.requester_role in policy.answer_bearing_roles,
            reuse_context=reuse_context,
            artifact_reader=artifact_reader,
        )

    def admit_local_indexing_candidate_pool(
        self,
        session: Session,
        scope: LocalIndexingSourceReadIntent,
        *,
        authority: LocalIndexingSourceAuthorization | None,
        artifact_reader: CatalogArtifactReader | None = None,
    ) -> ReadOnlyKnowledgeCandidatePool:
        """Separate actual service gate, same canonical source algorithm; no fake user."""
        if authority is None:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return self._admit_service_indexing_candidate_pool(
            session,
            scope,
            authorize_scope=authority.authorize_scope,
            artifact_reader=artifact_reader,
        )

    def admit_segmented_local_indexing_candidate_pool(
        self,
        session: Session,
        scope: LocalIndexingSourceReadIntent,
        *,
        authority: SegmentedLocalIndexingSourceAuthorization | None,
        artifact_reader: CatalogArtifactReader | None = None,
    ) -> ReadOnlyKnowledgeCandidatePool:
        """One bounded 1.3 page through the same canonical source algorithm."""
        if authority is None:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return self._admit_service_indexing_candidate_pool(
            session,
            scope,
            authorize_scope=authority.authorize_segmented_scope,
            artifact_reader=artifact_reader,
        )

    def _admit_service_indexing_candidate_pool(
        self,
        session: Session,
        scope: LocalIndexingSourceReadIntent,
        *,
        authorize_scope: Callable[[Session, LocalIndexingSourceReadIntent], object],
        artifact_reader: CatalogArtifactReader | None,
    ) -> ReadOnlyKnowledgeCandidatePool:
        if type(scope) is not LocalIndexingSourceReadIntent:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        policy = authorize_scope(session, scope)
        snapshot = self.resolve_snapshot_pointer(
            session, scope.graph_snapshot.graph_snapshot_revision_id
        )
        if snapshot != scope.graph_snapshot:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_SCOPE_INVALID")
        result = self._read_candidate_pool(
            session,
            scope,
            snapshot=snapshot,
            allow_answer_bearing=True,
            artifact_reader=artifact_reader,
        )
        if authorize_scope(session, scope) != policy:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_UNAVAILABLE")
        return result

    @staticmethod
    def candidate_pool_analysis_statement(
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        *,
        allow_answer_bearing: bool,
    ) -> Select[tuple[str]]:
        """Bounded metadata selection, NOT authorization or source materialization.

        The same predicates must bound capture prefetch and the official pool;
        raw Graph analyses include additive reports outside occurrence scope.
        """
        snapshot_id = scope.graph_snapshot.graph_snapshot_revision_id
        association = KnowledgeSnapshotAnalysisRecord
        pointer = KnowledgeNodeSourcePointerRecord
        node = KnowledgeNodeRecord
        run = KnowledgeAnalysisRunRecord
        eligible_pointer = (
            select(pointer.pointer_id)
            .select_from(pointer)
            .join(
                node,
                (node.graph_snapshot_revision_id == pointer.graph_snapshot_revision_id)
                & (node.node_id == pointer.node_id),
            )
            .where(
                pointer.graph_snapshot_revision_id == association.graph_snapshot_revision_id,
                pointer.analysis_run_id == association.analysis_run_id,
                pointer.source_class.in_(scope.source_classes),
            )
            .correlate(association)
        )
        if not allow_answer_bearing:
            eligible_pointer = eligible_pointer.where(node.answer_bearing.is_(False))
        occurrence_scoped = (
            scope.population_scope == InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
        )
        if occurrence_scoped:
            eligible_pointer = eligible_pointer.where(pointer.source_class == "PAST_EXAM")
        statement = (
            select(association.analysis_run_id)
            .join(run, run.analysis_run_id == association.analysis_run_id)
            .join(
                ItemRevisionRecord,
                ItemRevisionRecord.item_revision_id == association.source_revision_id,
            )
            .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
            .where(
                association.graph_snapshot_revision_id == snapshot_id,
                association.source_kind == "APPROVED_ITEM_REVISION",
                eligible_pointer.exists(),
                run.state == "ACCEPTED",
                ItemRecord.lifecycle_state == "ACTIVE",
                ItemRevisionRecord.revision_state.in_(("APPROVED", "SUPERSEDED", "RETIRED")),
            )
            .order_by(association.analysis_run_id)
            .limit(scope.maximum_candidates + 1)
        )
        if scope.analysis_run_ids:
            statement = statement.where(association.analysis_run_id.in_(scope.analysis_run_ids))
        if scope.source_revision_ids:
            statement = statement.where(
                association.source_revision_id.in_(scope.source_revision_ids)
            )
        if occurrence_scoped:
            occurrence = AssessmentItemOccurrenceReferenceRecord
            exact_occurrence = (
                select(occurrence.analysis_run_id)
                .where(
                    occurrence.graph_snapshot_revision_id == association.graph_snapshot_revision_id,
                    occurrence.analysis_run_id == association.analysis_run_id,
                    occurrence.item_revision_id == association.source_revision_id,
                    occurrence.item_id == ItemRevisionRecord.item_id,
                )
                .correlate(association, ItemRevisionRecord)
                .exists()
            )
            # EXISTS restricts the original population before LIMIT without
            # duplicate placements multiplying sources or waiving authority.
            statement = statement.where(exact_occurrence)
        return statement

    def _read_candidate_pool(
        self,
        session: Session,
        scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent,
        *,
        snapshot: KnowledgeGraphSnapshotPointer,
        allow_answer_bearing: bool,
        reuse_context: ReadOnlyKnowledgeReuseContext | None = None,
        artifact_reader: CatalogArtifactReader | None = None,
    ) -> ReadOnlyKnowledgeCandidatePool:
        """Shared bounded source selection AFTER the purpose-specific authority gate."""
        snapshot_id = snapshot.graph_snapshot_revision_id
        pointer, node = KnowledgeNodeSourcePointerRecord, KnowledgeNodeRecord
        occurrence_scoped = (
            scope.population_scope == InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
        )
        statement = self.candidate_pool_analysis_statement(
            scope, allow_answer_bearing=allow_answer_bearing
        )
        selected = tuple(str(value) for value in session.scalars(statement))
        truncated = len(selected) > scope.maximum_candidates
        run_ids = selected[: scope.maximum_candidates]
        if not run_ids:
            return ReadOnlyKnowledgeCandidatePool(snapshot, (), truncated=False)
        maximum_pointer_rows = scope.maximum_candidates * MAX_RETRIEVAL_CANDIDATES
        detail = (
            select(pointer, node)
            .join(
                node,
                (node.graph_snapshot_revision_id == pointer.graph_snapshot_revision_id)
                & (node.node_id == pointer.node_id),
            )
            .where(
                pointer.graph_snapshot_revision_id == snapshot_id,
                pointer.analysis_run_id.in_(run_ids),
                pointer.source_class.in_(scope.source_classes),
            )
            .order_by(pointer.analysis_run_id, pointer.node_id, pointer.anchor_id)
            .limit(maximum_pointer_rows + 1)
        )
        if not allow_answer_bearing:
            detail = detail.where(node.answer_bearing.is_(False))
        if occurrence_scoped:
            detail = detail.where(pointer.source_class == "PAST_EXAM")
        rows = tuple(session.execute(detail.execution_options(populate_existing=True)))
        if len(rows) > maximum_pointer_rows:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_CANDIDATE_POOL_BUDGET_EXCEEDED",
                "candidate pool pointer budget was exceeded; no partial pool was returned",
            )
        by_run: dict[str, list[tuple[KnowledgeNodeSourcePointerRecord, KnowledgeNodeRecord]]] = (
            defaultdict(list)
        )
        for source_pointer, source_node in rows:
            by_run[source_pointer.analysis_run_id].append((source_pointer, source_node))
        cache = self._snapshot_source_resolution_cache(
            session,
            snapshot_id,
            tuple(values[0][0] for values in by_run.values()),
            reuse_context=reuse_context,
            artifact_reader=artifact_reader,
            item_source_revision_ids=tuple(
                sorted(
                    {
                        values[0][0].source_revision_id
                        for values in by_run.values()
                        if values[0][0].source_class in {"APPROVED_ITEM", "PAST_EXAM"}
                    }
                )
            ),
        )
        admitted: list[KnowledgeRetrievalCandidate] = []
        for run_id in run_ids:
            entries = by_run.get(run_id)
            if not entries:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID",
                    "candidate analysis lost its Graph source pointers",
                )
            source = self._resolve_snapshot_source(session, snapshot_id, entries[0][0], cache=cache)
            if not isinstance(source, ApprovedItemKnowledgeSourceV2):
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID", "candidate source is not an Item"
                )
            for source_pointer, _node in entries:
                if (
                    self._resolve_snapshot_source(session, snapshot_id, source_pointer, cache=cache)
                    != source
                ):
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID",
                        "candidate source identity differs",
                    )
            nodes_by_id = {value.node_id: value for _pointer, value in entries}
            node_ids = tuple(sorted(nodes_by_id))[:16]
            admitted.append(
                KnowledgeRetrievalCandidate(
                    analysis_run_id=run_id,
                    source=source,
                    node_ids=node_ids,
                    anchor_ids=tuple(sorted({p.anchor_id for p, _n in entries}))[:32],
                    node_labels=tuple(nodes_by_id[node_id].label for node_id in node_ids),
                    node_types=tuple(nodes_by_id[node_id].node_type for node_id in node_ids),
                    relevance_milli=0,
                    answer_bearing=any(value.answer_bearing for value in nodes_by_id.values()),
                )
            )
        return ReadOnlyKnowledgeCandidatePool(snapshot, tuple(admitted), truncated=truncated)

    def _snapshot_pointer(
        self, session: Session, graph_snapshot_revision_id: str
    ) -> KnowledgeGraphSnapshotPointer:
        snapshot = session.get(
            KnowledgeGraphSnapshotRecord, graph_snapshot_revision_id, populate_existing=True
        )
        if snapshot is None or snapshot.state != "PUBLISHED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SNAPSHOT_INVALID",
                "requested graph snapshot is absent or unpublished",
            )
        logical = session.get(ArtifactRecord, snapshot.manifest_artifact_id)
        revision = session.get(ArtifactRevisionRecord, snapshot.manifest_artifact_revision_id)
        if (
            logical is None
            or revision is None
            or not logical.approved
            or not revision.approved
            or revision.logical_artifact_id != snapshot.manifest_artifact_id
            or revision.content_hash != snapshot.manifest_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SNAPSHOT_STALE",
                "graph snapshot manifest pointer is stale",
            )
        manifest_schema_ref = _artifact_member_schema_ref(
            revision,
            member_path="projections/manifest.json",
            allowed=frozenset(
                {
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/3.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/4.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/5.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/6.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/7.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/8.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/9.0",
                }
            ),
        )
        return KnowledgeGraphSnapshotPointer(
            graph_id=snapshot.graph_id,
            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
            manifest_artifact=KnowledgeArtifactMemberPointer(
                artifact_id=snapshot.manifest_artifact_id,
                artifact_revision_id=snapshot.manifest_artifact_revision_id,
                sha256=snapshot.manifest_sha256,
                schema_ref=manifest_schema_ref,
                media_type="application/json",
                logical_name="manifest.json",
                member_path="projections/manifest.json",
            ),
            manifest_sha256=snapshot.manifest_sha256,
        )

    @staticmethod
    def _policy(session: Session, access_policy_revision_id: str) -> EducationRetrievalAccessPolicy:
        record = session.get(
            EducationRetrievalAccessPolicyRevisionRecord,
            access_policy_revision_id,
            populate_existing=True,
        )
        if record is None or record.state != "RELEASED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "retrieval access policy is absent or unreleased",
            )
        try:
            validate_contract("education-retrieval-access-policy", record.canonical_document)
            policy = EducationRetrievalAccessPolicy.model_validate(record.canonical_document)
        except (ValueError, ValidationError, JsonSchemaValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "retrieval access policy document is invalid",
            ) from exc
        if (
            policy.access_policy_revision_id != record.access_policy_revision_id
            or policy.content_sha256 != record.content_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_STALE",
                "retrieval access policy identity or hash differs",
            )
        return policy

    @staticmethod
    def _authorize(
        session: Session,
        command: CreateEvidenceBundleCommand | ReadOnlyCandidatePoolScope,
        policy: EducationRetrievalAccessPolicy,
    ) -> None:
        operator = session.get(OperatorRecord, command.requested_by)
        if operator is None or operator.status != "ACTIVE":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REQUESTER_INVALID",
                "retrieval requester is absent or inactive",
            )
        permission_keys = set(command.requester_permission_keys)
        if "knowledge_graph:retrieve" not in permission_keys:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_UNAUTHORIZED",
                "retrieval permission is absent",
            )
        if (
            command.query_kind not in policy.allowed_query_kinds
            or command.requester_role not in policy.allowed_requester_roles
            or not set(command.source_classes).issubset(policy.allowed_source_classes)
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_UNAUTHORIZED",
                "retrieval query, role, or source class is outside policy",
            )
        requested = command.evidence_budget
        maximum = policy.maximum_budget
        if any(
            left > right
            for left, right in (
                (requested.max_documents, maximum.max_documents),
                (requested.max_item_revisions, maximum.max_item_revisions),
                (requested.max_graph_nodes, maximum.max_graph_nodes),
                (requested.max_claims, maximum.max_claims),
                (requested.max_context_tokens, maximum.max_context_tokens),
            )
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_BUDGET_INVALID",
                "retrieval budget exceeds policy",
            )

    @staticmethod
    def _request(
        command: CreateEvidenceBundleCommand,
        *,
        snapshot_pointer: KnowledgeGraphSnapshotPointer,
        policy: EducationRetrievalAccessPolicy,
        retrieval_request_id: str,
        created_at: datetime,
    ) -> EducationRetrievalRequestV2:
        permissions = tuple(command.requester_permission_keys)
        value: dict[str, Any] = {
            "schema_version": "education-retrieval-request/2.0",
            "retrieval_request_id": retrieval_request_id,
            "graph_snapshot": snapshot_pointer.model_dump(mode="json"),
            "query_kind": command.query_kind,
            "curriculum_scope": (
                command.curriculum_scope.model_dump(mode="json")
                if command.curriculum_scope is not None
                else None
            ),
            "topic_keys": list(command.topic_keys),
            "target_item_revision_id": command.target_item_revision_id,
            "required_item_elements": list(command.required_item_elements),
            "source_classes": list(command.source_classes),
            "retrieval_mode": "HYBRID_LOCAL_MULTIHOP",
            "evidence_budget": command.evidence_budget.model_dump(mode="json"),
            "access_policy_revision_id": policy.access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "requester_role": command.requester_role,
            "requester_operator_id": command.requested_by,
            "requester_permission_keys": list(permissions),
            "requester_permissions_sha256": content_sha256({"permission_keys": list(permissions)}),
            "requested_at": _utc_json(created_at),
            "request_sha256": "sha256:" + "0" * 64,
        }
        value["request_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "request_sha256"}
        )
        try:
            validate_contract("education-retrieval-request-v2", value)
            return EducationRetrievalRequestV2.model_validate(value)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REQUEST_INVALID",
                "resolved retrieval request is invalid",
            ) from exc

    def _candidates(
        self,
        session: Session,
        command: CreateEvidenceBundleCommand,
        policy: EducationRetrievalAccessPolicy,
        *,
        include_solution_evidence: bool = True,
        reuse_context: ReadOnlyKnowledgeReuseContext | None = None,
    ) -> tuple[_Candidate, ...]:
        snapshot_id = command.graph_snapshot_revision_id
        max_nodes = min(command.evidence_budget.max_graph_nodes, MAX_RETRIEVAL_CANDIDATES)
        seed_scores: dict[str, int] = {}

        if command.target_item_revision_id is not None:
            placement_node_id = _exact_target_placement_node_id(
                session,
                snapshot_id=snapshot_id,
                item_revision_id=command.target_item_revision_id,
            )
            seed_scores[placement_node_id] = 1000

        if command.curriculum_scope is not None:
            scope = command.curriculum_scope
            root = session.scalar(
                select(CurriculumUnitRecord).where(
                    CurriculumUnitRecord.graph_snapshot_revision_id == snapshot_id,
                    CurriculumUnitRecord.framework_revision_id == scope.framework_revision_id,
                    CurriculumUnitRecord.curriculum_unit_id == scope.root_unit_id,
                )
            )
            if root is None:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_CURRICULUM_SCOPE_INVALID",
                    "pinned curriculum scope does not resolve in the snapshot",
                )
            unit_ids = [scope.root_unit_id]
            if scope.include_descendants:
                unit_ids = list(
                    session.scalars(
                        select(CurriculumUnitClosureRecord.descendant_unit_id)
                        .where(
                            CurriculumUnitClosureRecord.graph_snapshot_revision_id == snapshot_id,
                            CurriculumUnitClosureRecord.framework_revision_id
                            == scope.framework_revision_id,
                            CurriculumUnitClosureRecord.ancestor_unit_id == scope.root_unit_id,
                        )
                        .order_by(
                            CurriculumUnitClosureRecord.depth,
                            CurriculumUnitClosureRecord.descendant_unit_id,
                        )
                        .limit(max_nodes)
                    )
                )
            unit_nodes = session.execute(
                select(CurriculumUnitRecord.node_id, CurriculumUnitRecord.curriculum_unit_id).where(
                    CurriculumUnitRecord.graph_snapshot_revision_id == snapshot_id,
                    CurriculumUnitRecord.curriculum_unit_id.in_(unit_ids),
                )
            )
            for node_id, unit_id in unit_nodes:
                seed_scores[node_id] = max(
                    seed_scores.get(node_id, 0), 1000 if unit_id == scope.root_unit_id else 950
                )

        if command.topic_keys:
            exact_topic_nodes = session.scalars(
                select(KnowledgeNodeRecord.node_id)
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeRecord.stable_key.in_(command.topic_keys),
                )
                .order_by(KnowledgeNodeRecord.node_id)
                .limit(max_nodes)
            )
            for node_id in exact_topic_nodes:
                seed_scores[str(node_id)] = max(seed_scores.get(str(node_id), 0), 1000)

        terms = sorted(
            {
                term
                for topic_key in command.topic_keys
                for term in knowledge_node_terms(topic_key, "")
            }
        )
        if terms:
            term_frequency = func.count().over(partition_by=KnowledgeNodeTermRecord.term)
            lexical_rows = tuple(
                (str(term), str(node_id), int(frequency))
                for term, node_id, frequency in session.execute(
                    select(
                        KnowledgeNodeTermRecord.term,
                        KnowledgeNodeTermRecord.node_id,
                        term_frequency.label("term_frequency"),
                    )
                    .where(
                        KnowledgeNodeTermRecord.graph_snapshot_revision_id == snapshot_id,
                        KnowledgeNodeTermRecord.term.in_(terms),
                    )
                    .order_by(
                        term_frequency,
                        KnowledgeNodeTermRecord.term,
                        KnowledgeNodeTermRecord.node_id,
                    )
                    .limit(max_nodes * max(len(terms), 1))
                )
            )
            for node_id, score in _rank_lexical_seed_rows(lexical_rows, limit=max_nodes):
                seed_scores[node_id] = max(seed_scores.get(node_id, 0), score)

        if command.required_item_elements and command.target_item_revision_id is None:
            element_filter = [str(value) for value in command.required_item_elements]
            item_query = (
                select(ItemElementReferenceRecord.item_revision_id)
                .where(
                    ItemElementReferenceRecord.graph_snapshot_revision_id == snapshot_id,
                    ItemElementReferenceRecord.element_kind.in_(element_filter),
                )
                .group_by(ItemElementReferenceRecord.item_revision_id)
                .having(
                    func.count(distinct(ItemElementReferenceRecord.element_kind))
                    == len(element_filter)
                )
                .order_by(ItemElementReferenceRecord.item_revision_id)
                .limit(max(command.evidence_budget.max_item_revisions, 1) * 4)
            )
            item_revisions = tuple(session.scalars(item_query))
            if item_revisions:
                for node_id in session.scalars(
                    select(ItemElementReferenceRecord.node_id)
                    .where(
                        ItemElementReferenceRecord.graph_snapshot_revision_id == snapshot_id,
                        ItemElementReferenceRecord.item_revision_id.in_(item_revisions),
                        ItemElementReferenceRecord.element_kind.in_(element_filter),
                    )
                    .order_by(ItemElementReferenceRecord.node_id)
                    .limit(max_nodes)
                ):
                    seed_scores[node_id] = max(seed_scores.get(node_id, 0), 975)

        if not seed_scores:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE",
                "retrieval query matched no graph seed",
            )
        scores = _bounded_seed_scores(seed_scores, limit=max_nodes)
        frontier = set(scores)
        visited = set(frontier)
        for _hop, hop_score in ((1, 850), (2, 700)):
            if not frontier or len(visited) >= max_nodes:
                break
            rows = session.execute(
                select(KnowledgeEdgeRecord.from_node_id, KnowledgeEdgeRecord.to_node_id)
                .where(
                    KnowledgeEdgeRecord.graph_snapshot_revision_id == snapshot_id,
                    or_(
                        KnowledgeEdgeRecord.from_node_id.in_(frontier),
                        KnowledgeEdgeRecord.to_node_id.in_(frontier),
                    ),
                )
                .order_by(KnowledgeEdgeRecord.edge_id)
                .limit(max_nodes * 8)
            )
            next_frontier: set[str] = set()
            for from_node_id, to_node_id in rows:
                for node_id in (from_node_id, to_node_id):
                    if node_id not in visited:
                        next_frontier.add(node_id)
            for node_id in sorted(next_frontier)[: max_nodes - len(visited)]:
                scores[node_id] = hop_score
                visited.add(node_id)
            frontier = next_frontier.intersection(visited)

        node_rows = tuple(
            session.scalars(
                select(KnowledgeNodeRecord)
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeRecord.node_id.in_(visited),
                )
                .order_by(KnowledgeNodeRecord.node_id)
            )
        )
        nodes = {row.node_id: row for row in node_rows}
        pointer_rows = tuple(
            session.scalars(
                select(KnowledgeNodeSourcePointerRecord)
                .where(
                    KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeSourcePointerRecord.node_id.in_(nodes),
                    KnowledgeNodeSourcePointerRecord.source_class.in_(command.source_classes),
                )
                .order_by(
                    KnowledgeNodeSourcePointerRecord.artifact_revision_id,
                    KnowledgeNodeSourcePointerRecord.member_path,
                    KnowledgeNodeSourcePointerRecord.node_id,
                    KnowledgeNodeSourcePointerRecord.anchor_id,
                )
                .limit(max_nodes * MAX_POINTER_ROWS_PER_NODE)
            )
        )
        grouped: dict[_ImmutableSourcePointerKey, list[KnowledgeNodeSourcePointerRecord]] = (
            defaultdict(list)
        )
        for pointer in pointer_rows:
            node = nodes.get(pointer.node_id)
            if node is None:
                continue
            if node.answer_bearing and command.requester_role not in policy.answer_bearing_roles:
                continue
            grouped[_ImmutableSourcePointerKey.from_record(snapshot_id, pointer)].append(pointer)

        source_cache = self._snapshot_source_resolution_cache(
            session,
            snapshot_id,
            tuple(pointers[0] for pointers in grouped.values()),
            reuse_context=reuse_context,
        )
        values: list[_Candidate] = []
        for _key, pointers in sorted(
            grouped.items(),
            key=lambda item: (
                item[0].analysis_run_id,
                item[0].artifact_revision_id,
                item[0].member_path,
                item[0].source_revision_id,
                item[0].source_class,
                item[0].source_artifact_id,
                item[0].source_sha256,
            ),
        ):
            nodes_for_source = {
                pointer.node_id: nodes[pointer.node_id]
                for pointer in pointers
                if pointer.node_id in nodes
            }
            ordered_nodes = tuple(sorted(nodes_for_source))[:16]
            anchors = tuple(sorted({pointer.anchor_id for pointer in pointers}))[:32]
            if not ordered_nodes or not anchors:
                continue
            source = self._resolve_snapshot_source(
                session,
                snapshot_id,
                pointers[0],
                cache=source_cache,
            )
            if source.source_class not in command.source_classes:
                continue
            if command.target_item_revision_id is not None and (
                not isinstance(source, ApprovedItemKnowledgeSourceV2)
                or source.item_revision_id != command.target_item_revision_id
                or source.source_class != "PAST_EXAM"
            ):
                continue
            values.append(
                _Candidate(
                    analysis_run_id=pointers[0].analysis_run_id,
                    source=source,
                    node_ids=ordered_nodes,
                    anchor_ids=anchors,
                    node_labels=tuple(nodes_for_source[node_id].label for node_id in ordered_nodes),
                    node_types=tuple(
                        nodes_for_source[node_id].node_type for node_id in ordered_nodes
                    ),
                    relevance_milli=max(scores[node_id] for node_id in ordered_nodes),
                    answer_bearing=any(
                        nodes_for_source[node_id].answer_bearing for node_id in ordered_nodes
                    ),
                )
            )
        if not values:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE",
                "retrieval graph matched no authorized immutable source",
            )
        candidates = tuple(
            sorted(
                values,
                key=lambda item: (
                    -item.relevance_milli,
                    item.source.artifact_member.artifact_revision_id,
                    item.source.artifact_member.member_path,
                    item.analysis_run_id,
                ),
            )[:MAX_RETRIEVAL_CANDIDATES]
        )
        if not include_solution_evidence:
            return candidates
        try:
            solutions = resolve_solution_evidence_by_base_run(
                session,
                self.artifacts,
                base_analysis_run_ids=tuple(candidate.analysis_run_id for candidate in candidates),
            )
        except SolutionEvidenceResolutionError as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOLUTION_EVIDENCE_INVALID",
                "accepted additive solution evidence could not be resolved exactly",
            ) from exc
        return tuple(
            replace(candidate, solution=solutions.get(candidate.analysis_run_id))
            for candidate in candidates
        )

    def _snapshot_source_resolution_cache(
        self,
        session: Session,
        snapshot_id: str,
        pointers: tuple[KnowledgeNodeSourcePointerRecord, ...],
        *,
        reuse_context: ReadOnlyKnowledgeReuseContext | None = None,
        artifact_reader: CatalogArtifactReader | None = None,
        item_source_revision_ids: tuple[str, ...] = (),
    ) -> _SnapshotSourceResolutionCache:
        if reuse_context is not None and artifact_reader is not None:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID",
                "a reader injection cannot override an existing immutable reuse context",
            )
        reader = self.artifacts if artifact_reader is None else artifact_reader
        if reuse_context is not None:
            reuse_context._require_owner(self, session)
            if reuse_context._scope.graph_snapshot.graph_snapshot_revision_id != snapshot_id:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID",
                    "immutable source decoding reuse belongs to a different Graph revision",
                )
        analysis_run_ids = tuple(sorted({pointer.analysis_run_id for pointer in pointers}))
        if not analysis_run_ids:
            return _SnapshotSourceResolutionCache(
                associations_by_run_id={},
                runs_by_id={},
                artifacts=reuse_context._artifacts
                if reuse_context is not None
                else _request_scoped_artifact_validation_cache(reader),
                past_exam_provenance=reuse_context._past_exam
                if reuse_context is not None
                else PastExamSourceResolutionCache(),
            )
        associations = tuple(
            session.scalars(
                select(KnowledgeSnapshotAnalysisRecord)
                .where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeSnapshotAnalysisRecord.analysis_run_id.in_(analysis_run_ids),
                )
                .execution_options(populate_existing=True)
            )
        )
        runs = tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord)
                .where(KnowledgeAnalysisRunRecord.analysis_run_id.in_(analysis_run_ids))
                .execution_options(populate_existing=True)
            )
        )
        associations_by_run_id: dict[str, KnowledgeSnapshotAnalysisRecord] = {}
        for association in associations:
            if association.analysis_run_id in associations_by_run_id:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID",
                    "graph snapshot contains duplicate accepted-analysis associations",
                )
            associations_by_run_id[association.analysis_run_id] = association
        runs_by_id: dict[str, KnowledgeAnalysisRunRecord] = {}
        for run in runs:
            if run.analysis_run_id in runs_by_id:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID",
                    "graph snapshot resolves an Analysis Run more than once",
                )
            runs_by_id[run.analysis_run_id] = run
        past_exam_provenance = (
            reuse_context._past_exam
            if reuse_context is not None
            else PastExamSourceResolutionCache()
        )
        scoped_artifacts = (
            reuse_context._artifacts
            if reuse_context is not None
            else _request_scoped_artifact_validation_cache(reader)
        )
        try:
            # This belongs to this capture only. In particular it is never kept
            # in the cross-call immutable reuse context or the root byte reader.
            item_relations = (
                read_item_source_relations(
                    session,
                    item_source_revision_ids,
                    artifacts=scoped_artifacts,
                    past_exam_cache=past_exam_provenance,
                )
                if item_source_revision_ids
                else None
            )
        except KnowledgeAnalysisSourceError as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_STALE",
                "current Item source relations cannot be resolved exactly",
            ) from exc
        return _SnapshotSourceResolutionCache(
            associations_by_run_id=associations_by_run_id,
            runs_by_id=runs_by_id,
            artifacts=scoped_artifacts,
            past_exam_provenance=past_exam_provenance,
            item_relations=item_relations,
        )

    def _resolve_snapshot_source(
        self,
        session: Session,
        snapshot_id: str,
        pointer: KnowledgeNodeSourcePointerRecord,
        *,
        cache: _SnapshotSourceResolutionCache,
    ) -> _ResolvedKnowledgeSource:
        pointer_key = _ImmutableSourcePointerKey.from_record(snapshot_id, pointer)
        cached = cache.validated_sources_by_pointer.get(pointer_key)
        if cached is not None:
            return cached
        association = cache.associations_by_run_id.get(pointer.analysis_run_id)
        if association is None or association.source_revision_id != pointer.source_revision_id:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID",
                "graph source pointer has no pinned accepted analysis",
            )
        run = cache.runs_by_id.get(association.analysis_run_id)
        if run is None or run.state != "ACCEPTED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_STALE",
                "pinned graph analysis is absent or unaccepted",
            )
        source = cache.declared_sources_by_run_id.get(run.analysis_run_id)
        try:
            if source is None:
                source = self._declared_source(run)
                cache.declared_sources_by_run_id[run.analysis_run_id] = source
            actual = cache.resolved_sources_by_run_id.get(run.analysis_run_id)
            if actual is None:
                actual = self._resolve_declared_source(
                    session,
                    source,
                    cache=cache,
                )
                if actual != source:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_SOURCE_HASH_MISMATCH",
                        "accepted analysis source differs from the canonical source revision",
                    )
                cache.resolved_sources_by_run_id[run.analysis_run_id] = actual
        except (KnowledgeAnalysisSourceError, ValidationError, ValueError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_STALE",
                "pinned source can no longer be resolved exactly",
            ) from exc
        allowed_member_keys = {
            (
                actual.artifact_member.artifact_id,
                actual.artifact_member.artifact_revision_id,
                actual.artifact_member.sha256,
                actual.artifact_member.member_path,
            )
        }
        if isinstance(actual, ApprovedPastExamItemKnowledgeSourceV3):
            allowed_member_keys.update(
                (
                    page.image.artifact_id,
                    page.image.artifact_revision_id,
                    page.image.sha256,
                    page.image.member_path,
                )
                for page in actual.page_inputs
            )
        member_key = (
            pointer.source_artifact_id,
            pointer.artifact_revision_id,
            pointer.source_sha256,
            pointer.member_path,
        )
        if actual != source or member_key not in allowed_member_keys:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_HASH_MISMATCH",
                "graph source pointer differs from the canonical source revision",
            )
        cache.validated_sources_by_pointer[pointer_key] = actual
        return actual

    @staticmethod
    def _declared_source(run: KnowledgeAnalysisRunRecord) -> _ResolvedKnowledgeSource:
        schema_version = run.canonical_request.get("schema_version")
        if schema_version == "knowledge-analysis-request/9.0":
            return KnowledgeAnalysisRequestV9.model_validate(run.canonical_request).source
        if schema_version == "knowledge-analysis-request/8.0":
            return KnowledgeAnalysisRequestV8.model_validate(run.canonical_request).source
        if schema_version == "knowledge-analysis-request/7.0":
            return KnowledgeAnalysisRequestV7.model_validate(run.canonical_request).source
        if schema_version == "knowledge-analysis-request/6.0":
            return KnowledgeAnalysisRequestV6.model_validate(run.canonical_request).source
        if schema_version == "knowledge-analysis-request/5.0":
            return KnowledgeAnalysisRequestV5.model_validate(run.canonical_request).source
        if schema_version == "knowledge-analysis-request/4.0":
            return KnowledgeAnalysisRequestV4.model_validate(run.canonical_request).source
        if schema_version == "knowledge-analysis-request/3.0":
            return KnowledgeAnalysisRequestV3.model_validate(run.canonical_request).source
        return KnowledgeAnalysisRequestV2.model_validate(run.canonical_request).source

    @staticmethod
    def _resolve_declared_source(
        session: Session,
        source: _ResolvedKnowledgeSource,
        *,
        cache: _SnapshotSourceResolutionCache,
    ) -> _ResolvedKnowledgeSource:
        if isinstance(source, ApprovedPastExamItemKnowledgeSourceV3):
            return resolve_historically_approved_item_source(
                session,
                artifacts=cache.artifacts,
                item_revision_id=source.item_revision_id,
                source_class=source.source_class,
                past_exam_cache=cache.past_exam_provenance,
                read_relations=cache.item_relations,
            )
        if isinstance(
            source,
            EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
        ):
            return resolve_educational_document_source(
                session,
                cache.artifacts,
                document_revision_id=source.document_revision_id,
                source_class=source.source_class,
                first_physical_page=source.first_physical_page,
                last_physical_page=source.last_physical_page,
                curriculum_unit_keys=source.curriculum_unit_keys,
                cache=cache.educational_documents,
            )
        if isinstance(source, ContentIntakeKnowledgeSourceV2):
            return resolve_content_intake_source(
                session,
                intake_batch_id=source.intake_batch_id,
                source_file_id=source.source_file_id,
                source_class=source.source_class,
            )
        return resolve_historically_approved_item_source(
            session,
            artifacts=cache.artifacts,
            item_revision_id=source.item_revision_id,
            source_class=source.source_class,
            past_exam_cache=cache.past_exam_provenance,
            read_relations=cache.item_relations,
        )

    @staticmethod
    def _rank_and_render(
        *,
        request: EducationRetrievalRequestV2,
        candidates: tuple[_Candidate, ...],
    ) -> tuple[tuple[EvidenceEntryContract, ...], str]:
        header_lines = [
            "# EOM Evidence Bundle",
            "",
            f"- Retrieval request: `{request.retrieval_request_id}`",
            f"- Graph snapshot: `{request.graph_snapshot.graph_snapshot_revision_id}`",
            "",
            "## Ranked evidence",
            "",
        ]
        selected: list[EvidenceEntryContract] = []
        selected_lines: dict[str, str] = {}
        selected_immutable_sources: set[tuple[str, str, str]] = set()
        documents: set[str] = set()
        items: set[str] = set()
        nodes: set[str] = set()
        claim_count = 0
        lines = list(header_lines)
        use_solution_manifest = any(candidate.solution is not None for candidate in candidates)
        for candidate in candidates:
            source = candidate.source
            source_document = isinstance(
                source,
                ContentIntakeKnowledgeSourceV2
                | EducationalDocumentKnowledgeSourceV3
                | EducationalDocumentKnowledgeSourceV4,
            )
            if isinstance(source, ContentIntakeKnowledgeSourceV2):
                source_identity = source.source_file_id
            elif isinstance(
                source,
                EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
            ):
                source_identity = source.document_revision_id
            else:
                source_identity = source.item_revision_id
            new_documents = documents | ({source_identity} if source_document else set())
            new_items = items | ({source_identity} if not source_document else set())
            new_nodes = nodes | set(candidate.node_ids)
            kind = KnowledgeRetrievalApplicationService._evidence_kind(candidate)
            new_claim_count = claim_count + (kind == "CLAIM")
            if (
                len(new_documents) > request.evidence_budget.max_documents
                or len(new_items) > request.evidence_budget.max_item_revisions
                or len(new_nodes) > request.evidence_budget.max_graph_nodes
                or new_claim_count > request.evidence_budget.max_claims
            ):
                continue
            use: Literal["GROUNDING", "REFERENCE_PATTERN", "AVOID_COPY"] = (
                "AVOID_COPY"
                if candidate.answer_bearing
                else ("GROUNDING" if source_document else "REFERENCE_PATTERN")
            )
            immutable_source = (
                source.artifact_member.artifact_revision_id,
                source.artifact_member.member_path,
                use,
            )
            if immutable_source in selected_immutable_sources:
                continue
            evidence_id = _typed_id(
                "evidenceitem_",
                {
                    "retrieval_request_id": request.retrieval_request_id,
                    "source_kind": source.source_kind,
                    "source_identity": source_identity,
                    "artifact_revision_id": source.artifact_member.artifact_revision_id,
                    "member_path": source.artifact_member.member_path,
                    "use": use,
                },
            )
            entry: EvidenceEntryContract
            if use_solution_manifest:
                entry = EvidenceEntryV5(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                    solution_evidence=(
                        candidate.solution.pointer if candidate.solution is not None else None
                    ),
                )
            elif isinstance(source, EducationalDocumentKnowledgeSourceV4):
                entry = EvidenceEntryV4(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                )
            elif isinstance(source, EducationalDocumentKnowledgeSourceV3):
                entry = EvidenceEntryV3(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                )
            else:
                item_source = (
                    ApprovedItemKnowledgeSourceV2(
                        source_class=source.source_class,
                        item_id=source.item_id,
                        item_revision_id=source.item_revision_id,
                        lifecycle_state=source.lifecycle_state,
                        artifact_member=source.artifact_member,
                    )
                    if isinstance(source, ApprovedPastExamItemKnowledgeSourceV3)
                    else source
                )
                entry = EvidenceEntryV2(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=item_source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                )
            label = "; ".join(candidate.node_labels)
            line = (
                f"- `{entry.evidence_id}` score={entry.relevance_milli} use={entry.use} "
                f"class={source.source_class} source=`{source_identity}` "
                f"nodes={','.join(entry.graph_node_ids)}: {label}"
            )
            if candidate.solution is not None:
                reusable = json.dumps(
                    {
                        "assessment_design_summary": (
                            candidate.solution.report.assessment_design_summary
                        ),
                        "reusable_generation_guidance": (
                            candidate.solution.report.reusable_generation_guidance
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                line = f"{line} reusable_solution_design={reusable}"
            proposed = "\n".join([*lines, line, ""])
            if (
                _context_tokens(proposed) > request.evidence_budget.max_context_tokens
                or len(proposed.encode("utf-8")) > MAX_CONTEXT_BYTES
            ):
                continue
            selected.append(entry)
            selected_lines[entry.evidence_id] = line
            selected_immutable_sources.add(immutable_source)
            lines.append(line)
            documents = new_documents
            items = new_items
            nodes = new_nodes
            claim_count = int(new_claim_count)
            if len(selected) >= 128:
                break
        if not selected:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_BUDGET_EXHAUSTED",
                "no authorized evidence fits the requested budget",
            )
        ordered = tuple(
            sorted(selected, key=lambda item: (-item.relevance_milli, item.evidence_id))
        )
        context = "\n".join(
            [*header_lines, *(selected_lines[entry.evidence_id] for entry in ordered), ""]
        )
        return ordered, context

    @staticmethod
    def _evidence_kind(
        candidate: _Candidate,
    ) -> Literal["DOCUMENT", "ITEM_REVISION", "CLAIM", "TABLE", "FIGURE", "EQUATION"]:
        types = set(candidate.node_types)
        if "CLAIM" in types:
            return "CLAIM"
        if "TABLE" in types:
            return "TABLE"
        if "FIGURE" in types:
            return "FIGURE"
        if "EQUATION" in types or "FORMULA" in types:
            return "EQUATION"
        if isinstance(candidate.source, ApprovedItemKnowledgeSourceV2):
            return "ITEM_REVISION"
        return "DOCUMENT"

    def _commit_context(
        self,
        request: EducationRetrievalRequestV2,
        markdown: str,
        *,
        entries: tuple[EvidenceEntryContract, ...],
    ) -> CatalogArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="evidence-context.", dir=self.settings.staging_root
            ) as raw_directory:
                source = Path(raw_directory) / "context.md"
                source.write_text(markdown, encoding="utf-8")
                source.chmod(0o640)
                multimodal_graph = any(
                    isinstance(entry.source, EducationalDocumentKnowledgeSourceV4)
                    for entry in entries
                )
                solution_graph = any(isinstance(entry, EvidenceEntryV5) for entry in entries)
                document_graph = multimodal_graph or any(
                    isinstance(entry.source, EducationalDocumentKnowledgeSourceV3)
                    for entry in entries
                )
                return self.artifacts.commit_file_set(
                    files={"evidence/context.md": source},
                    primary_file="evidence/context.md",
                    artifact_type="evidence-bundle-context",
                    idempotency_key=f"evidence-context:{request.retrieval_request_id}",
                    request={
                        "retrieval_request_id": request.retrieval_request_id,
                        "request_sha256": request.request_sha256,
                    },
                    result={"estimated_context_tokens": _context_tokens(markdown)},
                    file_metadata={
                        "evidence/context.md": {
                            "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
                            "media_type": "text/markdown",
                        }
                    },
                    manifest_version="evidence-bundle-context-file-set/1.0",
                    protocol_version=(
                        KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_PROTOCOL
                        if solution_graph
                        else (
                            KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL
                            if multimodal_graph
                            else (
                                KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL
                                if document_graph
                                else KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL
                            )
                        )
                    ),
                    protocol_schema_hash=(
                        KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_SCHEMA_HASH
                        if solution_graph
                        else (
                            KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_SCHEMA_HASH
                            if multimodal_graph
                            else (
                                KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_SCHEMA_HASH
                                if document_graph
                                else KNOWLEDGE_RETRIEVAL_CATALOG_SCHEMA_HASH
                            )
                        )
                    ),
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_ARTIFACT_COMMIT_FAILED",
                "Evidence Bundle context Artifact commit failed",
            ) from exc

    def _commit_manifest(
        self, request: EducationRetrievalRequestV2, manifest: EvidenceManifestContract
    ) -> CatalogArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="evidence-manifest.", dir=self.settings.staging_root
            ) as raw_directory:
                source = Path(raw_directory) / "manifest.json"
                source.write_bytes(canonical_json_bytes(manifest))
                source.chmod(0o640)
                return self.artifacts.commit_file_set(
                    files={"evidence/manifest.json": source},
                    primary_file="evidence/manifest.json",
                    artifact_type="evidence-bundle-manifest",
                    idempotency_key=f"evidence-manifest:{request.retrieval_request_id}",
                    request={
                        "retrieval_request_id": request.retrieval_request_id,
                        "request_sha256": request.request_sha256,
                    },
                    result={
                        "evidence_bundle_revision_id": manifest.evidence_bundle_revision_id,
                        "manifest_sha256": manifest.manifest_sha256,
                    },
                    file_metadata={
                        "evidence/manifest.json": {
                            "schema_ref": (
                                "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
                                if isinstance(manifest, EvidenceBundleManifestV5)
                                else (
                                    "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
                                    if isinstance(manifest, EvidenceBundleManifestV4)
                                    else (
                                        "eom://schemas/knowledge/evidence-bundle-manifest/3.0"
                                        if isinstance(manifest, EvidenceBundleManifestV3)
                                        else "eom://schemas/knowledge/evidence-bundle-manifest/2.0"
                                    )
                                )
                            ),
                            "media_type": "application/json",
                        }
                    },
                    manifest_version="evidence-bundle-manifest-file-set/1.0",
                    protocol_version=(
                        KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_PROTOCOL
                        if isinstance(manifest, EvidenceBundleManifestV5)
                        else (
                            KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL
                            if isinstance(manifest, EvidenceBundleManifestV4)
                            else (
                                KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL
                                if isinstance(manifest, EvidenceBundleManifestV3)
                                else KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL
                            )
                        )
                    ),
                    protocol_schema_hash=(
                        KNOWLEDGE_RETRIEVAL_SOLUTION_CATALOG_SCHEMA_HASH
                        if isinstance(manifest, EvidenceBundleManifestV5)
                        else (
                            KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_SCHEMA_HASH
                            if isinstance(manifest, EvidenceBundleManifestV4)
                            else (
                                KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_SCHEMA_HASH
                                if isinstance(manifest, EvidenceBundleManifestV3)
                                else KNOWLEDGE_RETRIEVAL_CATALOG_SCHEMA_HASH
                            )
                        )
                    ),
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_ARTIFACT_COMMIT_FAILED",
                "Evidence Bundle manifest Artifact commit failed",
            ) from exc

    def _commit_database(
        self,
        *,
        command: CreateEvidenceBundleCommand,
        request: EducationRetrievalRequestV2,
        manifest: EvidenceManifestContract,
        context_artifact: CatalogArtifact,
        manifest_artifact: CatalogArtifact,
    ) -> EvidencePublicationContract:
        with transaction(self.sessions) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": command.idempotency_key},
            )
            existing = session.scalar(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key == command.idempotency_key
                )
            )
            if existing is not None:
                if existing.submission_sha256 != command.submission_sha256:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT",
                        "retrieval idempotency key has different input",
                    )
                revision = session.scalar(
                    select(EvidenceBundleRevisionRecord).where(
                        EvidenceBundleRevisionRecord.retrieval_request_id
                        == existing.retrieval_request_id
                    )
                )
                if revision is None:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                        "retrieval request has no published Evidence Bundle",
                    )
                return self._result(session, existing, revision)
            self._snapshot_pointer(session, request.graph_snapshot.graph_snapshot_revision_id)
            self._policy(session, request.access_policy_revision_id)
            request_record = EducationRetrievalRequestRecord(
                retrieval_request_id=request.retrieval_request_id,
                idempotency_key=command.idempotency_key,
                submission_sha256=command.submission_sha256,
                request_sha256=request.request_sha256,
                canonical_request=request.model_dump(mode="json"),
                graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
                access_policy_revision_id=request.access_policy_revision_id,
                query_kind=request.query_kind,
                requester_role=request.requester_role,
                requester_operator_id=request.requester_operator_id,
                requester_permissions_sha256=request.requester_permissions_sha256,
                state="PUBLISHED",
                requested_at=request.requested_at,
            )
            bundle = EvidenceBundleRecord(
                evidence_bundle_id=manifest.evidence_bundle_id,
                retrieval_request_id=request.retrieval_request_id,
                current_revision_id=None,
                created_by_operator_id=request.requester_operator_id,
                created_at=manifest.created_at,
            )
            session.add_all([request_record, bundle])
            session.flush()
            revision = EvidenceBundleRevisionRecord(
                evidence_bundle_revision_id=manifest.evidence_bundle_revision_id,
                evidence_bundle_id=manifest.evidence_bundle_id,
                revision_number=manifest.revision_number,
                retrieval_request_id=request.retrieval_request_id,
                graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
                access_policy_revision_id=request.access_policy_revision_id,
                requester_permissions_sha256=request.requester_permissions_sha256,
                state="PUBLISHED",
                context_artifact_id=context_artifact.artifact_id,
                context_artifact_revision_id=context_artifact.revision_id,
                context_sha256=context_artifact.content_hash,
                manifest_artifact_id=manifest_artifact.artifact_id,
                manifest_artifact_revision_id=manifest_artifact.revision_id,
                manifest_sha256=manifest.manifest_sha256,
                document_count=manifest.budget.document_count,
                item_revision_count=manifest.budget.item_revision_count,
                graph_node_count=manifest.budget.graph_node_count,
                claim_count=manifest.budget.claim_count,
                estimated_context_tokens=manifest.budget.estimated_context_tokens,
                created_by_operator_id=request.requester_operator_id,
                created_at=manifest.created_at,
            )
            session.add(revision)
            session.flush()
            for entry in manifest.entries:
                source = entry.source
                member = source.artifact_member
                session.add(
                    EvidenceBundleEntryRecord(
                        evidence_bundle_revision_id=manifest.evidence_bundle_revision_id,
                        evidence_id=entry.evidence_id,
                        evidence_kind=entry.evidence_kind,
                        evidence_use=entry.use,
                        source_kind=source.source_kind,
                        source_class=source.source_class,
                        intake_batch_id=getattr(source, "intake_batch_id", None),
                        source_file_id=getattr(source, "source_file_id", None),
                        item_id=getattr(source, "item_id", None),
                        item_revision_id=getattr(source, "item_revision_id", None),
                        educational_document_id=getattr(source, "document_id", None),
                        educational_document_revision_id=getattr(
                            source, "document_revision_id", None
                        ),
                        source_artifact_id=member.artifact_id,
                        source_artifact_revision_id=member.artifact_revision_id,
                        source_member_path=member.member_path,
                        source_sha256=member.sha256,
                        source_bytes=member.bytes,
                        source_schema_ref=member.schema_ref,
                        source_media_type=member.media_type,
                        source_logical_name=member.logical_name,
                        graph_node_ids=list(entry.graph_node_ids),
                        anchor_ids=list(entry.anchor_ids),
                        relevance_milli=entry.relevance_milli,
                        answer_bearing=entry.answer_bearing,
                    )
                )
            bundle.current_revision_id = revision.evidence_bundle_revision_id
            session.flush()
            return self._result(session, request_record, revision)

    @staticmethod
    def _result(
        session: Session,
        request: EducationRetrievalRequestRecord,
        revision: EvidenceBundleRevisionRecord,
    ) -> EvidencePublicationContract:
        request_model = EducationRetrievalRequestV2.model_validate(request.canonical_request)
        policy = session.get(
            EducationRetrievalAccessPolicyRevisionRecord, revision.access_policy_revision_id
        )
        artifact_revision = session.get(
            ArtifactRevisionRecord, revision.manifest_artifact_revision_id
        )
        context_revision = session.get(
            ArtifactRevisionRecord, revision.context_artifact_revision_id
        )
        if (
            policy is None
            or artifact_revision is None
            or context_revision is None
            or policy.content_sha256 != request_model.access_policy_sha256
            or not artifact_revision.approved
            or artifact_revision.logical_artifact_id != revision.manifest_artifact_id
            or not context_revision.approved
            or context_revision.logical_artifact_id != revision.context_artifact_id
            or context_revision.content_hash != revision.context_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
                "published Evidence Bundle pointers do not resolve",
            )
        manifest_schema_ref = _artifact_member_schema_ref(
            artifact_revision,
            member_path="evidence/manifest.json",
            allowed=frozenset(
                {
                    "eom://schemas/knowledge/evidence-bundle-manifest/2.0",
                    "eom://schemas/knowledge/evidence-bundle-manifest/3.0",
                    "eom://schemas/knowledge/evidence-bundle-manifest/4.0",
                    "eom://schemas/knowledge/evidence-bundle-manifest/5.0",
                }
            ),
        )
        value: dict[str, Any] = {
            "schema_version": "evidence-bundle-publication-result/1.0",
            "evidence_bundle_id": revision.evidence_bundle_id,
            "evidence_bundle_revision_id": revision.evidence_bundle_revision_id,
            "revision_number": revision.revision_number,
            "state": revision.state,
            "retrieval_request_id": request.retrieval_request_id,
            "retrieval_request_sha256": request.request_sha256,
            "graph_snapshot": request_model.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": revision.access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "manifest_artifact": KnowledgeArtifactMemberPointer(
                artifact_id=revision.manifest_artifact_id,
                artifact_revision_id=revision.manifest_artifact_revision_id,
                sha256=artifact_revision.content_hash,
                schema_ref=manifest_schema_ref,
                media_type="application/json",
                logical_name="manifest.json",
                member_path="evidence/manifest.json",
            ).model_dump(mode="json"),
            "manifest_sha256": revision.manifest_sha256,
            "budget": {
                "document_count": revision.document_count,
                "item_revision_count": revision.item_revision_count,
                "graph_node_count": revision.graph_node_count,
                "claim_count": revision.claim_count,
                "estimated_context_tokens": revision.estimated_context_tokens,
            },
            "published_at": _utc_json(revision.created_at),
            "result_sha256": "sha256:" + "0" * 64,
        }
        if manifest_schema_ref.endswith(("/3.0", "/4.0", "/5.0")):
            value.update(
                {
                    "schema_version": (
                        "evidence-bundle-publication-result/5.0"
                        if manifest_schema_ref.endswith("/5.0")
                        else (
                            "evidence-bundle-publication-result/4.0"
                            if manifest_schema_ref.endswith("/4.0")
                            else "evidence-bundle-publication-result/3.0"
                        )
                    ),
                    "requester_permissions_sha256": revision.requester_permissions_sha256,
                    "context_artifact": KnowledgeArtifactMemberPointer(
                        artifact_id=revision.context_artifact_id,
                        artifact_revision_id=revision.context_artifact_revision_id,
                        sha256=revision.context_sha256,
                        schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
                        media_type="text/markdown",
                        logical_name="context.md",
                        member_path="evidence/context.md",
                    ).model_dump(mode="json"),
                }
            )
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        if manifest_schema_ref.endswith("/5.0"):
            validate_contract("evidence-bundle-publication-result-v5", value)
            return EvidenceBundlePublicationResultV5.model_validate(value)
        if manifest_schema_ref.endswith("/4.0"):
            validate_contract("evidence-bundle-publication-result-v4", value)
            return EvidenceBundlePublicationResultV4.model_validate(value)
        if manifest_schema_ref.endswith("/3.0"):
            validate_contract("evidence-bundle-publication-result-v3", value)
            return EvidenceBundlePublicationResultV3.model_validate(value)
        validate_contract("evidence-bundle-publication-result", value)
        return EvidenceBundlePublicationResult.model_validate(value)

    def _result_v2(
        self,
        session: Session,
        request: EducationRetrievalRequestRecord,
        revision: EvidenceBundleRevisionRecord,
    ) -> ItemProductionEvidencePublicationContract:
        base = self._result(session, request, revision)
        if isinstance(
            base,
            EvidenceBundlePublicationResultV3
            | EvidenceBundlePublicationResultV4
            | EvidenceBundlePublicationResultV5,
        ):
            return base
        context_revision = session.get(
            ArtifactRevisionRecord, revision.context_artifact_revision_id
        )
        if (
            context_revision is None
            or not context_revision.approved
            or context_revision.logical_artifact_id != revision.context_artifact_id
            or context_revision.content_hash != revision.context_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
                "Evidence Bundle context pointer does not resolve",
            )
        value: dict[str, Any] = {
            **base.model_dump(mode="json", exclude={"schema_version", "result_sha256"}),
            "schema_version": "evidence-bundle-publication-result/2.0",
            "requester_permissions_sha256": revision.requester_permissions_sha256,
            "context_artifact": KnowledgeArtifactMemberPointer(
                artifact_id=revision.context_artifact_id,
                artifact_revision_id=revision.context_artifact_revision_id,
                sha256=revision.context_sha256,
                schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
                media_type="text/markdown",
                logical_name="context.md",
                member_path="evidence/context.md",
            ).model_dump(mode="json"),
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        validate_contract("evidence-bundle-publication-result-v2", value)
        return EvidenceBundlePublicationResultV2.model_validate(value)
