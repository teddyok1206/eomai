"""Public completed read wire and owner selection; no model, GPU, or live authority."""

import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_api.services import similarity_context_client as client_module
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.similarity_read import (
    CompletedSimilarityQuerySelection,
    SimilarityContextReadReply,
    SimilarityContextReadRequest,
)
from eom_catalog_contracts.similarity_read_v2 import (
    SimilarityContextReadReplyV2,
    SimilarityContextReadRequestV2,
)
from eom_catalog_contracts.similarity_read_v3 import (
    SimilarityContextReadReplyV3,
    SimilarityContextReadRequestV3,
    validate_similarity_read_reply_v3,
)
from eom_catalog_service import similarity_read_service as read_module
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_read_dispatch import dispatch_similarity_read_frame
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import create_engine

from tests.unit.test_public_solution_similarity_contracts import public_similarity_case

ERRORS = (ValueError, SchemaError)


def pair():
    context = public_similarity_case()[1]
    request = SimilarityContextReadRequestV3(
        schema_version="system-rag-similarity-read-request/3.0",
        operation="READ_SIMILARITY_CONTEXT",
        actor_id="operator_" + "1" * 32,
        selection=CompletedSimilarityQuerySelection(
            workflow_id="workflow_" + "2" * 32,
            workflow_request_sha256="sha256:" + "3" * 64,
            context_request_sha256=context.request.request_sha256,
        ),
    )
    reply = SimilarityContextReadReplyV3(
        schema_version="system-rag-similarity-read-reply/3.0",
        operation="READ_SIMILARITY_CONTEXT",
        status="SUCCESS",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request.model_dump(mode="json")),
        result=context,
        error_code=None,
    )
    return request, reply


def test_read3_schema_mirror_and_pin():
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/knowledge/system-rag-similarity-read-v3.schema.json").read_bytes()
    assert (
        raw
        == (
            root
            / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
            / "system-rag-similarity-read-v3.schema.json"
        ).read_bytes()
    )
    assert sha256_bytes(raw) == (
        "sha256:75a8f5f54a2f41ef62e90779cd342fe4bd72b5dc4296b129018517c7125a374d"
    )


def test_public_read_is_closed_and_legacy_families_cannot_accept_it():
    request, reply = pair()
    validate_similarity_read_reply_v3(request, reply)
    for parser in (SimilarityContextReadRequest, SimilarityContextReadRequestV2):
        with pytest.raises(ERRORS):
            parser.model_validate(request.model_dump(mode="json"))
    for parser in (SimilarityContextReadReply, SimilarityContextReadReplyV2):
        with pytest.raises(ERRORS):
            parser.model_validate(reply.model_dump(mode="json"))


@pytest.mark.parametrize("field", ("authority", "runtime", "source_ids", "query_text", "path"))
def test_no_execution_or_source_authority_fields(field):
    request, _ = pair()
    with pytest.raises(ERRORS):
        SimilarityContextReadRequestV3.model_validate(
            request.model_dump(mode="json") | {field: "not-a-grant"}
        )


@pytest.mark.parametrize("change", ("actor_id", "request_sha256", "selection"))
def test_reply_binding_requires_exact_actual_actor_request_and_context(change):
    request, reply = pair()
    if change == "selection":
        request = request.model_copy(
            update={
                "selection": request.selection.model_copy(
                    update={
                        "context_request_sha256": "sha256:" + "e" * 64,
                    }
                ),
            }
        )
    else:
        reply = reply.model_copy(
            update={
                change: "operator_" + "e" * 32 if change == "actor_id" else "sha256:" + "e" * 64,
            }
        )
    with pytest.raises(ERRORS):
        validate_similarity_read_reply_v3(request, reply)


def test_dispatch_and_api_client_keep_public_family_and_actual_caller(monkeypatch):
    request, reply = pair()
    service = NS(read=Mock(return_value=reply.result))

    def exchange(endpoint, value, **options):
        assert value == request.model_dump(mode="json")
        assert options["timeout"] == 90
        return json.loads(
            dispatch_similarity_read_frame(service, canonical_json_bytes(value) + b"\n")
        )

    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogSimilarityContextClient(ChatSocketEndpoint(Path("/tmp/synthetic.sock"), 42, 43))
    assert client.read_public(request.actor_id, request.selection) == reply.result
    service.read.assert_called_once_with(request)


@pytest.mark.parametrize("missing", (True, False))
def test_public_errors_do_not_fall_back_to_legacy_or_expose_exception_prose(missing):
    request, _ = pair()
    service = None if missing else NS(read=Mock(side_effect=RuntimeError("private detail")))
    raw = dispatch_similarity_read_frame(service, canonical_json_bytes(request) + b"\n")
    reply = SimilarityContextReadReplyV3.model_validate(json.loads(raw))
    validate_similarity_read_reply_v3(request, reply)
    assert reply.status == "FAILED" and reply.result is None
    assert reply.error_code == "SIMILARITY_CONTEXT_UNAVAILABLE"
    assert b"private detail" not in raw


def test_service_uses_only_the_explicit_public_owner_and_existing_completed_reader(
    tmp_path, monkeypatch
):
    request, reply = pair()
    engine = create_engine("sqlite://")
    registry = NS(
        namespace=PublicSolutionIndexNamespace(
            storage_partition="public-solution",
            space_sha256=reply.result.request.views[0].index.spaces.document.space_sha256,
            recipe_sha256=reply.result.request.views[0].recipe.recipe_sha256,
        )
    )
    primary = NS(catalog=NS(engine=engine))
    public_owner = NS(catalog=NS(engine=engine), configuration=NS(registry=registry))
    calls = []

    def completed(session, owner, caller, selection):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert owner is public_owner
        assert caller == EmbeddingRegistryCaller(request.actor_id)
        assert selection == request.selection
        calls.append(selection)
        return reply.result

    monkeypatch.setattr(
        read_module, "read_completed_public_solution_similarity_in_session", completed
    )
    service = CatalogSimilarityContextReadService(primary, public_owner=public_owner)
    assert service.read(request) == reply.result
    assert calls == [request.selection]
    with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
        CatalogSimilarityContextReadService(primary).read(request)

    def denied(*_args):
        raise OperatorAuthorizationFenceError("AUTHORITY_UNAVAILABLE")

    monkeypatch.setattr(read_module, "read_completed_public_solution_similarity_in_session", denied)
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        service.read(request)
    engine.dispose()
