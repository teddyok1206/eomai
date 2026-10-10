"""Bounded owner snapshot values and closure checks, never authorization tokens.

Catalog must independently reconstruct the population and authenticate the actual
operator on every operation. These pure checks establish identity, not permission.
"""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, TypeAdapter, model_validator

from eom_catalog_contracts.inference_transfer_experiment import (
    BoundedLimitation,
    ExperimentViewRecipe,
    PopulationSource,
    StagedExperimentEntry,
    SuppliedGraphBaseline,
    population_sha256,
    profile_key,
    profile_set_sha256,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MAX_SNAPSHOT_FRAME_BYTES = 3 * 1024**2
type SourceCount = Annotated[int, Field(ge=0, le=1024, strict=True)]
type ItemRevisionId = Annotated[str, Field(pattern=r"^itemrev_[0-9a-f]{32}$")]


def _canonical_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError(f"{field} differs from canonical snapshot content")
    _encoded_bound(value, MAX_SNAPSHOT_FRAME_BYTES)


def _encoded_bound(value: FrozenModel, maximum: int) -> None:
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > maximum:
        raise ValueError("snapshot encoded frame exceeds its byte budget")


def _canonical_index(entries: tuple[InferenceTransferSnapshotIndexEntry, ...]) -> None:
    runs = tuple(entry.base_analysis_run_id for entry in entries)
    if runs != tuple(sorted(set(runs))):
        raise ValueError("snapshot index must be sorted by unique base analysis run")
    revisions = tuple(entry.source_item_revision_id for entry in entries)
    if len(revisions) != len(set(revisions)):
        raise ValueError("snapshot index repeats an Item revision")
    profiles = tuple(entry.profile for entry in entries if entry.profile is not None)
    if len(profiles) != len(set(profiles)):
        raise ValueError("snapshot index repeats a profile")


def snapshot_index_sha256(entries: tuple[InferenceTransferSnapshotIndexEntry, ...]) -> str:
    """Order-stable compact identity, not a source-authorization proof."""
    return content_sha256(
        [
            entry.model_dump(mode="json")
            for entry in sorted(entries, key=lambda e: e.base_analysis_run_id)
        ]
    )


def snapshot_entry_set_sha256(entries: tuple[StagedExperimentEntry, ...]) -> str:
    return content_sha256(
        [
            entry.model_dump(mode="json")
            for entry in sorted(
                entries,
                key=lambda e: profile_key(InferenceTransferProfilePointer.from_profile(e.profile)),
            )
        ]
    )


def snapshot_baseline_set_sha256(baselines: tuple[SuppliedGraphBaseline, ...]) -> str:
    return content_sha256(
        [
            baseline.model_dump(mode="json")
            for baseline in sorted(baselines, key=lambda row: profile_key(row.query))
        ]
    )


class InferenceTransferSnapshotChunkBudget(FrozenModel):
    max_entries: int = Field(ge=1, le=64, strict=True)
    max_encoded_bytes: int = Field(ge=1024, le=MAX_SNAPSHOT_FRAME_BYTES, strict=True)


class InferenceTransferSnapshotPrepareRequest(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-prepare/1.0"] = (
        "inference-transfer-snapshot-prepare/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    phase: Literal["PREPARE"] = "PREPARE"
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    population_scope: Literal["ALL_ADMITTED_GRAPH_ITEMS", "OCCURRENCE_BACKED_PAST_EXAM"]
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    recipe: ExperimentViewRecipe
    baseline_recipe: Literal["canonical-question-lexical-terms/1.0"] = (
        "canonical-question-lexical-terms/1.0"
    )
    projection_version: Literal["accepted-solution-comparison/1.0"] = (
        "accepted-solution-comparison/1.0"
    )
    max_sources: int = Field(ge=1, le=1024, strict=True)
    query_item_revision_ids: tuple[ItemRevisionId, ...] = Field(max_length=16)
    chunk_budget: InferenceTransferSnapshotChunkBudget
    prepare_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotPrepareRequest:
        if self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256:
            raise ValueError("snapshot Graph artifact and manifest hash differ")
        if self.source_classes != tuple(sorted(set(self.source_classes))):
            raise ValueError("snapshot source classes must be sorted and unique")
        if self.query_item_revision_ids != tuple(sorted(set(self.query_item_revision_ids))):
            raise ValueError("snapshot query Item revisions must be sorted and unique")
        if self.population_scope == "OCCURRENCE_BACKED_PAST_EXAM" and self.source_classes != (
            "PAST_EXAM",
        ):
            raise ValueError("occurrence-backed past-exam scope requires only PAST_EXAM")
        _canonical_hash(self, "prepare_sha256")
        return self


class InferenceTransferSnapshotHeader(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-header/1.0"] = (
        "inference-transfer-snapshot-header/1.0"
    )
    prepare: InferenceTransferSnapshotPrepareRequest
    actor_id: ActorId
    source_count: SourceCount
    profile_count: SourceCount
    missing_report_count: SourceCount
    population_sha256: Sha256
    eligible_profile_set_sha256: Sha256
    index_sha256: Sha256
    header_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotHeader:
        if self.source_count != self.profile_count + self.missing_report_count:
            raise ValueError("snapshot source/report counts do not close")
        if self.source_count > self.prepare.max_sources:
            raise ValueError("snapshot exceeds its source budget")
        _canonical_hash(self, "header_sha256")
        return self


class InferenceTransferSnapshotIndexEntry(FrozenModel):
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    source_item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    source_item_revision_id: ItemRevisionId
    source_value_sha256: Sha256
    profile: InferenceTransferProfilePointer | None
    solution_evidence_pointer_sha256: Sha256 | None

    @model_validator(mode="after")
    def report_presence(self) -> InferenceTransferSnapshotIndexEntry:
        if (self.profile is None) != (self.solution_evidence_pointer_sha256 is None):
            raise ValueError("snapshot report/profile pointer presence differs")
        return self


def _validate_index(
    header: InferenceTransferSnapshotHeader,
    index: tuple[InferenceTransferSnapshotIndexEntry, ...],
) -> None:
    _canonical_index(index)
    profiles = tuple(row.profile for row in index if row.profile is not None)
    if len(index) != header.source_count or len(profiles) != header.profile_count:
        raise ValueError("snapshot index counts differ from its header")
    if snapshot_index_sha256(index) != header.index_sha256:
        raise ValueError("snapshot index hash differs from its header")
    if profile_set_sha256(profiles) != header.eligible_profile_set_sha256:
        raise ValueError("snapshot profile set hash differs from its header")
    if not set(header.prepare.query_item_revision_ids).issubset(
        {entry.source_item_revision_id for entry in index}
    ):
        raise ValueError("snapshot query is outside its source population")


class InferenceTransferSnapshotPrepareResult(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-prepare-result/1.0"] = (
        "inference-transfer-snapshot-prepare-result/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    phase: Literal["PREPARE"] = "PREPARE"
    header: InferenceTransferSnapshotHeader
    index: tuple[InferenceTransferSnapshotIndexEntry, ...] = Field(max_length=1024)
    result_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotPrepareResult:
        _validate_index(self.header, self.index)
        _canonical_hash(self, "result_sha256")
        return self


class InferenceTransferSnapshotReadRequest(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-read/1.0"] = (
        "inference-transfer-snapshot-read/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    phase: Literal["READ"] = "READ"
    header: InferenceTransferSnapshotHeader
    selected_index_entries: tuple[InferenceTransferSnapshotIndexEntry, ...] = Field(
        min_length=1, max_length=64
    )
    read_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotReadRequest:
        _canonical_index(self.selected_index_entries)
        if len(self.selected_index_entries) > self.header.prepare.chunk_budget.max_entries:
            raise ValueError("snapshot chunk exceeds its entry budget")
        _canonical_hash(self, "read_sha256")
        _encoded_bound(self, self.header.prepare.chunk_budget.max_encoded_bytes)
        return self


class InferenceTransferSnapshotRecord(FrozenModel):
    index_entry: InferenceTransferSnapshotIndexEntry
    source: PopulationSource
    staged_entry: StagedExperimentEntry | None

    @model_validator(mode="after")
    def source_closure(self) -> InferenceTransferSnapshotRecord:
        index = self.index_entry
        if (self.source.item_id, self.source.item_revision_id) != (
            index.source_item_id,
            index.source_item_revision_id,
        ) or content_sha256(self.source.model_dump(mode="json")) != index.source_value_sha256:
            raise ValueError("snapshot full source differs from its index")
        if (self.staged_entry is None) != (index.profile is None):
            raise ValueError("snapshot missing report and staged entry presence differ")
        if self.staged_entry is not None:
            profile = self.staged_entry.profile
            basis = profile.source_basis
            if InferenceTransferProfilePointer.from_profile(profile) != index.profile:
                raise ValueError("snapshot staged profile differs from its exact index pointer")
            if (
                basis.solution_evidence.base_analysis_run_id != index.base_analysis_run_id
                or basis.solution_evidence.pointer_sha256 != index.solution_evidence_pointer_sha256
            ):
                raise ValueError("snapshot accepted report differs from its index")
            # V3 retains the full occurrence/page chain; a profile intentionally
            # uses core V2 identity. Never drop the V3 bytes from source hashing.
            if any(
                getattr(self.source, field) != getattr(basis.source, field)
                for field in (
                    "source_kind",
                    "source_class",
                    "item_id",
                    "item_revision_id",
                    "lifecycle_state",
                    "artifact_member",
                )
            ):
                raise ValueError("snapshot profile core source differs from full source")
            if profile.extraction.method != "DETERMINISTIC_REPORT_PROJECTION":
                raise ValueError("snapshot has no accepted Codex-derived producer boundary")
        return self


class InferenceTransferSnapshotReadResult(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-read-result/1.0"] = (
        "inference-transfer-snapshot-read-result/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    phase: Literal["READ"] = "READ"
    header_sha256: Sha256
    read_sha256: Sha256
    records: tuple[InferenceTransferSnapshotRecord, ...] = Field(min_length=1, max_length=64)
    baselines: tuple[SuppliedGraphBaseline, ...] = Field(max_length=16)
    limitations: tuple[BoundedLimitation, ...] = Field(max_length=32)
    result_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotReadResult:
        _canonical_index(tuple(record.index_entry for record in self.records))
        keys = tuple(profile_key(row.query) for row in self.baselines)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("snapshot baseline queries must be sorted and unique")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("snapshot limitations must be unique")
        if any(not row.ordered_candidates for row in self.baselines) and not self.limitations:
            raise ValueError("empty official baseline requires an explicit limitation")
        _canonical_hash(self, "result_sha256")
        return self


class InferenceTransferSnapshotAuthorizeRequest(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-authorize/1.0"] = (
        "inference-transfer-snapshot-authorize/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    phase: Literal["AUTHORIZE"] = "AUTHORIZE"
    header: InferenceTransferSnapshotHeader
    staged_entry_set_sha256: Sha256
    staged_baseline_set_sha256: Sha256
    authorization_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotAuthorizeRequest:
        _canonical_hash(self, "authorization_sha256")
        return self


class InferenceTransferSnapshotAuthorizeResult(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-authorize-result/1.0"] = (
        "inference-transfer-snapshot-authorize-result/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    phase: Literal["AUTHORIZE"] = "AUTHORIZE"
    header_sha256: Sha256
    authorization_sha256: Sha256
    source_count: SourceCount
    profile_count: SourceCount
    missing_report_count: SourceCount
    staged_entry_set_sha256: Sha256
    staged_baseline_set_sha256: Sha256
    status: Literal["AUTHORIZED_CURRENT_READ"] = "AUTHORIZED_CURRENT_READ"
    result_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> InferenceTransferSnapshotAuthorizeResult:
        if self.source_count != self.profile_count + self.missing_report_count:
            raise ValueError("snapshot authorization source/report counts do not close")
        _canonical_hash(self, "result_sha256")
        return self


type InferenceTransferSnapshotRequest = Annotated[
    InferenceTransferSnapshotPrepareRequest
    | InferenceTransferSnapshotReadRequest
    | InferenceTransferSnapshotAuthorizeRequest,
    Field(discriminator="phase"),
]
type InferenceTransferSnapshotResult = Annotated[
    InferenceTransferSnapshotPrepareResult
    | InferenceTransferSnapshotReadResult
    | InferenceTransferSnapshotAuthorizeResult,
    Field(discriminator="phase"),
]


def validate_snapshot_prepare_result(
    request: InferenceTransferSnapshotPrepareRequest,
    result: InferenceTransferSnapshotPrepareResult,
) -> None:
    request = InferenceTransferSnapshotPrepareRequest.model_validate(
        request.model_dump(mode="json")
    )
    result = InferenceTransferSnapshotPrepareResult.model_validate(result.model_dump(mode="json"))
    if result.header.prepare != request:
        raise ValueError("snapshot prepare result is bound to a different request")


def validate_snapshot_read_result(
    request: InferenceTransferSnapshotReadRequest,
    result: InferenceTransferSnapshotReadResult,
    *,
    index: tuple[InferenceTransferSnapshotIndexEntry, ...],
) -> None:
    request = InferenceTransferSnapshotReadRequest.model_validate(request.model_dump(mode="json"))
    result = InferenceTransferSnapshotReadResult.model_validate(result.model_dump(mode="json"))
    index = tuple(
        InferenceTransferSnapshotIndexEntry.model_validate(row.model_dump(mode="json"))
        for row in index
    )
    _validate_index(request.header, index)
    index_map = {row.base_analysis_run_id: row for row in index}
    if any(
        index_map.get(row.base_analysis_run_id) != row for row in request.selected_index_entries
    ):
        raise ValueError("snapshot chunk selects a foreign index entry")
    _check_snapshot_read_context(request, result)
    eligible = {row.profile for row in index if row.profile is not None}
    if any(not set(row.ordered_candidates).issubset(eligible) for row in result.baselines):
        raise ValueError("snapshot baseline query/candidate is outside exact eligible profiles")


def validate_snapshot_read_result_context(
    request: InferenceTransferSnapshotReadRequest,
    result: InferenceTransferSnapshotReadResult,
) -> None:
    """Check chunk-local identity; only the owner can check full index membership."""
    request = InferenceTransferSnapshotReadRequest.model_validate(request.model_dump(mode="json"))
    result = InferenceTransferSnapshotReadResult.model_validate(result.model_dump(mode="json"))
    _check_snapshot_read_context(request, result)


def _check_snapshot_read_context(
    request: InferenceTransferSnapshotReadRequest,
    result: InferenceTransferSnapshotReadResult,
) -> None:
    if (result.header_sha256, result.read_sha256) != (
        request.header.header_sha256,
        request.read_sha256,
    ):
        raise ValueError("snapshot read result is bound to a different header/request")
    if tuple(record.index_entry for record in result.records) != request.selected_index_entries:
        raise ValueError("snapshot read records differ from the exact selected chunk")
    selected_queries: set[InferenceTransferProfilePointer] = set()
    missing_query = False
    for record in result.records:
        _validate_record_scope(request.header, record)
        if record.source.item_revision_id in request.header.prepare.query_item_revision_ids:
            if record.index_entry.profile is None:
                missing_query = True
            else:
                selected_queries.add(record.index_entry.profile)
    for baseline in result.baselines:
        if baseline.query not in selected_queries:
            raise ValueError("snapshot baseline query is outside the exact requested chunk")
    if (
        missing_query or selected_queries - {row.query for row in result.baselines}
    ) and not result.limitations:
        raise ValueError("unavailable requested query baseline requires an explicit limitation")
    _encoded_bound(result, request.header.prepare.chunk_budget.max_encoded_bytes)


def _validate_record_scope(
    header: InferenceTransferSnapshotHeader, record: InferenceTransferSnapshotRecord
) -> None:
    if record.source.source_class not in header.prepare.source_classes:
        raise ValueError("snapshot record source class is outside the requested scope")
    if (
        record.staged_entry is not None
        and record.staged_entry.profile.source_basis.graph_snapshot != header.prepare.graph_snapshot
    ):
        raise ValueError("snapshot profile Graph differs from the exact prepared Graph")
    if (
        record.staged_entry is not None
        and record.staged_entry.profile.extraction.extractor_version
        != header.prepare.projection_version
    ):
        raise ValueError("snapshot profile extraction differs from the exact projection version")


def validate_snapshot_records(
    header: InferenceTransferSnapshotHeader,
    index: tuple[InferenceTransferSnapshotIndexEntry, ...],
    records: tuple[InferenceTransferSnapshotRecord, ...],
) -> None:
    """Close a complete assembly's hashes; owner source authority remains separate."""
    header = InferenceTransferSnapshotHeader.model_validate(header.model_dump(mode="json"))
    index = tuple(
        InferenceTransferSnapshotIndexEntry.model_validate(row.model_dump(mode="json"))
        for row in index
    )
    records = tuple(
        InferenceTransferSnapshotRecord.model_validate(row.model_dump(mode="json"))
        for row in records
    )
    _validate_index(header, index)
    if tuple(row.index_entry for row in records) != index:
        raise ValueError("snapshot full records differ from the complete frozen index")
    if population_sha256(tuple(row.source for row in records)) != header.population_sha256:
        raise ValueError("snapshot full population hash differs from its header")
    for record in records:
        _validate_record_scope(header, record)


def validate_snapshot_authorize_result(
    request: InferenceTransferSnapshotAuthorizeRequest,
    result: InferenceTransferSnapshotAuthorizeResult,
) -> None:
    request = InferenceTransferSnapshotAuthorizeRequest.model_validate(
        request.model_dump(mode="json")
    )
    result = InferenceTransferSnapshotAuthorizeResult.model_validate(result.model_dump(mode="json"))
    if (
        result.header_sha256,
        result.authorization_sha256,
        result.source_count,
        result.profile_count,
        result.missing_report_count,
        result.staged_entry_set_sha256,
        result.staged_baseline_set_sha256,
    ) != (
        request.header.header_sha256,
        request.authorization_sha256,
        request.header.source_count,
        request.header.profile_count,
        request.header.missing_report_count,
        request.staged_entry_set_sha256,
        request.staged_baseline_set_sha256,
    ):
        raise ValueError("snapshot authorization result differs from the exact assembled request")


def parse_snapshot_request(value: object) -> InferenceTransferSnapshotRequest:
    if not isinstance(value, dict):
        raise ValueError("snapshot request must be a JSON object")
    validate_contract("item-inference-transfer-snapshot", value)
    return TypeAdapter(InferenceTransferSnapshotRequest).validate_python(value)


def parse_snapshot_result(value: object) -> InferenceTransferSnapshotResult:
    if not isinstance(value, dict):
        raise ValueError("snapshot result must be a JSON object")
    validate_contract("item-inference-transfer-snapshot", value)
    return TypeAdapter(InferenceTransferSnapshotResult).validate_python(value)
