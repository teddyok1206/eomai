"""Request-local typed decoding of exact immutable past-exam provenance members.

These values are derived indexes, not permissions or canonical sources. The
caller still checks each Item's current approval, decision and lineage. A new
request must use a new cache; no process-global or durable cache is maintained.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, NoReturn

from eom_catalog_contracts import (
    AssessmentItemBoundary,
    AssessmentLayoutObservation,
    AssessmentPageImageInput,
    LegacyAssessmentItemProposal,
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemDecision,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionResult,
    validate_contract,
)

from eom_catalog_service.artifacts import CatalogArtifactReader

MAX_PAST_EXAM_PROVENANCE_CACHE_BYTES = 64 * 1024 * 1024
MAX_PAST_EXAM_PROVENANCE_CACHE_MEMBERS = 1024
MAX_PAST_EXAM_PROVENANCE_CACHE_INDEX_ROWS = 100_000


@dataclass(frozen=True, slots=True)
class PastExamProvenanceMember:
    artifact_id: str
    artifact_revision_id: str
    member_path: str
    sha256: str
    schema_ref: str
    media_type: str
    max_bytes: int


def _group[K: Hashable, V](
    values: tuple[V, ...], key: Callable[[V], K]
) -> Mapping[K, tuple[V, ...]]:
    grouped: dict[K, list[V]] = {}
    for value in values:
        grouped.setdefault(key(value), []).append(value)
    # Retain cardinality rather than turning ambiguous provenance into one row.
    return MappingProxyType({identity: tuple(rows) for identity, rows in grouped.items()})


@dataclass(frozen=True, slots=True)
class PastExamBatchProvenance:
    value: LegacyItemExtractionBatchManifestV2
    work_units_by_id: Mapping[str, tuple[LegacyExtractionBatchWorkUnitV2, ...]]


@dataclass(frozen=True, slots=True)
class PastExamAcceptanceProvenance:
    value: LegacyItemExtractionAcceptance
    decisions_by_item: Mapping[tuple[str, int], tuple[LegacyItemDecision, ...]]


@dataclass(frozen=True, slots=True)
class PastExamResultProvenance:
    value: LegacyItemExtractionResult
    proposals_by_item: Mapping[tuple[str, int], tuple[LegacyAssessmentItemProposal, ...]]


@dataclass(frozen=True, slots=True)
class PastExamLayoutProvenance:
    value: AssessmentLayoutObservation
    pages_by_id: Mapping[str, AssessmentPageImageInput]
    pages_by_position: Mapping[tuple[str, int], AssessmentPageImageInput]
    boundaries_by_item: Mapping[int, tuple[AssessmentItemBoundary, ...]]


type _DecodedProvenance = (
    PastExamBatchProvenance
    | PastExamAcceptanceProvenance
    | PastExamResultProvenance
    | PastExamLayoutProvenance
)
type _ProvenanceKind = Literal["BATCH", "ACCEPTANCE", "RESULT", "LAYOUT"]


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON value")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = member
    return value


def _decode(kind: _ProvenanceKind, raw: bytes) -> tuple[_DecodedProvenance, int]:
    value = json.loads(
        raw, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant
    )
    if not isinstance(value, dict):
        raise ValueError("Artifact member is not a JSON object")
    if kind == "BATCH":
        validate_contract("legacy-item-extraction-batch-v2", value)
        batch = LegacyItemExtractionBatchManifestV2.model_validate(value)
        return (
            PastExamBatchProvenance(batch, _group(batch.work_units, lambda row: row.work_unit_id)),
            len(batch.work_units),
        )
    if kind == "ACCEPTANCE":
        validate_contract("legacy-item-extraction-acceptance", value)
        acceptance = LegacyItemExtractionAcceptance.model_validate(value)
        return (
            PastExamAcceptanceProvenance(
                acceptance,
                _group(
                    acceptance.item_decisions, lambda row: (row.item_proposal_id, row.item_number)
                ),
            ),
            len(acceptance.item_decisions),
        )
    if kind == "RESULT":
        validate_contract("legacy-item-extraction-result", value)
        result = LegacyItemExtractionResult.model_validate(value)
        return (
            PastExamResultProvenance(
                result, _group(result.items, lambda row: (row.item_proposal_id, row.item_number))
            ),
            len(result.items),
        )
    validate_contract("assessment-layout-observation", value)
    layout = AssessmentLayoutObservation.model_validate(value)
    return (
        PastExamLayoutProvenance(
            layout,
            MappingProxyType({row.page.page_input_id: row.page for row in layout.pages}),
            # This is the existing resolver's last-position-wins meaning. The
            # schema independently requires page IDs and item numbers unique.
            MappingProxyType(
                {(row.page.source_role, row.page.physical_page): row.page for row in layout.pages}
            ),
            _group(layout.item_boundaries, lambda row: row.item_number),
        ),
        2 * len(layout.pages) + len(layout.item_boundaries),
    )


class PastExamSourceResolutionCache:
    """Bounded successful typed values for one owner read transaction only.

    Retention is capped by source JSON bytes, member count and index row count;
    schema-bounded typed values/indexes are O(retained input). Over-budget values
    are fully validated and returned without retention, never truncated. Raw
    bytes remain owned by the existing Artifact reader/cache.
    """

    def __init__(
        self,
        *,
        max_source_bytes: int = MAX_PAST_EXAM_PROVENANCE_CACHE_BYTES,
        max_members: int = MAX_PAST_EXAM_PROVENANCE_CACHE_MEMBERS,
        max_index_rows: int = MAX_PAST_EXAM_PROVENANCE_CACHE_INDEX_ROWS,
    ) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (max_source_bytes, max_members, max_index_rows)
        ):
            raise ValueError("past-exam cache budgets must be non-negative integers")
        self._maximum_bytes = max_source_bytes
        self._maximum_members = max_members
        self._maximum_rows = max_index_rows
        self._source_bytes = 0
        self._index_rows = 0
        self._members: dict[
            tuple[PastExamProvenanceMember, _ProvenanceKind], _DecodedProvenance
        ] = {}

    def _read(
        self,
        artifacts: CatalogArtifactReader,
        member: PastExamProvenanceMember,
        kind: _ProvenanceKind,
    ) -> _DecodedProvenance:
        key = (member, kind)
        if key in self._members:
            return self._members[key]
        raw = artifacts.read_member(
            artifact_id=member.artifact_id,
            revision_id=member.artifact_revision_id,
            member_path=member.member_path,
            sha256=member.sha256,
            media_type=member.media_type,
            schema_ref=member.schema_ref,
            max_bytes=member.max_bytes,
        )
        if not raw or len(raw) > member.max_bytes:
            raise ValueError("past-exam provenance member exceeds its exact read bound")
        decoded, row_count = _decode(kind, raw)
        # Do not retain a failed read/decode or evict and silently reinterpret a
        # pin. Budget fallback is the same validated value, without caching.
        if (
            len(self._members) < self._maximum_members
            and self._source_bytes + len(raw) <= self._maximum_bytes
            and self._index_rows + row_count <= self._maximum_rows
        ):
            self._members[key] = decoded
            self._source_bytes += len(raw)
            self._index_rows += row_count
        return decoded

    def batch(
        self, artifacts: CatalogArtifactReader, member: PastExamProvenanceMember
    ) -> PastExamBatchProvenance:
        value = self._read(artifacts, member, "BATCH")
        assert isinstance(value, PastExamBatchProvenance)
        return value

    def acceptance(
        self, artifacts: CatalogArtifactReader, member: PastExamProvenanceMember
    ) -> PastExamAcceptanceProvenance:
        value = self._read(artifacts, member, "ACCEPTANCE")
        assert isinstance(value, PastExamAcceptanceProvenance)
        return value

    def result(
        self, artifacts: CatalogArtifactReader, member: PastExamProvenanceMember
    ) -> PastExamResultProvenance:
        value = self._read(artifacts, member, "RESULT")
        assert isinstance(value, PastExamResultProvenance)
        return value

    def layout(
        self, artifacts: CatalogArtifactReader, member: PastExamProvenanceMember
    ) -> PastExamLayoutProvenance:
        value = self._read(artifacts, member, "LAYOUT")
        assert isinstance(value, PastExamLayoutProvenance)
        return value
