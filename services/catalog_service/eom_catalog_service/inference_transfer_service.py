"""Opt-in, Catalog-owned comparison candidates; GraphRAG remains authoritative."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2, KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    InferenceTransferSourceBasis,
)
from eom_identifiers import content_sha256

from eom_catalog_service.inference_transfer_ports import (
    EmbeddingRankerProvenance,
    InferenceTransferCandidateRanker,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope


class InferenceTransferServiceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class InferenceTransferSearchCommand:
    """Application value: actual actor is injected, never taken from model tools."""

    actor_id: str
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str
    access_policy_sha256: str
    query_item_revision_id: str
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = ("PAST_EXAM",)
    topic_keys: tuple[str, ...] = ()
    maximum_candidates: int = 1024
    top_k: int = 8
    population_scope: InferenceTransferPopulationScope = (
        InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS
    )

    def __post_init__(self) -> None:
        if not isinstance(self.population_scope, InferenceTransferPopulationScope):
            raise ValueError("inference transfer population scope must be a typed value")
        if type(self.top_k) is not int or type(self.maximum_candidates) is not int:
            raise ValueError("inference transfer budgets must be integer values")
        if not 1 <= self.top_k <= 64 or not self.top_k <= self.maximum_candidates <= 1024:
            raise ValueError("inference transfer budgets are invalid")
        for values in (self.source_classes, self.topic_keys):
            if values != tuple(sorted(set(values))):
                raise ValueError("inference transfer source/topic selection must be canonical")
        if not self.source_classes or len(self.topic_keys) > 20:
            raise ValueError("inference transfer source/topic selection is invalid")
        if not set(self.source_classes).issubset({"APPROVED_ITEM", "PAST_EXAM"}):
            raise ValueError("inference transfer only supports approved Item source classes")


@dataclass(frozen=True, slots=True)
class AdmittedInferenceTransferSource:
    """Exact authorized pool member, including sources without a solution report."""

    analysis_run_id: str
    source: ApprovedItemKnowledgeSourceV2


@dataclass(frozen=True, slots=True)
class AdmittedInferenceTransferCorpus:
    profiles: tuple[InferenceTransferProfile, ...]
    graph_scores: tuple[tuple[str, int], ...]
    truncated: bool
    missing_solution_reports: int
    sources: tuple[AdmittedInferenceTransferSource, ...]


class InferenceTransferSourcePort(Protocol):
    def load(self, command: InferenceTransferSearchCommand) -> AdmittedInferenceTransferCorpus:
        """Admit actual actor's exact Graph sources before any embedding work."""
        ...

    def reauthorize(
        self,
        command: InferenceTransferSearchCommand,
        corpus: AdmittedInferenceTransferCorpus,
    ) -> None:
        """Reauthorize every returned population pin, not only top-ranked content."""
        ...


@dataclass(frozen=True, slots=True)
class InferenceTransferCandidateResult:
    profile: InferenceTransferProfilePointer
    source_basis: InferenceTransferSourceBasis
    provenance: tuple[Literal["EMBEDDING_POOL", "GRAPH_LEXICAL"], ...]
    cosine_similarity: float | None
    graph_relevance_milli: int | None


@dataclass(frozen=True, slots=True)
class InferenceTransferSearchResult:
    status: Literal["CANDIDATES", "NOT_INDEXED", "UNAVAILABLE"]
    query_profile: InferenceTransferProfilePointer | None
    candidates: tuple[InferenceTransferCandidateResult, ...]
    limitations: tuple[str, ...]
    eligible_profile_count: int
    missing_solution_report_count: int
    truncated: bool
    embedding_provenance: EmbeddingRankerProvenance | None
    eligible_profile_set_sha256: str


def _profile_pointer(profile: InferenceTransferProfile) -> InferenceTransferProfilePointer:
    return InferenceTransferProfilePointer(
        profile_id=profile.profile_id,
        profile_revision_id=profile.profile_revision_id,
        profile_sha256=profile.profile_sha256,
    )


