"""Bounded snapshot use case; frozen hashes establish identity, never authority.

The injected Catalog port must authenticate the actual actor and reconstruct the
complete admitted population before materialization. No persistence, filesystem,
SQL, transport or model execution belongs to this application module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eom_catalog_contracts.inference_transfer_experiment import (
    SuppliedGraphBaseline,
    population_sha256,
    profile_set_sha256,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    snapshot_baseline_set_sha256,
    snapshot_entry_set_sha256,
    snapshot_index_sha256,
    validate_snapshot_authorize_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result,
    validate_snapshot_records,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import content_sha256

from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    InferenceTransferServiceError,
)


@dataclass(frozen=True, slots=True)
class AuthorizedSnapshotCapture:
    """Owner-local result, not a wire payload, cache or durable permission proof."""

    corpus: AdmittedInferenceTransferCorpus
    records: tuple[InferenceTransferSnapshotRecord, ...] = ()
    baselines: tuple[SuppliedGraphBaseline, ...] = ()
    limitations: tuple[str, ...] = ()


class InferenceTransferSnapshotSourcePort(Protocol):
    def capture(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotPrepareRequest,
        *,
        expected_header: InferenceTransferSnapshotHeader | None = None,
        selected_index_entries: tuple[InferenceTransferSnapshotIndexEntry, ...] = (),
        materialize_all: bool = False,
    ) -> AuthorizedSnapshotCapture:
        """Reauthenticate and admit full scope before resolving selected exact bytes.

        The actor is trusted application context, never a request/model field.
        The owner compares a rebuilt header and selection before reading bytes.
        Final authorization materializes all entries and requested baselines anew.
        """
        ...


def hashed_snapshot_value[T: FrozenModel](model: type[T], field: str, **values: Any) -> T:
    """Construct one small canonical value; Pydantic revalidates all nested inputs."""
    body = model.model_construct(**values).model_dump(mode="json", exclude={field})
    return model.model_validate(body | {field: content_sha256(body)})


def prepare_snapshot_value(
    actor_id: str,
    request: InferenceTransferSnapshotPrepareRequest,
    corpus: AdmittedInferenceTransferCorpus,
) -> InferenceTransferSnapshotPrepareResult:
    """Freeze the complete admitted denominator without reading canonical Item bytes."""
    request = InferenceTransferSnapshotPrepareRequest.model_validate(
        request.model_dump(mode="json")
    )
    if corpus.truncated:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED")
    if (
        len(corpus.sources) > request.max_sources
        or corpus.missing_solution_reports < 0
        or len(corpus.sources) != len(corpus.profiles) + corpus.missing_solution_reports
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_POPULATION_INVALID")
    by_run: dict[str, InferenceTransferProfile] = {}
    profile_keys: set[InferenceTransferProfilePointer] = set()
    for value in corpus.profiles:
        profile = InferenceTransferProfile.model_validate(value.model_dump(mode="json"))
        run_id = profile.source_basis.solution_evidence.base_analysis_run_id
        pointer = InferenceTransferProfilePointer.from_profile(profile)
        if run_id in by_run or pointer in profile_keys:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_DUPLICATE_PROFILE")
        if (
            profile.source_basis.graph_snapshot != request.graph_snapshot
            or profile.extraction.method != "DETERMINISTIC_REPORT_PROJECTION"
            or profile.extraction.extractor_version != request.projection_version
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        by_run[run_id] = profile
        profile_keys.add(pointer)
    index: list[InferenceTransferSnapshotIndexEntry] = []
    sources = []
    for member in sorted(corpus.sources, key=lambda value: value.analysis_run_id):
        source = type(member.source).model_validate(member.source.model_dump(mode="json"))
        if source.source_class not in request.source_classes:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_UNADMITTED_SOURCE")
        admitted_profile = by_run.get(member.analysis_run_id)
        if admitted_profile is not None and any(
            getattr(source, field) != getattr(admitted_profile.source_basis.source, field)
            for field in (
                "source_kind",
                "source_class",
                "item_id",
                "item_revision_id",
                "lifecycle_state",
                "artifact_member",
            )
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
        sources.append(source)
        index.append(
            InferenceTransferSnapshotIndexEntry(
                base_analysis_run_id=member.analysis_run_id,
                source_item_id=source.item_id,
                source_item_revision_id=source.item_revision_id,
                source_value_sha256=content_sha256(source.model_dump(mode="json")),
                profile=None
                if admitted_profile is None
                else InferenceTransferProfilePointer.from_profile(admitted_profile),
                solution_evidence_pointer_sha256=None
                if admitted_profile is None
                else admitted_profile.source_basis.solution_evidence.pointer_sha256,
            )
        )
    if not set(by_run).issubset({row.base_analysis_run_id for row in index}):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_UNADMITTED_PROFILE")
    frozen_index = tuple(index)
    header = hashed_snapshot_value(
        InferenceTransferSnapshotHeader,
        "header_sha256",
        prepare=request,
        actor_id=actor_id,
        source_count=len(sources),
        profile_count=len(by_run),
        missing_report_count=corpus.missing_solution_reports,
        population_sha256=population_sha256(tuple(sources)),
        eligible_profile_set_sha256=profile_set_sha256(tuple(profile_keys)),
        index_sha256=snapshot_index_sha256(frozen_index),
    )
    result = hashed_snapshot_value(
        InferenceTransferSnapshotPrepareResult,
        "result_sha256",
        header=header,
        index=frozen_index,
    )
    validate_snapshot_prepare_result(request, result)
    return result


def validate_snapshot_selection(
    current: InferenceTransferSnapshotPrepareResult,
    expected: InferenceTransferSnapshotHeader | None,
    selected: tuple[InferenceTransferSnapshotIndexEntry, ...],
) -> None:
    """Check current population before dereferencing any selected source member."""
    if expected is not None and current.header != expected:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_CHANGED")
    by_run = {row.base_analysis_run_id: row for row in current.index}
    if any(by_run.get(row.base_analysis_run_id) != row for row in selected):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID")


class InferenceTransferSnapshotApplicationService:
    """Prepare, read and reauthorize one bounded exact corpus; no runtime activation."""

    def __init__(self, sources: InferenceTransferSnapshotSourcePort) -> None:
        self.sources = sources

    def prepare(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotPrepareRequest,
    ) -> InferenceTransferSnapshotPrepareResult:
        request = InferenceTransferSnapshotPrepareRequest.model_validate(
            request.model_dump(mode="json")
        )
        capture = self.sources.capture(actor_id, request)
        return prepare_snapshot_value(actor_id, request, capture.corpus)

    @staticmethod
    def _actor(actor_id: str, header: InferenceTransferSnapshotHeader) -> None:
        if actor_id != header.actor_id:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")

    def read(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotReadRequest,
    ) -> InferenceTransferSnapshotReadResult:
        request = InferenceTransferSnapshotReadRequest.model_validate(
            request.model_dump(mode="json")
        )
        self._actor(actor_id, request.header)
        capture = self.sources.capture(
            actor_id,
            request.header.prepare,
            expected_header=request.header,
            selected_index_entries=request.selected_index_entries,
        )
        current = prepare_snapshot_value(actor_id, request.header.prepare, capture.corpus)
        validate_snapshot_selection(current, request.header, request.selected_index_entries)
        result = hashed_snapshot_value(
            InferenceTransferSnapshotReadResult,
            "result_sha256",
            header_sha256=request.header.header_sha256,
            read_sha256=request.read_sha256,
            records=capture.records,
            baselines=capture.baselines,
            limitations=capture.limitations,
        )
        validate_snapshot_read_result(request, result, index=current.index)
        return result

    def authorize(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotAuthorizeRequest,
    ) -> InferenceTransferSnapshotAuthorizeResult:
        request = InferenceTransferSnapshotAuthorizeRequest.model_validate(
            request.model_dump(mode="json")
        )
        self._actor(actor_id, request.header)
        capture = self.sources.capture(
            actor_id,
            request.header.prepare,
            expected_header=request.header,
            materialize_all=True,
        )
        current = prepare_snapshot_value(actor_id, request.header.prepare, capture.corpus)
        validate_snapshot_selection(current, request.header, ())
        validate_snapshot_records(current.header, current.index, capture.records)
        # Validate official query/candidate closure across the complete assembly,
        # without forcing the full corpus into a wire chunk.
        eligible = {row.profile for row in current.index if row.profile is not None}
        query_profiles = {
            row.profile
            for row in current.index
            if row.source_item_revision_id in request.header.prepare.query_item_revision_ids
            and row.profile is not None
        }
        if any(
            row.query not in query_profiles or not set(row.ordered_candidates).issubset(eligible)
            for row in capture.baselines
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_BASELINE_INVALID")
        if len({row.query for row in capture.baselines}) != len(capture.baselines):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_BASELINE_INVALID")
        if (
            query_profiles - {row.query for row in capture.baselines}
            or any(not row.ordered_candidates for row in capture.baselines)
            or any(
                row.profile is None
                and row.source_item_revision_id in request.header.prepare.query_item_revision_ids
                for row in current.index
            )
        ) and not capture.limitations:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_BASELINE_INVALID")
        entry_hash = snapshot_entry_set_sha256(
            tuple(row.staged_entry for row in capture.records if row.staged_entry is not None)
        )
        baseline_hash = snapshot_baseline_set_sha256(capture.baselines)
        if (entry_hash, baseline_hash) != (
            request.staged_entry_set_sha256,
            request.staged_baseline_set_sha256,
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_CHANGED")
        result = hashed_snapshot_value(
            InferenceTransferSnapshotAuthorizeResult,
            "result_sha256",
            header_sha256=current.header.header_sha256,
            authorization_sha256=request.authorization_sha256,
            source_count=current.header.source_count,
            profile_count=current.header.profile_count,
            missing_report_count=current.header.missing_report_count,
            staged_entry_set_sha256=entry_hash,
            staged_baseline_set_sha256=baseline_hash,
        )
        validate_snapshot_authorize_result(request, result)
        return result
