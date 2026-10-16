"""Pure synthetic membership changes; no authority, DB, model or Artifact publication."""

from __future__ import annotations

import pytest
from eom_catalog_service.embedding_index_refresh_plan import plan_index_membership_refresh
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_index_refresh import IndexRefreshContractError

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    index_manifest,
    index_pointer,
    source_binding,
)


def fixture():
    bindings = tuple(source_binding(embedding_entry(seed)) for seed in ("a", "b"))
    sources = tuple(value.source for value in bindings)
    index = index_manifest(*bindings)
    return sources, bindings, (index_pointer(index), index)


def test_missing_namespace_needs_membership_publication_despite_all_reusable_bindings():
    sources, bindings, _ = fixture()
    basis = plan_index_membership_refresh(
        eligible_sources=sources, available_bindings=bindings, previous=None
    )
    assert basis is not None and basis.reason == "MISSING_NAMESPACE_INDEX"
    assert basis.eligible_source_count == basis.available_binding_count == 2
    assert basis.previous_index_manifest is None and basis.previous_index_sha256 is None


def test_source_withdrawal_changes_index_membership_without_changing_surviving_rows():
    sources, bindings, previous = fixture()
    original_row = bindings[0].row_ref
    basis = plan_index_membership_refresh(
        eligible_sources=sources[:1], available_bindings=bindings[:1], previous=previous
    )
    assert basis is not None and basis.reason == "INDEX_MEMBERSHIP_CHANGED"
    assert basis.eligible_source_count == basis.available_binding_count == 1
    assert basis.previous_index_manifest == previous[0]
    assert basis.previous_index_sha256 == previous[1].index_sha256
    assert bindings[0].row_ref == original_row


def test_identical_current_membership_is_no_work_and_order_does_not_change_identity():
    sources, bindings, previous = fixture()
    assert (
        plan_index_membership_refresh(
            eligible_sources=sources[::-1], available_bindings=bindings[::-1], previous=previous
        )
        is None
    )
    first = plan_index_membership_refresh(
        eligible_sources=sources, available_bindings=bindings, previous=None
    )
    replay = plan_index_membership_refresh(
        eligible_sources=sources[::-1], available_bindings=bindings[::-1], previous=None
    )
    assert first == replay


@pytest.mark.parametrize("empty_sources", [False, True])
def test_empty_or_report_waiting_population_never_creates_an_empty_index(empty_sources):
    sources, _, previous = fixture()
    assert (
        plan_index_membership_refresh(
            eligible_sources=() if empty_sources else sources,
            available_bindings=(),
            previous=previous,
        )
        is None
    )


def test_missing_report_changes_live_denominator_not_identical_index_bytes():
    sources, bindings, previous = fixture()
    extra = embedding_entry("c").profile.source_basis.source
    assert (
        plan_index_membership_refresh(
            eligible_sources=(*sources, extra), available_bindings=bindings, previous=previous
        )
        is None
    )


@pytest.mark.parametrize(
    "fault",
    [
        "source_duplicate",
        "binding_duplicate",
        "foreign_source",
        "hash",
        "copied_extra",
        "mixed_view",
        "path",
    ],
)
def test_corrupt_or_foreign_membership_is_an_explicit_error(fault):
    sources, bindings, previous = fixture()
    if fault == "source_duplicate":
        sources = (sources[0], sources[0])
    elif fault == "binding_duplicate":
        bindings = (bindings[0], bindings[0])
    elif fault == "foreign_source":
        sources = (embedding_entry("c").profile.source_basis.source, sources[1])
    elif fault == "hash":
        previous = (
            ArtifactMemberPointer.model_validate(
                previous[0].model_dump(mode="json") | {"sha256": "sha256:" + "0" * 64}
            ),
            previous[1],
        )
    elif fault == "copied_extra":
        bindings = (bindings[0].model_copy(update={"approved": True}), bindings[1])
    elif fault == "mixed_view":
        bindings = (bindings[0], source_binding(embedding_entry("b"), view="CONTENT_ONLY"))
    else:
        previous = (
            ArtifactMemberPointer.model_validate(
                previous[0].model_dump(mode="json") | {"member_path": "other.json"}
            ),
            previous[1],
        )
    with pytest.raises(IndexRefreshContractError):
        plan_index_membership_refresh(
            eligible_sources=sources, available_bindings=bindings, previous=previous
        )
