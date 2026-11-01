"""SOURCE-only closed-consumer and dependency checks; no installed tools or grants."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.registered_public_solution_index import (
    RegisteredPublicSolutionProfilePointer,
)
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_context_service import SimilarityContextApplicationService

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_registered_public_solution_index import successor
from tests.unit.test_similarity_context_service import CALLER, case

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("registered", (False, True))
def test_legacy_composer_does_not_reinterpret_either_common_public_binding_family(registered):
    request, source, query = case()
    _old, index, _pointer, _rows = successor()
    binding = next(
        value
        for value in index.bindings
        if isinstance(value.profile, RegisteredPublicSolutionProfilePointer) is registered
    )
    reads = {read.intent.selection.view: read for read in source.reads}
    view = source.reads[0].intent.selection.view
    # Exercise the composer's own closed-family guard independently of the
    # earlier document-reader validation, with a real validated successor DTO.
    reads[view] = replace(reads[view], bindings=(binding,))
    native = query.value
    vectors = read_unit_vectors(
        native.binary,
        dimension=native.result.shard.dimension,
        row_count=native.result.shard.row_count,
        expected_sha256=native.result.shard.binary.sha256,
    )
    with pytest.raises(SimilarityContextReadError, match="INDEX_POINTER_INVALID"):
        SimilarityContextApplicationService._compose(
            request,
            source.prepared,
            {value.source.item_revision_id: value for value in source.prepared.sources},
            native,
            vectors,
            reads,
            "QUERY_NOT_OFFERED",
        )


@pytest.mark.parametrize("purpose", ["GENERAL_CHAT_READ", "MOCK_EXAM_OBSERVATION"])
def test_unconnected_consumers_have_no_authority_or_implicit_variation_fallback(
    purpose: str,
) -> None:
    request, source, query = case()
    changed = parse_similarity_context_request(
        seal(request.model_dump(mode="json") | {"consumer_purpose": purpose}, "request_sha256")
    )
    result = SimilarityContextApplicationService(source, query).compose(CALLER, changed)
    assert result.status == "FAILED" and result.error_code == "AUTHORITY_UNAVAILABLE"
    assert not source.calls and query.calls == 0
    assert not result.candidates and result.population is None


@pytest.mark.parametrize("purpose", ["ITEM_AUTHORING", "ITEM_REVIEW"])
def test_authoring_reference_uses_same_composer_without_claiming_private_query(purpose):
    request, source, query = case(consumer_purpose=purpose)
    result = SimilarityContextApplicationService(source, query).compose(CALLER, request)
    assert result.status == "READY" and result.error_code is None
    assert result.request.consumer_purpose == purpose
    assert result.request.anchor.basis == "APPROVED_REFERENCE_ITEM"
    assert result.candidates and result.query_execution is not None
    assert source.calls == ["prepare", "read", "reauthorize"] and query.calls == 1
    old, _, _ = case()
    assert old.request_id == request.request_id
    assert old.request_sha256 != request.request_sha256


@pytest.mark.parametrize("purpose", ["ITEM_AUTHORING", "ITEM_REVIEW"])
def test_authoring_reference_cannot_relabel_completed_variation_query(purpose):
    request, source, _query = case(consumer_purpose=purpose)
    _old, _old_source, old_query = case()
    result = SimilarityContextApplicationService(source, old_query).compose(CALLER, request)
    assert result.status == "FAILED" and result.error_code == "QUERY_RESULT_INVALID"
    assert not result.candidates and result.population is None
    assert "read" not in source.calls


@pytest.mark.parametrize("purpose", ["ITEM_AUTHORING", "ITEM_REVIEW"])
def test_authoring_reference_rechecks_late_source_permission(purpose):
    request, source, query = case(consumer_purpose=purpose)
    source.denial = "synthetic revocation"
    result = SimilarityContextApplicationService(source, query).compose(CALLER, request)
    assert result.status == "FAILED" and result.error_code == "SOURCE_REVOKED"
    assert not result.candidates and result.population is None
    assert source.calls == ["prepare", "read", "reauthorize"]


def test_core_has_no_database_filesystem_ml_worker_or_private_owner_calls() -> None:
    forbidden = {"sqlalchemy", "os", "pathlib", "subprocess", "torch", "transformers", "socket"}
    for name in (
        "similarity_context_service.py",
        "similarity_context_ports.py",
        "private_chat_similarity_service.py",
        "private_chat_similarity_ports.py",
        "similarity_document_read_validation.py",
    ):
        path = ROOT / "services/catalog_service/eom_catalog_service" / name
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                modules = (
                    [value.name for value in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                assert not any(module.split(".")[0] in forbidden for module in modules)
                assert not any(
                    "embedding_registry_repository" in module
                    or "embedding_registry_catalog_adapter" in module
                    for module in modules
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr
                in {
                    "sources",
                    "query_reads",
                }
            ):
                assert not node.func.attr.startswith("_")


def test_similarity_does_not_import_benchmark_or_existing_on_demand_encoder() -> None:
    source = (
        ROOT / "services/catalog_service/eom_catalog_service/similarity_context_service.py"
    ).read_text()
    assert "embedding_device_benchmark" not in source
    assert "ExactLocalEmbeddingRanker" not in source and "backend.encode(" not in source
    assert "embedding_encoder_adapter" not in source and "embedding_offline_backend" not in source
    assert "evidence_id" not in source
    assert ".approve(" not in source and ".register(" not in source
