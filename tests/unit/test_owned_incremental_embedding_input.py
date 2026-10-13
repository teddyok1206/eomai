"""Pure owned-subset materialization; synthetic values confer no execution authority."""

from __future__ import annotations

import pytest
from eom_identifiers import canonical_json_bytes
from eom_workflow.local_embedding_encoding_job import build_owned_incremental_embedding_input

from tests.unit.local_embedding_admission_fixtures import native_fixture, resources


@pytest.mark.parametrize("owned", (None, ("a",), ("b",)))
def test_exact_owned_subset_materializes_existing_input_without_rewriting_original(owned) -> None:
    fixture = native_fixture("a", "b", owned_seeds=owned)
    original = canonical_json_bytes(fixture.request.model_dump(mode="json"))
    plan = canonical_json_bytes(fixture.plan.model_dump(mode="json"))
    actual = build_owned_incremental_embedding_input(
        fixture.plan,
        fixture.entries,
        fixture.association.owned_jobs,
        native_launch_job_id=fixture.association.intent.native_launch_job_id,
        resources=fixture.request.resource_profile,
    )
    assert actual == fixture.native_input
    assert len(actual.rows) == (2 if owned is None else 1)
    assert canonical_json_bytes(fixture.request.model_dump(mode="json")) == original
    assert canonical_json_bytes(fixture.plan.model_dump(mode="json")) == plan
    assert (
        build_owned_incremental_embedding_input(
            fixture.plan,
            fixture.entries,
            fixture.association.owned_jobs,
            native_launch_job_id=fixture.association.intent.native_launch_job_id,
            resources=fixture.request.resource_profile,
        )
        == actual
    )


@pytest.mark.parametrize("selection", ("empty", "reversed", "duplicate", "foreign", "alias_launch"))
def test_missing_foreign_or_ambiguous_ownership_is_not_filled_with_latest(selection: str) -> None:
    fixture = native_fixture("a", "b")
    jobs = fixture.association.owned_jobs
    launch = fixture.association.intent.native_launch_job_id
    if selection == "empty":
        jobs = ()
    if selection == "reversed":
        jobs = tuple(reversed(jobs))
    if selection == "duplicate":
        jobs = (jobs[0], jobs[0])
    if selection == "foreign":
        jobs = native_fixture("c").association.owned_jobs
    if selection == "alias_launch":
        launch = jobs[0].job_reference.job_id
    with pytest.raises(ValueError):
        build_owned_incremental_embedding_input(
            fixture.plan,
            fixture.entries,
            jobs,
            native_launch_job_id=launch,
            resources=fixture.request.resource_profile,
        )


@pytest.mark.parametrize("bad_entries", ("missing", "duplicate", "foreign"))
def test_current_profile_closure_is_required_even_for_a_smaller_owned_subset(
    bad_entries: str,
) -> None:
    fixture = native_fixture("a", "b", owned_seeds=("a",))
    entries = fixture.entries
    if bad_entries == "missing":
        entries = entries[:1]
    if bad_entries == "duplicate":
        entries = (entries[0], entries[0])
    if bad_entries == "foreign":
        entries = native_fixture("c", "d").entries
    with pytest.raises(ValueError):
        build_owned_incremental_embedding_input(
            fixture.plan,
            entries,
            fixture.association.owned_jobs,
            native_launch_job_id=fixture.association.intent.native_launch_job_id,
            resources=fixture.request.resource_profile,
        )


def test_different_device_is_not_silently_treated_as_cpu() -> None:
    fixture = native_fixture()
    with pytest.raises(ValueError):
        build_owned_incremental_embedding_input(
            fixture.plan,
            fixture.entries,
            fixture.association.owned_jobs,
            native_launch_job_id=fixture.association.intent.native_launch_job_id,
            resources=resources("CUDA"),
        )
