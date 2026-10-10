"""Snapshot assembly uses fake owner ports; hashes are not real authorization."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotChunkBudget,
    snapshot_baseline_set_sha256,
    snapshot_entry_set_sha256,
)
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_service import (
    AuthorizedSnapshotCapture,
    InferenceTransferSnapshotApplicationService,
    prepare_snapshot_value,
    validate_snapshot_selection,
)
from pydantic import ValidationError

from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
    snapshot_records,
    snapshot_v3_record,
)

ACTOR = "synthetic-operator"


def corpus(records=None, *, truncated=False):
    records = snapshot_records() if records is None else records
    return AdmittedInferenceTransferCorpus(
        profiles=tuple(row.staged_entry.profile for row in records if row.staged_entry is not None),
        graph_scores=(),
        truncated=truncated,
        missing_solution_reports=sum(row.staged_entry is None for row in records),
        sources=tuple(
            AdmittedInferenceTransferSource(row.index_entry.base_analysis_run_id, row.source)
            for row in records
        ),
    )


class FakeOwner:
    def __init__(self, records=None):
        self.records = snapshot_records() if records is None else records
        self.population = corpus(self.records)
        self.calls = []
        self.revoked = False
        self.baseline_override = None
        self.limits_override = None

    def capture(
        self,
        actor_id,
        request,
        *,
        expected_header=None,
        selected_index_entries=(),
        materialize_all=False,
    ):
        self.calls.append(
            (actor_id, request, expected_header, selected_index_entries, materialize_all)
        )
        if self.revoked:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
        selected = (
            self.records
            if materialize_all
            else tuple(row for row in self.records if row.index_entry in selected_index_entries)
        )
        baselines = ()
        limits = ()
        if selected:
            sample = snapshot_read_result(self.records)
            queries = {
                row.index_entry.profile
                for row in selected
                if row.source.item_revision_id in request.query_item_revision_ids
            }
            baselines = tuple(row for row in sample.baselines if row.query in queries)
            limits = sample.limitations
        return AuthorizedSnapshotCapture(
            self.population,
            selected,
            baselines if self.baseline_override is None else self.baseline_override,
            limits if self.limits_override is None else self.limits_override,
        )


def authorized_request(prepared, read):
    return hashed(
        InferenceTransferSnapshotAuthorizeRequest,
        "authorization_sha256",
        header=prepared.header,
        staged_entry_set_sha256=snapshot_entry_set_sha256(
            tuple(row.staged_entry for row in read.records if row.staged_entry is not None)
        ),
        staged_baseline_set_sha256=snapshot_baseline_set_sha256(read.baselines),
    )


def test_three_phases_pin_all_sources_and_have_deterministic_replay():
    owner = FakeOwner(snapshot_records(missing_seed="c"))
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    assert (
        prepared.header.source_count,
        prepared.header.profile_count,
        prepared.header.missing_report_count,
    ) == (3, 2, 1)
    read = service.read(ACTOR, snapshot_read_request(prepared))
    result = service.authorize(ACTOR, authorized_request(prepared, read))
    assert result.status == "AUTHORIZED_CURRENT_READ"
    assert result.source_count == 3
    assert owner.calls[-1][-1] is True
    assert service.prepare(ACTOR, snapshot_prepare()) == prepared
    assert service.read(ACTOR, snapshot_read_request(prepared)) == read
    assert service.authorize(ACTOR, authorized_request(prepared, read)) == result


def test_prepare_without_queries_does_not_require_a_fabricated_query_item():
    service = InferenceTransferSnapshotApplicationService(FakeOwner())
    prepared = service.prepare(ACTOR, snapshot_prepare(query_item_revision_ids=()))
    assert prepared.header.prepare.query_item_revision_ids == ()


@pytest.mark.parametrize("phase", ["read", "authorize"])
def test_header_actor_is_a_pin_not_an_authority_override(phase):
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    read = service.read(ACTOR, snapshot_read_request(prepared))
    calls = len(owner.calls)
    request = (
        snapshot_read_request(prepared) if phase == "read" else authorized_request(prepared, read)
    )
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        getattr(service, phase)("other-operator", request)
    assert len(owner.calls) == calls


@pytest.mark.parametrize("phase", ["read", "authorize"])
def test_revoked_current_owner_rejects_prior_valid_hashes(phase):
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    read = service.read(ACTOR, snapshot_read_request(prepared))
    owner.revoked = True
    request = (
        snapshot_read_request(prepared) if phase == "read" else authorized_request(prepared, read)
    )
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        getattr(service, phase)(ACTOR, request)


def test_revoked_nonselected_population_member_invalidates_chunk():
    owner = FakeOwner(snapshot_records(missing_seed="c"))
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    owner.population = corpus(owner.records[:2])
    request = snapshot_read_request(prepared, selected_index_entries=prepared.index[:1])
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        service.read(ACTOR, request)


def test_new_accepted_report_changes_missing_denominator_and_blocks_old_header():
    owner = FakeOwner(snapshot_records(missing_seed="c"))
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    owner.population = corpus(snapshot_records())
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        service.read(ACTOR, snapshot_read_request(prepared))


def test_truncated_population_is_not_called_complete_corpus():
    with pytest.raises(InferenceTransferServiceError, match="POPULATION_TRUNCATED"):
        prepare_snapshot_value(ACTOR, snapshot_prepare(), corpus(truncated=True))


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_source",
        "duplicate_revision",
        "missing_count",
        "unadmitted_profile",
        "duplicate_profile",
    ],
)
def test_bad_owner_population_is_rejected_before_return(mutation):
    value = corpus()
    if mutation == "duplicate_source":
        value = replace(
            value, sources=value.sources + value.sources[:1], missing_solution_reports=1
        )
    elif mutation == "duplicate_revision":
        row = value.sources[-1]
        altered = row.source.model_copy(
            update={"item_revision_id": value.sources[0].source.item_revision_id}
        )
        value = replace(value, sources=(*value.sources[:-1], replace(row, source=altered)))
    elif mutation == "missing_count":
        value = replace(value, missing_solution_reports=1)
    elif mutation == "duplicate_profile":
        value = replace(value, profiles=value.profiles[:-1] + value.profiles[:1])
    else:
        value = replace(value, sources=value.sources[:-1], missing_solution_reports=-1)
    with pytest.raises((InferenceTransferServiceError, ValidationError, ValueError)):
        prepare_snapshot_value(ACTOR, snapshot_prepare(), value)


def test_full_v3_source_chain_is_hashed_while_profile_uses_core_v2():
    row = snapshot_v3_record()
    prepared = prepare_snapshot_value(
        ACTOR, snapshot_prepare(query_item_revision_ids=()), corpus((row,))
    )
    assert prepared.index[0].source_value_sha256 == row.index_entry.source_value_sha256
    assert prepared.header.source_count == 1


def test_selection_exact_index_hash_cannot_be_replaced_by_same_item_identity():
    prepared = snapshot_prepare_result()
    forged = prepared.index[0].model_copy(update={"source_value_sha256": "sha256:" + "0" * 64})
    with pytest.raises(InferenceTransferServiceError, match="SELECTION_INVALID"):
        validate_snapshot_selection(prepared, prepared.header, (forged,))


def test_read_revalidates_model_copy_hashes_before_owner_call():
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    request = snapshot_read_request().model_copy(update={"read_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValidationError):
        service.read(ACTOR, request)
    assert not owner.calls


def test_encoded_result_budget_is_actual_bytes_not_just_entry_count():
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(
        ACTOR,
        snapshot_prepare(
            chunk_budget=InferenceTransferSnapshotChunkBudget(
                max_entries=64, max_encoded_bytes=4096
            )
        ),
    )
    request = snapshot_read_request(prepared, selected_index_entries=prepared.index[:1])
    with pytest.raises(ValueError, match=r"encoded|frame|budget"):
        service.read(ACTOR, request)


def test_final_authorization_regenerates_staged_text_hash_not_only_source_header():
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    read = service.read(ACTOR, snapshot_read_request(prepared))
    row = owner.records[0]
    entry = row.staged_entry
    assert entry is not None
    altered = entry.model_copy(
        update={"limitations": (*entry.limitations, "changed producer view")}
    )
    owner.records = (row.model_copy(update={"staged_entry": altered}), *owner.records[1:])
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        service.authorize(ACTOR, authorized_request(prepared, read))


def test_final_authorization_rechecks_baseline_order_hash():
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    read = service.read(ACTOR, snapshot_read_request(prepared))
    owner.baseline_override = ()
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        service.authorize(ACTOR, authorized_request(prepared, read))


def test_final_missing_baseline_requires_explicit_limitation():
    owner = FakeOwner()
    service = InferenceTransferSnapshotApplicationService(owner)
    prepared = service.prepare(ACTOR, snapshot_prepare())
    read = service.read(ACTOR, snapshot_read_request(prepared))
    owner.baseline_override = ()
    owner.limits_override = ()
    with pytest.raises(InferenceTransferServiceError, match="BASELINE_INVALID"):
        service.authorize(ACTOR, authorized_request(prepared, read))


def test_empty_population_is_explicit_and_cannot_manufacture_query():
    prepared = prepare_snapshot_value(
        ACTOR, snapshot_prepare(query_item_revision_ids=()), corpus(())
    )
    assert prepared.header.source_count == prepared.header.profile_count == 0
    with pytest.raises(ValueError, match="outside"):
        prepare_snapshot_value(ACTOR, snapshot_prepare(), corpus(()))
