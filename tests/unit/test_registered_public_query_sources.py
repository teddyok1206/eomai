"""Index4 real local bytes and native source materialization; IAM/ledger leaves synthetic."""

import pytest
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityRequestV4,
)
from eom_catalog_service import public_solution_similarity_read as reads
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    SelectedEmbeddingSources,
)
from eom_workflow_runner.reference_query_source_read import build_public_solution_query_native_input

from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_public_solution_query_source import public_query_sources
from tests.unit.test_public_solution_registry_read import public_read as public_read
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_bulk_catalog_preparation_carries_three_source_proofs_from_actual_index4(public_read):
    value = public_read
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    inputs = tuple(
        reads.PublicSolutionSimilarityPreparation(
            "similarityrequest_" + f"{ordinal + 1:032x}",
            SelectedEmbeddingSources(value.intent.scope, (entry.source.item_revision_id,)),
            value.intent.selection.index.spaces,
            "ITEM_DATABASE_SEARCH",
            8,
        )
        for ordinal, entry in enumerate(value.entries)
    )
    facade = reads.CatalogPublicSolutionSimilarityRead(value.verifier)
    requests = facade.prepare_many_in_session(value.session, caller, inputs)
    assert len(requests) == 3 and all(
        isinstance(request, PublicSolutionSimilarityRequestV4) for request in requests
    )
    assert {request.anchor.evidence.kind for request in requests} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    }
    for request in requests:
        source = facade.prepare_query_in_session(value.session, caller, request)
        assert source.anchor == request.anchor
        assert source.row.text == value.entries[0].public_solution.text
        assert request.views[0].index.index_manifest == value.index_member


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("registered_anchor", [False, True])
def test_native_receiver_derives_same_query2_from_registered_proof(device, registered_anchor):
    value = registered_public_workflow_case(device=device, registered_anchor=registered_anchor)
    sources = public_query_sources(value)
    native = build_public_solution_query_native_input(
        sources,
        job_id=value.native_input.job_id,
        query_request_id=value.native_input.query_request_id,
    )
    assert native == value.native_input
    assert native.schema_version == "embedding-reference-query-input/2.0"
    assert sources.request.context_request.anchor == sources.prepared.anchor