def _same_approved_source_identity(
    left: ApprovedItemKnowledgeSourceV2, right: ApprovedItemKnowledgeSourceV2
) -> bool:
    """Compare the report's core pointer with an admitted visual-source subtype.

    The source adapter separately retains and reauthorizes every full canonical
    source value. ApprovedPastExam V3 adds page lineage that V10 reports do not
    copy; subclass equality must not reject the exact inherited Item/member pin.
    """
    return (
        left.source_kind,
        left.source_class,
        left.item_id,
        left.item_revision_id,
        left.lifecycle_state,
        left.artifact_member,
    ) == (
        right.source_kind,
        right.source_class,
        right.item_id,
        right.item_revision_id,
        right.lifecycle_state,
        right.artifact_member,
    )


class InferenceTransferApplicationService:
    """Merge candidate provenance; never turn a similarity score into an approval."""

    def __init__(
        self,
        sources: InferenceTransferSourcePort,
        ranker: InferenceTransferCandidateRanker | None = None,
    ) -> None:
        self.sources = sources
        self.ranker = ranker

    def search(self, command: InferenceTransferSearchCommand) -> InferenceTransferSearchResult:
        corpus = self.sources.load(command)
        if (
            len(corpus.profiles) + corpus.missing_solution_reports > command.maximum_candidates
            or corpus.missing_solution_reports < 0
            or len(corpus.sources) != len(corpus.profiles) + corpus.missing_solution_reports
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_CORPUS_BUDGET_EXCEEDED")
        sources_by_run = {source.analysis_run_id: source.source for source in corpus.sources}
        if len(sources_by_run) != len(corpus.sources):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_DUPLICATE_SOURCE")
        source_revisions = {source.source.item_revision_id for source in corpus.sources}
        if len(source_revisions) != len(corpus.sources):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_DUPLICATE_SOURCE")
        if any(
            source.source.source_class not in command.source_classes for source in corpus.sources
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_UNADMITTED_SOURCE")
        by_revision: dict[str, InferenceTransferProfile] = {}
        by_pointer: dict[InferenceTransferProfilePointer, InferenceTransferProfile] = {}
        for profile in corpus.profiles:
            # Profiles and small pointers are immutable values, not permission grants.
            profile = InferenceTransferProfile.model_validate(profile.model_dump(mode="json"))
            revision = profile.source_basis.source.item_revision_id
            pointer = _profile_pointer(profile)
            if revision in by_revision or pointer in by_pointer:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_DUPLICATE_PROFILE")
            if profile.source_basis.graph_snapshot != command.graph_snapshot:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_GRAPH_PIN_MISMATCH")
            if profile.source_basis.source.source_class not in command.source_classes:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_UNADMITTED_PROFILE")
            source = sources_by_run.get(profile.source_basis.solution_evidence.base_analysis_run_id)
            if source is None or not _same_approved_source_identity(
                source, profile.source_basis.source
            ):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
            by_revision[revision] = profile
            by_pointer[pointer] = profile
        query = by_revision.get(command.query_item_revision_id)
        profile_set_sha256 = content_sha256(
            [
                pointer.model_dump(mode="json")
                for pointer in sorted(
                    by_pointer,
                    key=lambda value: (
                        value.profile_id,
                        value.profile_revision_id,
                        value.profile_sha256,
                    ),
                )
            ]
        )
        limitations = ["유사도는 후보 검색 신호이며 핵심 착상 전이·표절·정답·승인 판정이 아닙니다."]
        if corpus.truncated:
            limitations.append(
                "권한으로 입장된 Graph source pool이 명시한 후보 상한에서 잘렸습니다."
            )
        if corpus.missing_solution_reports:
            limitations.append("승인 풀이보고서가 없는 source는 비교 profile을 만들지 않았습니다.")
        if query is None:
            self.sources.reauthorize(command, corpus)
            return InferenceTransferSearchResult(
                "NOT_INDEXED",
                None,
                (),
                tuple(limitations),
                len(by_pointer),
                corpus.missing_solution_reports,
                corpus.truncated,
                None,
                profile_set_sha256,
            )
        eligible = tuple(profile for profile in corpus.profiles if profile != query)
        graph_rows = tuple(
            (revision, score)
            for revision, score in corpus.graph_scores
            if revision != command.query_item_revision_id and revision in by_revision
        )
        graph = dict(graph_rows)
        if len(graph) != len(graph_rows):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_DUPLICATE_GRAPH_SCORE")
        provenance: dict[
            InferenceTransferProfilePointer, set[Literal["EMBEDDING_POOL", "GRAPH_LEXICAL"]]
        ] = {}
        cosine: dict[InferenceTransferProfilePointer, float] = {}
        embedding_provenance: EmbeddingRankerProvenance | None = None
        if self.ranker is not None and eligible:
            embedding_provenance = self.ranker.provenance
            if not isinstance(embedding_provenance, EmbeddingRankerProvenance):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_MODEL_PIN_INVALID")
            ranked = self.ranker.rank(query, eligible, top_k=min(command.top_k, len(eligible)))
            if self.ranker.provenance != embedding_provenance:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_MODEL_PIN_MISMATCH")
            if embedding_provenance.kind == "TEST_ONLY":
                limitations.append(
                    "임베딩 점수는 TEST_ONLY 검증 backend에서 나온 값이며 "
                    "운영 모델의 성능 증거가 아닙니다."
                )
            if len(ranked) > command.top_k:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_RANK_BUDGET_EXCEEDED")
            for value in ranked:
                if value.profile not in by_pointer or by_pointer[value.profile] == query:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_UNADMITTED_PROFILE")
                if value.profile in cosine:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_DUPLICATE_RANK")
                cosine[value.profile] = value.cosine_similarity
                provenance[value.profile] = {"EMBEDDING_POOL"}
        elif self.ranker is None:
            limitations.append(
                "로컬 임베딩 모델이 연결되지 않아 벡터 후보 검색은 UNAVAILABLE입니다."
            )
        for revision, _score in sorted(graph.items(), key=lambda pair: (-pair[1], pair[0]))[
            : command.top_k
        ]:
            graph_profile = by_revision.get(revision)
            if graph_profile is not None:
                provenance.setdefault(_profile_pointer(graph_profile), set()).add("GRAPH_LEXICAL")
        # Keep the two bounded channels; do not compare cosine with Graph's milli-score.
        embedding_order = tuple(
            sorted(cosine, key=lambda pointer: (-cosine[pointer], pointer.profile_id))
        )
        graph_order = tuple(
            _profile_pointer(by_revision[revision])
            for revision, _score in sorted(graph.items(), key=lambda pair: (-pair[1], pair[0]))[
                : command.top_k
            ]
            if revision in by_revision
        )
        ordered_values: list[InferenceTransferProfilePointer] = []
        seen: set[InferenceTransferProfilePointer] = set()
        for index in range(max(len(embedding_order), len(graph_order))):
            for channel in (embedding_order, graph_order):
                if index < len(channel) and channel[index] not in seen:
                    pointer = channel[index]
                    seen.add(pointer)
                    ordered_values.append(pointer)
                    if len(ordered_values) == command.top_k:
                        break
            if len(ordered_values) == command.top_k:
                break
        ordered = tuple(ordered_values)
        # Counts and the population hash also describe unselected pool members.
        # A revocation of any member must therefore block the entire result.
        self.sources.reauthorize(command, corpus)
        results = tuple(
            InferenceTransferCandidateResult(
                profile=pointer,
                source_basis=by_pointer[pointer].source_basis,
                provenance=tuple(sorted(provenance[pointer])),
                cosine_similarity=cosine.get(pointer),
                graph_relevance_milli=graph.get(
                    by_pointer[pointer].source_basis.source.item_revision_id
                ),
            )
            for pointer in ordered
        )
        return InferenceTransferSearchResult(
            "CANDIDATES" if results else "UNAVAILABLE",
            _profile_pointer(query),
            results,
            tuple(limitations),
            len(by_pointer),
            corpus.missing_solution_reports,
            corpus.truncated,
            embedding_provenance,
            profile_set_sha256,
        )
