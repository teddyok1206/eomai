"""Completed-read4 preserves exact actor/pins and old read3; synthetic source/transport."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services import similarity_context_client as client_module
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_contracts.similarity_read_v3 import SimilarityContextReadReplyV3
from eom_catalog_contracts.similarity_read_v4 import (
    SimilarityContextReadReplyV4,
    SimilarityContextReadRequestV4,
    validate_similarity_read_reply_v4,
)
from eom_catalog_service.similarity_read_dispatch import dispatch_similarity_read_frame
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)


def pair(*, registered=True):
    context = registered_similarity_case()[1] if registered else public_similarity_case()[1]
    request = SimilarityContextReadRequestV4(
        schema_version="system-rag-similarity-read-request/4.0",
        operation="READ_SIMILARITY_CONTEXT",
        actor_id="operator_" + "1" * 32,
        selection=CompletedSimilarityQuerySelection(
            workflow_id="workflow_" + "2" * 32,
            workflow_request_sha256="sha256:" + "3" * 64,
            context_request_sha256=context.request.request_sha256,
        ),
    )
    reply = SimilarityContextReadReplyV4(
        schema_version="system-rag-similarity-read-reply/4.0",
        operation="READ_SIMILARITY_CONTEXT",
        status="SUCCESS",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request.model_dump(mode="json")),
        result=context,
        error_code=None,
    )
    return request, reply


@pytest.mark.parametrize("registered", [False, True])
def test_dispatch_and_api_client_keep_registered_context_and_same_actor(monkeypatch, registered):
    request, reply = pair(registered=registered)
    validate_similarity_read_reply_v4(request, reply)
    service = SimpleNamespace(read=Mock(return_value=reply.result))

    def exchange(endpoint, value, **options):
        assert value == request.model_dump(mode="json")
        assert options["request_limit"] == options["reply_limit"] == 1024 * 1024
        return json.loads(
            dispatch_similarity_read_frame(service, canonical_json_bytes(value) + b"\n")
        )

    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogSimilarityContextClient(
        ChatSocketEndpoint(Path("/tmp/synthetic-read4.sock"), 42, 43)
    )
    assert client.read_public(request.actor_id, request.selection) == reply.result
    service.read.assert_called_once_with(request)
    with pytest.raises((ValueError, SchemaError)):
        SimilarityContextReadReplyV3.model_validate(reply.model_dump(mode="json"))


@pytest.mark.parametrize("field", ["actor_id", "request_sha256", "selection"])
def test_read4_reply_cannot_replace_actor_or_original_selector(field):
    request, reply = pair()
    if field == "selection":
        request = request.model_copy(
            update={
                "selection": request.selection.model_copy(
                    update={"context_request_sha256": "sha256:" + "f" * 64}
                )
            }
        )
    else:
        reply = reply.model_copy(
            update={field: "operator_" + "f" * 32 if field == "actor_id" else "sha256:" + "f" * 64}
        )
    with pytest.raises(ValueError):
        validate_similarity_read_reply_v4(request, reply)


def test_read4_schema_is_mirrored_pinned_and_legacy_unchanged():
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/knowledge/system-rag-similarity-read-v4.schema.json").read_bytes()
    assert (
        raw
        == (
            root
            / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
            / "system-rag-similarity-read-v4.schema.json"
        ).read_bytes()
    )
    assert (
        sha256_bytes(raw)
        == "sha256:27b0001939579083763a4af2f987bbfd6c6a4f66b52ee22cf40d1a55a7790561"
    )
    assert (
        sha256_bytes(
            (root / "schemas/knowledge/system-rag-similarity-read-v3.schema.json").read_bytes()
        )
        == "sha256:75a8f5f54a2f41ef62e90779cd342fe4bd72b5dc4296b129018517c7125a374d"
    )


@pytest.mark.parametrize("extra", ["authority", "source_text", "runtime", "path"])
def test_read4_does_not_accept_model_supplied_authority_or_payload(extra):
    request, _ = pair()
    body = request.model_dump(mode="json") | {extra: "untrusted"}
    with pytest.raises((ValueError, SchemaError)):
        SimilarityContextReadRequestV4.model_validate(body)
