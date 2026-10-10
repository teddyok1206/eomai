"""Real dispatch/application budget checks with synthetic source ports, not live authority.

The fake source returns small typed capture containers, never constructs an
oversize wire result itself. Therefore overflow classification is exercised at
the actual Catalog application boundary, before the consumer's adaptive split.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentBudget,
    SuppliedGraphBaseline,
    profile_key,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    MAX_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    validate_snapshot_read_result,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    InferenceTransferSnapshotBindingRequest,
    parse_binding_reply,
    validate_binding_reply,
)
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_dispatch import dispatch_snapshot_frame
from eom_catalog_service.inference_transfer_snapshot_service import (
    AuthorizedSnapshotCapture,
    InferenceTransferSnapshotApplicationService,
    prepare_snapshot_value,
    validate_snapshot_selection,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.inference_transfer_experiment_execution import (
    InferenceTransferExperimentExecution,
)
from eom_orchestrator.inference_transfer_snapshot_staging import (
    AuthenticatedSnapshotActor,
    SnapshotExperimentStageCommand,
    SnapshotReadFailure,
    SnapshotStagingError,
    stage_snapshot_experiment,
)

from tests.unit.inference_transfer_experiment_fixtures import experiment_request
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_prepare,
    snapshot_read_request,
    snapshot_read_result,
    snapshot_records,
)

ACTOR = AuthenticatedSnapshotActor("synthetic-operator")
BUDGET_ERROR = "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED"
SYNTHETIC_LIMITATIONS = ("Synthetic source data; no real authorization or scientific evaluation.",)


@pytest.fixture(scope="module")
def large_records() -> tuple[InferenceTransferSnapshotRecord, ...]:
    """Three individually valid 1.5MiB profiles with preserved explicit source refs."""
    result = []
    for record in snapshot_records():
        body = record.model_dump(mode="json")
        profile = body["staged_entry"]["profile"]
        template = profile["claims"][0]
        profile["claims"] = [
            *profile["claims"],
            *(
                template | {"claim_id": f"transferclaim_expanded{index:03d}", "text": "가" * 4000}
                for index in range(126)
            ),
        ]
        profile.pop("profile_sha256")
        profile["profile_sha256"] = content_sha256(profile)
        body["index_entry"]["profile"]["profile_sha256"] = profile["profile_sha256"]
        result.append(InferenceTransferSnapshotRecord.model_validate(body))
    return tuple(result)


class FakeAuthorizedSource:
    """No DB, Artifact read or current-login proof; indexed synthetic capture only."""

    def __init__(self, records: tuple[InferenceTransferSnapshotRecord, ...]) -> None:
        self.records = records
        self.by_run = {record.index_entry.base_analysis_run_id: record for record in records}
        self.corpus = AdmittedInferenceTransferCorpus(
            profiles=tuple(
                record.staged_entry.profile for record in records if record.staged_entry is not None
            ),
            graph_scores=(),
            truncated=False,
            missing_solution_reports=sum(record.staged_entry is None for record in records),
            sources=tuple(
                AdmittedInferenceTransferSource(
                    record.index_entry.base_analysis_run_id, record.source
                )
                for record in records
            ),
        )
        self.calls: list[
            tuple[
                str, InferenceTransferSnapshotPrepareRequest, InferenceTransferSnapshotHeader | None
            ]
        ] = []
        self.transform: Callable[[AuthorizedSnapshotCapture], AuthorizedSnapshotCapture] | None = (
            None
        )
        self.revoked = False

    def capture(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotPrepareRequest,
        *,
        expected_header: InferenceTransferSnapshotHeader | None = None,
        selected_index_entries: tuple[InferenceTransferSnapshotIndexEntry, ...] = (),
        materialize_all: bool = False,
    ) -> AuthorizedSnapshotCapture:
        self.calls.append((actor_id, request, expected_header))
        if self.revoked:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
        current = prepare_snapshot_value(actor_id, request, self.corpus)
        validate_snapshot_selection(current, expected_header, selected_index_entries)
        selected = (
            self.records
            if materialize_all
            else tuple(self.by_run[row.base_analysis_run_id] for row in selected_index_entries)
        )
        eligible = tuple(row.profile for row in current.index if row.profile is not None)
        baselines = tuple(
            sorted(
                (
                    hashed(
                        SuppliedGraphBaseline,
                        "result_sha256",
                        query=row.index_entry.profile,
                        command_sha256=content_sha256("synthetic official baseline command"),
                        ordered_candidates=tuple(
                            pointer for pointer in eligible if pointer != row.index_entry.profile
                        ),
                    )
                    for row in selected
                    if row.index_entry.profile is not None
                    and row.source.item_revision_id in request.query_item_revision_ids
                ),
                key=lambda baseline: profile_key(baseline.query),
            )
        )
        capture = AuthorizedSnapshotCapture(self.corpus, selected, baselines, SYNTHETIC_LIMITATIONS)
        return capture if self.transform is None else self.transform(capture)


class DispatchPort:
    """Exercise the actual private protocol without a socket or HTTP authority grant."""

    def __init__(self, source: FakeAuthorizedSource) -> None:
        self.service = InferenceTransferSnapshotApplicationService(source)
        self.calls: list[tuple[str, InferenceTransferSnapshotRequest]] = []
        self.error_codes: list[str] = []

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        self.calls.append((actor_id, request))
        binding = InferenceTransferSnapshotBindingRequest(actor_id=actor_id, request=request)
        raw = dispatch_snapshot_frame(self.service, canonical_json_bytes(binding) + b"\n")
        reply = parse_binding_reply(json.loads(raw))
        validate_binding_reply(binding, reply)
        if reply.error_code is not None:
            self.error_codes.append(reply.error_code)
            raise SnapshotReadFailure(reply.error_code)
        assert reply.result is not None
        return reply.result


def stage_command(
    prepare: InferenceTransferSnapshotPrepareRequest,
) -> SnapshotExperimentStageCommand:
    example = experiment_request()
    return SnapshotExperimentStageCommand(
        prepare_request=prepare,
        experiment_id=example.experiment_id,
        experiment_revision_id=example.experiment_revision_id,
        model_spec=example.model_spec,
        budget=ExperimentBudget(minimum_common_candidates=1),
    )


def prepared_read(
    port: DispatchPort, prepare: InferenceTransferSnapshotPrepareRequest
) -> tuple[InferenceTransferSnapshotPrepareResult, InferenceTransferSnapshotReadRequest]:
    prepared = port.execute(ACTOR.actor_id, prepare)
    assert isinstance(prepared, InferenceTransferSnapshotPrepareResult)
    return prepared, snapshot_read_request(prepared)


def test_global_three_mebibyte_overflow_has_exact_retryable_read_budget_code(
    large_records: tuple[InferenceTransferSnapshotRecord, ...],
) -> None:
    encoded_records = len(
        canonical_json_bytes([record.model_dump(mode="json") for record in large_records])
    )
    assert 4_500_000 < encoded_records < 4_700_000
    assert all(
        len(canonical_json_bytes(record.model_dump(mode="json"))) < MAX_SNAPSHOT_FRAME_BYTES
        for record in large_records
    )
    source = FakeAuthorizedSource(large_records)
    port = DispatchPort(source)
    prepared, read = prepared_read(port, snapshot_prepare())
    with pytest.raises(SnapshotReadFailure) as error:
        port.execute(ACTOR.actor_id, read)
    assert error.value.code == BUDGET_ERROR
    assert prepared.header.source_count == prepared.header.profile_count == 3
    assert source.calls[-1][2] == prepared.header
    assert [request.phase for _, request in port.calls] == ["PREPARE", "READ"]


def test_requested_smaller_bound_is_budget_not_invalid_input() -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    prepared = port.execute(
        ACTOR.actor_id,
        snapshot_prepare(chunk_budget={"max_entries": 64, "max_encoded_bytes": 4096}),
    )
    assert isinstance(prepared, InferenceTransferSnapshotPrepareResult)
    read = snapshot_read_request(prepared, selected_index_entries=prepared.index[:1])
    with pytest.raises(SnapshotReadFailure) as error:
        port.execute(ACTOR.actor_id, read)
    assert error.value.code == BUDGET_ERROR
    assert prepared.header.prepare.chunk_budget.max_encoded_bytes == 4096


def test_below_bound_result_preserves_predecessor_canonical_bytes_and_hash() -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    prepared, read = prepared_read(port, snapshot_prepare())
    result = port.execute(ACTOR.actor_id, read)
    assert isinstance(result, InferenceTransferSnapshotReadResult)
    capture = source.capture(
        ACTOR.actor_id,
        read.header.prepare,
        expected_header=read.header,
        selected_index_entries=read.selected_index_entries,
    )
    expected = snapshot_read_result(
        source.records, request=read, baselines=capture.baselines, limitations=capture.limitations
    )
    assert canonical_json_bytes(result.model_dump(mode="json")) == canonical_json_bytes(
        expected.model_dump(mode="json")
    )
    assert result.result_sha256 == expected.result_sha256
    assert port.error_codes == []
    validate_snapshot_read_result(read, result, index=prepared.index)


@pytest.mark.parametrize("offset", [0, -1])
def test_encoded_response_boundary_is_inclusive_without_clipping(offset: int) -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    _, initial_read = prepared_read(port, snapshot_prepare())
    initial_result = port.execute(ACTOR.actor_id, initial_read)
    assert isinstance(initial_result, InferenceTransferSnapshotReadResult)
    size = len(canonical_json_bytes(initial_result.model_dump(mode="json")))
    assert 1024 < size < MAX_SNAPSHOT_FRAME_BYTES
    _, exact_read = prepared_read(
        port, snapshot_prepare(chunk_budget={"max_entries": 64, "max_encoded_bytes": size + offset})
    )
    if offset < 0:
        with pytest.raises(SnapshotReadFailure) as error:
            port.execute(ACTOR.actor_id, exact_read)
        assert error.value.code == BUDGET_ERROR
    else:
        result = port.execute(ACTOR.actor_id, exact_read)
        assert isinstance(result, InferenceTransferSnapshotReadResult)
        assert len(canonical_json_bytes(result.model_dump(mode="json"))) == size
        assert result.records == initial_result.records
        assert result.baselines == initial_result.baselines


def test_adaptive_split_keeps_header_index_query_recipe_and_every_byte(
    large_records: tuple[InferenceTransferSnapshotRecord, ...],
) -> None:
    source = FakeAuthorizedSource(large_records)
    port = DispatchPort(source)
    prepare = snapshot_prepare()
    staged = stage_snapshot_experiment(ACTOR, stage_command(prepare), port)
    reads = [
        query for _, query in port.calls if isinstance(query, InferenceTransferSnapshotReadRequest)
    ]
    assert [len(query.selected_index_entries) for query in reads] == [3, 1, 2]
    assert port.error_codes == [BUDGET_ERROR]
    assert all(query.header == staged.header for query in reads)
    assert all(query.header.prepare == prepare for query in reads)
    assert all(actor_id == ACTOR.actor_id for actor_id, _ in port.calls)
    assert tuple(row.index_entry for row in large_records) == staged.index
    assert tuple(row.staged_entry for row in large_records) == staged.request.entries
    assert staged.request.queries == (large_records[0].index_entry.profile,)
    assert staged.request.recipe == prepare.recipe
    assert len(staged.request.baselines) == 1
    assert staged.request.baselines[0].query == staged.request.queries[0]
    assert staged.header.source_count == staged.header.profile_count == 3


def test_single_entry_too_large_is_terminal_before_workspace_or_cpu() -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    command = stage_command(
        snapshot_prepare(chunk_budget={"max_entries": 1, "max_encoded_bytes": 4096})
    )
    workspace, cpu, commit = Mock(), Mock(), Mock()
    execution = InferenceTransferExperimentExecution(
        snapshot=port, workspace=workspace, cpu=cpu, commit=commit
    )
    with pytest.raises(SnapshotStagingError) as error:
        execution.execute(
            ACTOR,
            command,
            execution_id="embeddingexecution_" + "9" * 32,
            created_at=NOW,
        )
    assert error.value.code == "INFERENCE_TRANSFER_STAGING_BUDGET_EXCEEDED"
    assert [request.phase for _, request in port.calls] == ["PREPARE", "READ"]
    assert port.error_codes == [BUDGET_ERROR]
    workspace.prepare.assert_not_called()
    cpu.run.assert_not_called()
    commit.publish.assert_not_called()


@pytest.mark.parametrize("corruption", ["source_hash", "foreign_reference"])
def test_hash_and_reference_failures_are_nonbudget_and_never_split(corruption: str) -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    prepared, read = prepared_read(port, snapshot_prepare())
    if corruption == "foreign_reference":
        selected = read.selected_index_entries[0].model_copy(
            update={"source_value_sha256": "sha256:" + "0" * 64}
        )
        read = hashed(
            InferenceTransferSnapshotReadRequest,
            "read_sha256",
            header=prepared.header,
            selected_index_entries=(selected,),
        )
    else:

        def tamper(capture: AuthorizedSnapshotCapture) -> AuthorizedSnapshotCapture:
            if not capture.records:
                return capture
            record = capture.records[0].model_copy(
                update={
                    "index_entry": capture.records[0].index_entry.model_copy(
                        update={"source_value_sha256": "sha256:" + "0" * 64}
                    )
                }
            )
            return replace(capture, records=(record, *capture.records[1:]))

        source.transform = tamper
    with pytest.raises(SnapshotReadFailure) as error:
        port.execute(ACTOR.actor_id, read)
    expected = (
        "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID"
        if corruption == "foreign_reference"
        else "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    )
    assert error.value.code == expected
    assert BUDGET_ERROR not in port.error_codes
    assert [request.phase for _, request in port.calls] == ["PREPARE", "READ"]


def test_invalid_request_hash_is_rejected_before_source_read_not_as_a_budget_failure() -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    _, read = prepared_read(port, snapshot_prepare())
    binding = InferenceTransferSnapshotBindingRequest(actor_id=ACTOR.actor_id, request=read)
    body = binding.model_dump(mode="json")
    body["request"]["read_sha256"] = "sha256:" + "0" * 64
    reply = parse_binding_reply(
        json.loads(dispatch_snapshot_frame(port.service, canonical_json_bytes(body) + b"\n"))
    )
    assert reply.status == "FAILED"
    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    assert len(source.calls) == 1


def test_real_dispatch_nonbudget_error_cannot_trigger_adaptive_replay() -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)

    def tamper(capture: AuthorizedSnapshotCapture) -> AuthorizedSnapshotCapture:
        if not capture.records:
            return capture
        record = capture.records[0].model_copy(
            update={
                "index_entry": capture.records[0].index_entry.model_copy(
                    update={"source_value_sha256": "sha256:" + "0" * 64}
                )
            }
        )
        return replace(capture, records=(record, *capture.records[1:]))

    source.transform = tamper
    with pytest.raises(SnapshotReadFailure) as error:
        stage_snapshot_experiment(ACTOR, stage_command(snapshot_prepare()), port)
    assert error.value.code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    assert port.error_codes == ["INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"]
    assert [request.phase for _, request in port.calls] == ["PREPARE", "READ"]


def test_source_revocation_remains_forbidden_not_a_reason_to_split() -> None:
    source = FakeAuthorizedSource(snapshot_records())
    port = DispatchPort(source)
    _, read = prepared_read(port, snapshot_prepare())
    source.revoked = True
    with pytest.raises(SnapshotReadFailure) as error:
        port.execute(ACTOR.actor_id, read)
    assert error.value.code == "INFERENCE_TRANSFER_FORBIDDEN"
    assert BUDGET_ERROR not in port.error_codes
    assert len(port.calls) == 2
