"""Device-neutral pure preparation; current authority and physical execution remain external."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from eom_orchestrator.native_embedding_query_handoff import PreparedNativeQuery
from eom_workflow_runner import reference_query_launch_preparation as module
from eom_workflow_runner.reference_query_source_read import ResolvedReferenceQuerySources
from eom_workflow_runner.repository import CommandLeaseIdentity
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_similarity_context_service import case as context_case


def sources_for(value):
    _, port, _ = context_case()
    return ResolvedReferenceQuerySources(
        value.request,
        value.policy,
        value.bundle,
        replace(
            port.prepared,
            request_sha256=value.request.context_request.request_sha256,
            query_texts=tuple((row.view, row.text) for row in value.native_input.rows),
        ),
    )


def prepare(sources, existing=None, generation=1):
    return module.prepare_reference_query_launch_candidate(
        sources,
        workflow_id="workflow_" + "1" * 32,
        step_run_id="steprun_" + "1" * 32,
        command_lease=CommandLeaseIdentity(
            "wfcmd_" + str(generation) * 32, "test", "test", generation
        ),
        existing=existing,
    )


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_same_source_preparation_supports_selected_device_without_model_or_allocation(device):
    value = case(device=device)
    sources = sources_for(value)
    candidate = prepare(sources)
    assert candidate.request.spaces.query.runtime.device == device
    assert tuple(row.text for row in candidate.request.rows) == tuple(
        row.text for row in value.native_input.rows
    )
    assert prepare(sources, candidate.association, generation=2) == candidate
    assert candidate.association.original_command_generation == 1
    with pytest.raises(FrozenInstanceError):
        candidate.request = value.native_input


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_replay_keeps_original_ids_time_and_command_without_generating_new_identity(
    device, monkeypatch
):
    value = case(device=device)
    sources = sources_for(value)

    def unexpected():
        pytest.fail("replay tried allocating a new identity")

    monkeypatch.setattr(module, "new_job_id", unexpected)
    monkeypatch.setattr(module, "new_revision_id", unexpected)
    candidate = prepare(sources, value.launch, generation=2)
    assert candidate.request == value.native_input and candidate.association == value.launch


def test_foreign_original_workflow_or_changed_source_is_not_an_implicit_reprepare():
    value = case()
    sources = sources_for(value)
    with pytest.raises(ValueError):
        module.prepare_reference_query_launch_candidate(
            sources,
            workflow_id="workflow_" + "f" * 32,
            step_run_id=value.launch.step_run_id,
            command_lease=CommandLeaseIdentity("wfcmd_" + "1" * 32, "test", "test", 1),
            existing=value.launch,
        )
    changed = replace(
        sources, prepared=replace(sources.prepared, query_texts=(("CONTENT_ONLY", "달라진 원문"),))
    )
    with pytest.raises(ValueError):
        prepare(changed, value.launch)


def test_constructed_candidate_still_rejects_forged_hash_or_unrelated_input():
    value = case()
    for invalid in (
        value.native_input.model_copy(update={"extra": True}),
        case(device="CUDA").native_input,
    ):
        with pytest.raises((ValueError, SchemaError)):
            module.ReferenceQueryLaunchCandidate(value.launch, invalid)


def test_device_neutral_preparation_does_not_weaken_legacy_cpu_handoff_guard():
    value = case(device="CUDA")
    candidate = prepare(sources_for(value), value.launch)
    with pytest.raises(ValueError):
        PreparedNativeQuery(
            candidate.association.native_launch_job_id.removeprefix("job_"),
            value.request,
            value.policy,
            value.bundle,
            candidate.association,
            candidate.request,
        )
