"""Mixed reference reads through existing owners; no live source or model authority."""

from __future__ import annotations

import os
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_catalog_contracts.embedding_reference_query import (
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.mixed_embedding_index import RegisteredReviewEmbeddingSourceBinding
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context_v2 import (
    RegisteredReviewSimilarityCandidateV2,
    SimilarityContextV2,
    parse_similarity_context_request_v2,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
)
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilaritySource,
    SimilarityContextReadError,
)
from eom_catalog_service.similarity_context_service import SimilarityContextApplicationService
from eom_identifiers import content_sha256
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_similarity_context_service import CALLER, Query, Sources, case


def mixed_case():
    original, old_sources, old_query = case()
    entry = mixed_embedding_case()[0]
    profile = RegisteredReviewProfilePointer.from_profile(entry.profile)
    prepared_rows = list(old_sources.prepared.sources)
    prepared_rows[1] = PreparedSimilaritySource(
        entry.profile.source_basis.source,
        profile,
        None,
        entry.profile.source_basis.review_evidence,
    )
    body = original.model_dump(mode="json")
    body["schema_version"] = "system-rag-similarity-request/2.0"
    body["source_classes"] = ["APPROVED_ITEM", "PAST_EXAM"]
    for selected in body["views"]:
        selected["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    request = parse_similarity_context_request_v2(seal(body, "request_sha256"))
    prepared = replace(
        old_sources.prepared, request_sha256=request.request_sha256, sources=tuple(prepared_rows)
    )
    reads = []
    for old in old_sources.reads:
        view = old.intent.selection.view
        _entry, binding, _shard, _pointer, _index = mixed_embedding_case(view)
        binding_body = binding.model_dump(mode="json")
        binding_body["graph_snapshot"] = request.graph_snapshot.model_dump(mode="json")
        binding_body["policy_revision_id"] = request.policy_revision_id
        binding_body["policy_sha256"] = request.policy_sha256
        binding = RegisteredReviewEmbeddingSourceBinding.model_validate(
            seal(binding_body, "binding_sha256")
        )
        selected = next(value for value in request.views if value.view == view)
        namespace = MixedEmbeddingIndexNamespace.model_validate(
            old.intent.scope.namespace.model_dump(mode="json")
            | {
                "projection_version": "mixed-solution-comparison/2.0",
                "population_scope": "ALL_ADMITTED_GRAPH_ITEMS",
            }
        )
        numerical = {row.row.encoding.encoding_sha256: row for row in old.numerical_rows}
        old_binding = old.bindings[1]
        values = numerical[old_binding.encoding.encoding_sha256].values
        if all(
            candidate.encoding != old_binding.encoding
            for candidate in (old.bindings[0], old.bindings[2])
        ):
            numerical.pop(old_binding.encoding.encoding_sha256)
        numerical[binding.encoding.encoding_sha256] = MaterializedEmbeddingReadRow(
            RegisteredEmbeddingRow(binding.encoding, binding.row_ref), values
        )
        reads.append(
            replace(
                old,
                intent=EmbeddingRegistryRead(
                    replace(old.intent.scope, namespace=namespace), selected
                ),
                sources=tuple(row.source for row in prepared_rows),
                profiles=tuple(
                    AuthorizedEmbeddingReadProfile(row.source.item_revision_id, row.profile)
                    for row in prepared_rows
                ),
                bindings=(old.bindings[0], binding, old.bindings[2]),
                numerical_rows=tuple(numerical[key] for key in sorted(numerical)),
            )
        )
    query_value = old_query.value
    query_body = query_value.request.model_dump(mode="json")
    query_body["context_request_sha256"] = request.request_sha256
    query = parse_embedding_reference_query_input(seal(query_body, "request_sha256"))
    result_body = query_value.result.model_dump(mode="json")
    result_body["context_request_sha256"] = request.request_sha256
    result_body["request_sha256"] = query.request_sha256
    result = parse_embedding_reference_query_result(seal(result_body, "result_sha256"))
    return (
        request,
        Sources(prepared, tuple(reads)),
        Query(
            replace(
                query_value,
                request=query,
                result=result,
                result_member=query_value.result_member.model_copy(
                    update={"sha256": content_sha256(result.model_dump(mode="json"))}
                ),
            )
        ),
    )


def test_common_composer_scores_genuine_profile2_with_original_numerical_result1() -> None:
    request, sources, query = mixed_case()
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert isinstance(result, SimilarityContextV2)
    assert result.status == "READY"
    registered = next(
        value
        for value in result.candidates
        if isinstance(value, RegisteredReviewSimilarityCandidateV2)
    )
    assert registered.source.source_class == "APPROVED_ITEM"
    assert registered.profile.schema_ref.endswith("/2.0")
    assert not hasattr(registered, "solution_evidence")
    assert result.population.available_profile_count == 3
    assert result.population.missing_evidence_count == 0
    assert sources.calls == ["prepare", "read", "reauthorize"]
    assert query.value.request.schema_version == "embedding-reference-query-input/1.0"
    assert query.value.result.schema_version == "embedding-reference-query-result/1.0"


@pytest.mark.parametrize(
    "fault", ["late_denial", "stale_evidence", "wrong_index_family", "wrong_profile_family"]
)
def test_mixed_current_source_and_binding_fences_fail_without_candidate_disclosure(fault) -> None:
    request, sources, query = mixed_case()
    if fault == "late_denial":
        sources.denial = "revoked"
    elif fault == "stale_evidence":
        changed = replace(sources.prepared.sources[1], review_evidence=None)
        sources.prepared = replace(
            sources.prepared,
            sources=(sources.prepared.sources[0], changed, sources.prepared.sources[2]),
        )
    elif fault == "wrong_index_family":
        _original, old_sources, _ = case()
        sources.reads = (old_sources.reads[0], *sources.reads[1:])
    else:
        row = sources.reads[0]
        sources.reads = (
            replace(
                row,
                profiles=(
                    row.profiles[0],
                    replace(row.profiles[1], profile=row.profiles[0].profile),
                    row.profiles[2],
                ),
            ),
            *sources.reads[1:],
        )
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    assert isinstance(result, SimilarityContextV2)
    assert result.status == "FAILED"
    assert result.candidates == () and result.population is None and result.query_execution is None


def test_existing_actual_unix_rpc_roundtrip_keeps_explicit2_and_actual_injected_actor(
    tmp_path,
) -> None:
    request, sources, query = mixed_case()
    result = SimilarityContextApplicationService(sources, query).compose(CALLER, request)
    selection = CompletedSimilarityQuerySelection(
        workflow_id="workflow_" + "a" * 32,
        workflow_request_sha256="sha256:" + "b" * 64,
        context_request_sha256=request.request_sha256,
    )
    server = _server(tmp_path)
    service = SimpleNamespace(read=Mock(return_value=result))
    server.similarity_context_reads = service
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogSimilarityContextClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        assert client.read_v2(CALLER.operator_id, selection) == result
        call = service.read.call_args.args[0]
        assert call.schema_version == "system-rag-similarity-read-request/2.0"
        assert call.actor_id == CALLER.operator_id and call.selection == selection
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_existing_private_and_exam_consumers_do_not_gain_review2_support():
    from eom_catalog_service.exam_similarity_observation import compose_exam_similarity_observation

    from tests.unit.test_exam_similarity_observation import exam_case
    from tests.unit.test_private_chat_similarity_service import case as private_case
    from tests.unit.test_private_chat_similarity_service import compose as private_compose

    entry = mixed_embedding_case()[0]
    review = PreparedSimilaritySource(
        entry.profile.source_basis.source,
        RegisteredReviewProfilePointer.from_profile(entry.profile),
        None,
        entry.profile.source_basis.review_evidence,
    )
    private, owner = private_case()
    owner.prepared = replace(owner.prepared, sources=(review, *owner.prepared.sources[1:]))
    rejected = private_compose(private, owner)
    assert rejected.status == "FAILED" and rejected.error_code == "SOURCE_POINTER_INVALID"
    assert rejected.candidates == () and owner.calls == ["prepare"]

    exam, prepared, reads = exam_case()
    with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
        compose_exam_similarity_observation(exam, (review, *prepared[1:]), reads)


@pytest.mark.parametrize("operation", ["prepare", "publish"])
def test_item_context1_publication_rejects_request2_before_io(tmp_path, monkeypatch, operation):
    from eom_orchestrator.control_service import ControlPlaneError

    from tests.unit.test_item_similarity_preparation import preparation_case, prepare

    value = preparation_case(tmp_path, monkeypatch)
    request, _sources, _query = mixed_case()
    value.value.query.request.context_request = request
    with pytest.raises(ControlPlaneError) as error:
        if operation == "prepare":
            prepare(value)
        else:
            value.owner.publish_context(value.caller)
    assert error.value.code == "CONTROL_SIMILARITY_PREPARATION_INVALID"
    assert value.calls == []
