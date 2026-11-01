"""Common wire2 is exact and bounded; synthetic metadata grants no live authority."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_query_prepare import (
    PRIVATE_CHAT_PREPARE_REPLY_BYTES,
    PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
    PrivateChatQueryPrepareProtocolError,
    parse_private_chat_query_prepare_request,
    private_chat_query_context_request_id,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_query_prepare_v2 import (
    PrivateChatQueryPrepareReplyV2,
    PrivateChatQueryPrepareRequestV2,
    parse_supported_private_chat_query_prepare_request,
    validate_supported_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_similarity import MAX_PRIVATE_CHAT_SIMILARITY_BYTES
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryWorkflowRequestV2
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_query_prepare_application import empty_completed_context
from tests.unit.test_private_chat_query_prepare_exchange import case as case


@pytest.fixture
def common(case):
    old = case
    original, _, _ = execution_case()
    context = seal(
        original.context_request.model_dump(mode="json")
        | {
            "request_id": private_chat_query_context_request_id(old.request.origin),
            "query_basis": old.request.origin.basis.model_dump(mode="json"),
        },
        "request_sha256",
    )
    workflow = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            original.model_dump(mode="json")
            | {
                "context_request": context,
                "operator_audit": original.operator_audit.model_dump(mode="json")
                | {"operator_id": old.request.origin.actor_id},
            },
            "request_sha256",
        )
    )
    request = PrivateChatQueryPrepareRequestV2.model_validate(
        seal(
            old.body
            | {
                "schema_version": "system-rag-private-chat-query-prepare-request/2.0",
                "graph_snapshot": context["graph_snapshot"],
                "policy_revision_id": context["policy_revision_id"],
                "policy_sha256": context["policy_sha256"],
            },
            "request_sha256",
        )
    )
    empty = empty_completed_context(SimpleNamespace(request=workflow))
    reply = PrivateChatQueryPrepareReplyV2(
        schema_version="system-rag-private-chat-query-prepare-reply/2.0",
        action=request.action,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        status="READY",
        workflow_id=old.result.workflow_id,
        context=empty,
        error_code=None,
    )
    return SimpleNamespace(legacy=old, workflow=workflow, request=request, reply=reply)


def test_common_wire_schema_is_independently_pinned_and_legacy_bytes_unchanged(common):
    root = Path(__file__).resolve().parents[2]
    name = "system-rag-private-chat-query-prepare-v2"
    entry = CATALOG_SCHEMA_RESOURCES[name]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    old = CATALOG_SCHEMA_RESOURCES["system-rag-private-chat-query-prepare"]
    assert sha256_bytes((root / old.canonical_path).read_bytes()) == (
        "sha256:9af37ac1dab5062183336016d1522a0e167fe165b592abfc244ee8b689487656"
    )
    Draft202012Validator.check_schema(load_schema(name))
    validate_contract(name, common.request.model_dump(mode="json"))
    validate_contract(name, common.reply.model_dump(mode="json"))
    assert PRIVATE_CHAT_PREPARE_REPLY_BYTES == 640 * 1024
    assert MAX_PRIVATE_CHAT_SIMILARITY_BYTES == 512 * 1024
    assert PrivateChatQueryPrepareReplyV2.maximum_bytes == PRIVATE_CHAT_PREPARE_REPLY_BYTES
    assert PRIVATE_CHAT_PREPARE_REQUEST_BYTES == 32 * 1024
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


def test_supported_request_keeps_exact_versions_and_legacy_parser_rejects_common(common):
    for request in (common.request, common.legacy.request):
        assert parse_supported_private_chat_query_prepare_request(request) == request
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        parse_private_chat_query_prepare_request(common.request)


def test_common_ready_empty_preserves_no_scored_execution_and_never_relabels_legacy(common):
    reply = validate_supported_private_chat_query_prepare_reply(common.request, common.reply)
    assert reply.context.status == "EMPTY"
    assert reply.context.query_execution is None and reply.context.population.scored_count == 0
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        validate_private_chat_query_prepare_reply(common.legacy.request, reply)
    old = common.legacy.dispatch.execute(common.legacy.request)
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        validate_supported_private_chat_query_prepare_reply(common.request, old)


@pytest.mark.parametrize("field", ("text", "path", "actor_id", "actor_role", "index", "runtime"))
def test_request_cannot_supply_question_authority_or_runtime(common, field):
    value = common.request.model_dump(mode="json") | {field: "DO_NOT_DISCLOSE_PRIVATE_INPUT"}
    with pytest.raises(PrivateChatQueryPrepareProtocolError) as error:
        parse_supported_private_chat_query_prepare_request(value)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_REQUEST_INVALID"


@pytest.mark.parametrize(
    "version", (None, "2.1", "system-rag-private-chat-query-prepare-request/3.0")
)
def test_unknown_family_never_defaults_to_an_older_request(common, version):
    body = common.request.model_dump(mode="json") | {"schema_version": version}
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        parse_supported_private_chat_query_prepare_request(seal(body, "request_sha256"))


def test_mutated_models_and_oversize_input_are_revalidated_and_redacted(common):
    invalid = common.request.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        parse_supported_private_chat_query_prepare_request(invalid)
    body = common.request.model_dump(mode="json") | {
        "request_id": "DO_NOT_DISCLOSE_PRIVATE_INPUT" * PRIVATE_CHAT_PREPARE_REQUEST_BYTES
    }
    with pytest.raises(PrivateChatQueryPrepareProtocolError) as error:
        parse_supported_private_chat_query_prepare_request(body)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_REQUEST_INVALID"


@pytest.mark.parametrize(
    "field,value",
    (
        ("request_id", "chatqueryprepare_" + "f" * 32),
        ("request_sha256", "sha256:" + "f" * 64),
        ("action", "READ_PRIVATE_CHAT_QUERY"),
    ),
)
def test_reply_must_match_the_exact_rpc_request(common, field, value):
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        validate_supported_private_chat_query_prepare_reply(
            common.request, common.reply.model_copy(update={field: value})
        )


@pytest.mark.parametrize("field", ("policy", "graph", "basis", "context_id"))
def test_ready_context_cannot_cross_original_scope(common, field):
    context = common.reply.context.model_dump(mode="json")
    selected = context["request"]
    if field == "policy":
        selected["policy_sha256"] = "sha256:" + "f" * 64
    elif field == "graph":
        selected["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    elif field == "context_id":
        selected["request_id"] = "similarityrequest_" + "f" * 32
    else:
        selected["query_basis"] = seal(
            selected["query_basis"] | {"turn_id": "chatturn_" + "f" * 32}, "basis_sha256"
        )
    context["request"] = seal(selected, "request_sha256")
    altered = common.reply.model_dump(mode="json") | {"context": seal(context, "context_sha256")}
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        validate_supported_private_chat_query_prepare_reply(common.request, altered)


@pytest.mark.parametrize(
    "updates",
    (
        {"workflow_id": None},
        {"context": None},
        {"status": "PENDING"},
        {"status": "PENDING", "context": None, "workflow_id": None},
        {"status": "FAILED", "context": None, "error_code": None},
        {"status": "UNAVAILABLE", "context": None, "error_code": "SOURCE_ACCESS_DENIED"},
        {"status": "FAILED", "context": None, "error_code": "PRIVATE_CHAT_QUERY_NOT_PREPARED"},
    ),
)
def test_schema_itself_closes_ambiguous_states(common, updates):
    body = common.reply.model_dump(mode="json") | updates
    with pytest.raises(SchemaError):
        validate_contract("system-rag-private-chat-query-prepare-v2", body)


def test_wire_envelope_keeps_the_original_context_and_hash_without_copy_projection(common):
    raw = canonical_json_bytes(common.reply)
    assert len(raw) <= PRIVATE_CHAT_PREPARE_REPLY_BYTES
    parsed = validate_supported_private_chat_query_prepare_reply(common.request, common.reply)
    assert parsed.context == common.reply.context
    assert parsed.context.context_sha256 == common.reply.context.context_sha256
