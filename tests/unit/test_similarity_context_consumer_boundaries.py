"""SOURCE-only closed-consumer and dependency checks; no installed tools or grants."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.similarity_context_service import SimilarityContextApplicationService

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_similarity_context_service import CALLER, case

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "purpose", ["ITEM_AUTHORING", "ITEM_REVIEW", "GENERAL_CHAT_READ", "MOCK_EXAM_OBSERVATION"]
)
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


def test_core_has_no_database_filesystem_ml_worker_or_private_owner_calls() -> None:
    forbidden = {"sqlalchemy", "os", "pathlib", "subprocess", "torch", "transformers", "socket"}
    for name in ("similarity_context_service.py", "similarity_context_ports.py"):
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
