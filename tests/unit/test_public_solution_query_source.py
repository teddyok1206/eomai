"""Exact public-source materialization only; no live authentication/native execution."""

from dataclasses import replace

import pytest
from eom_catalog_service.public_solution_similarity_service import PreparedPublicSolutionQuerySource
from eom_workflow_runner.reference_query_source_read import (
    ResolvedPublicSolutionReferenceQuerySources,
    ResolvedReferenceQuerySources,
    build_public_solution_query_native_input,
    build_reference_query_native_input,
)

from tests.unit.test_public_solution_reference_query_execution import public_workflow_case


def public_query_sources(value):
    return ResolvedPublicSolutionReferenceQuerySources(
        value.request,
        value.policy,
        value.bundle,
        PreparedPublicSolutionQuerySource(
            value.request.context_request.request_sha256,
            value.request.context_request.anchor,
            value.native_input.rows[0],
        ),
    )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_public_source_derives_exact_original_query2_input_and_separate_query_space(device):
    value = public_workflow_case(device=device)
    sources = public_query_sources(value)
    result = build_public_solution_query_native_input(
        sources,
        job_id=value.native_input.job_id,
        query_request_id=value.native_input.query_request_id,
    )
    assert result == value.native_input
    assert result.spaces.query.runtime.device == device
    assert result.rows[0].encoding.space_sha256 != result.spaces.document.space_sha256
    with pytest.raises(ValueError):
        ResolvedReferenceQuerySources(value.request, value.policy, value.bundle, sources.prepared)
    with pytest.raises(ValueError):
        build_reference_query_native_input(
            sources,
            job_id=value.native_input.job_id,
            query_request_id=value.native_input.query_request_id,
        )


@pytest.mark.parametrize(
    "fault", ["context", "anchor", "anchor_extra", "encoding", "extra", "text", "device", "recipe"]
)
def test_public_source_materialization_does_not_repair_foreign_pins_or_raw_fields(fault):
    value = public_workflow_case()
    sources = public_query_sources(value)
    prepared = sources.prepared
    if fault == "context":
        prepared = replace(prepared, request_sha256="sha256:" + "f" * 64)
    elif fault == "anchor":
        prepared = replace(
            prepared,
            anchor=prepared.anchor.model_copy(
                update={"base_analysis_run_id": "analysisrun_" + "f" * 32}
            ),
        )
    elif fault == "anchor_extra":
        prepared = replace(
            prepared, anchor=prepared.anchor.model_copy(update={"authority": "ADMIN"})
        )
    elif fault == "encoding":
        prepared = replace(
            prepared,
            row=prepared.row.model_copy(
                update={
                    "encoding": prepared.row.encoding.model_copy(
                        update={"space_sha256": value.policy.spaces.document.space_sha256}
                    )
                }
            ),
        )
    elif fault == "extra":
        prepared = replace(prepared, row=prepared.row.model_copy(update={"authority": "ADMIN"}))
    elif fault == "text":
        prepared = replace(
            prepared, row=prepared.row.model_copy(update={"text": prepared.row.text + " changed"})
        )
    elif fault == "device":
        with pytest.raises(ValueError):
            replace(sources, policy=public_workflow_case(device="CUDA").policy)
        return
    else:
        with pytest.raises(ValueError):
            replace(
                sources,
                request=value.request.model_copy(update={"request_sha256": "sha256:" + "f" * 64}),
            )
        return
    with pytest.raises(ValueError):
        replace(sources, prepared=prepared)
