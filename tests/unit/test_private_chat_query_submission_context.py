"""Closed original metadata, not source admission, a real claim or Workflow execution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_submission_context import (
    PrivateChatQuerySubmissionContext,
    PrivateChatQuerySubmissionContextError,
    build_private_chat_query_submission_context,
    parse_private_chat_query_submission_context,
    private_chat_query_submission_fingerprint,
    private_chat_query_submission_key,
    private_chat_query_turn_identity,
    validate_private_chat_query_submission_context,
)
from eom_workflow.schemas import (
    PRIVATE_CHAT_QUERY_SUBMISSION_SCHEMA_RESOURCE,
    load_local_embedding_admission_schema,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case
from tests.unit.test_private_chat_query_source import source_case


def context_case():
    request, _policy, _bundle = execution_case()
    source = source_case(question=TEXT)
    projection = source.execution.materialize_live_private_query(source.ticket)
    request = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "operator_audit": request.operator_audit.model_dump(mode="json")
                | {"operator_id": projection.origin.actor_id},
                "context_request": seal(
                    request.context_request.model_dump(mode="json")
                    | {"query_basis": projection.origin.basis.model_dump(mode="json")},
                    "request_sha256",
                ),
            },
            "request_sha256",
        )
    )
    return SimpleNamespace(
        request=request,
        context=build_private_chat_query_submission_context(request, projection.origin),
    )


def fingerprint(value, context=None, **overrides):
    fields = {
        "definition_sha256": value.request.workflow_definition_sha256,
        "actor_type": "human",
        "actor_id": value.context.origin.actor_id,
    } | overrides
    return private_chat_query_submission_fingerprint(
        value.request, context or value.context, **fields
    )


def test_schema_first_pinned_resource_and_exact_private_static_admission():
    _name, filename, identity, digest = PRIVATE_CHAT_QUERY_SUBMISSION_SCHEMA_RESOURCE
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    schema = load_local_embedding_admission_schema("private-chat-submission")
    assert schema["$id"] == identity
    Draft202012Validator.check_schema(schema)
    assert workflow_definition_is_admitted("local-embedding-private-chat-query", "1.0.0")


def test_exact_origin_and_existing_empty_pointer_value_are_small_immutable_metadata():
    value = context_case()
    context = validate_private_chat_query_submission_context(value.request, value.context)
    assert context == build_private_chat_query_submission_context(value.request, context.origin)
    assert context.artifact_pointers == ()
    raw = canonical_json_bytes(context)
    assert TEXT.encode() not in raw and b'"text"' not in raw and len(raw) < 8192
    assert context.context_sha256 == content_sha256(
        context.model_dump(mode="json", exclude={"context_sha256"})
    )
    assert parse_private_chat_query_submission_context(context.model_dump(mode="json")) == context
    actor, conversation, turn = private_chat_query_turn_identity(context)
    assert (actor, conversation, turn) == (
        context.origin.actor_id,
        context.origin.basis.conversation_id,
        context.origin.basis.turn_id,
    )
    assert private_chat_query_submission_key(context) == f"private-chat-query:{actor}:{turn}"
    assert len(private_chat_query_submission_key(context)) <= 128
    assert fingerprint(value) == fingerprint(value)
    with pytest.raises(ValueError):
        context.context_sha256 = "sha256:" + "f" * 64


@pytest.mark.parametrize(
    "fault", ["version", "purpose", "text", "pointers", "hash", "missing", "copied"]
)
def test_untrusted_context_extras_and_purpose_changes_fail_without_question_leak(fault):
    value = context_case()
    body = value.context.model_dump(mode="json")
    if fault == "version":
        body["schema_version"] = "reference-query/1.0"
    elif fault == "purpose":
        body["purpose"] = "REFERENCE_QUERY"
    elif fault == "text":
        body["question"] = TEXT
    elif fault == "pointers":
        body["artifact_pointers"] = [value.context.origin.request_member.model_dump(mode="json")]
    elif fault == "missing":
        body.pop("origin")
    elif fault == "copied":
        body = value.context.model_copy(update={"actor_role": TEXT})
    else:
        body["context_sha256"] = "sha256:" + "f" * 64
    if fault not in {"copied", "hash"}:
        body = seal(body, "context_sha256")
    with pytest.raises(PrivateChatQuerySubmissionContextError) as error:
        parse_private_chat_query_submission_context(body)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
    assert TEXT not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize("fault", ["request", "actor", "turn"])
def test_resealed_parent_or_origin_cannot_replace_original_submission(fault):
    value = context_case()
    body = value.context.model_dump(mode="json")
    if fault == "request":
        body["workflow_request_sha256"] = "sha256:" + "f" * 64
    else:
        origin = body["origin"]
        if fault == "actor":
            origin["actor_id"] = "operator_" + "f" * 32
        else:
            origin["basis"] = seal(
                origin["basis"] | {"turn_id": "chatturn_" + "f" * 32}, "basis_sha256"
            )
            origin["ticket"]["turn_id"] = "chatturn_" + "f" * 32
        body["origin"] = seal(origin, "origin_sha256")
    context = PrivateChatQuerySubmissionContext.model_validate(seal(body, "context_sha256"))
    with pytest.raises(PrivateChatQuerySubmissionContextError):
        validate_private_chat_query_submission_context(value.request, context)


@pytest.mark.parametrize("field", ["runtime", "claim"])
def test_new_claim_changes_fingerprint_but_cannot_invent_another_turn_key(field):
    value = context_case()
    origin = value.context.origin.model_dump(mode="json")
    if field == "runtime":
        origin["runtime_id"] = "chatrt_" + "f" * 32
    else:
        original = origin["ticket"]["claim_id"]
        origin["ticket"]["claim_id"] = original.rsplit("_", 1)[0] + "_" + "f" * 32
    changed = build_private_chat_query_submission_context(
        value.request, ChatPrivateQueryOrigin.model_validate(seal(origin, "origin_sha256"))
    )
    assert changed.context_sha256 != value.context.context_sha256
    assert fingerprint(value, changed) != fingerprint(value)
    assert private_chat_query_submission_key(changed) == private_chat_query_submission_key(
        value.context
    )
    assert private_chat_query_turn_identity(changed) == private_chat_query_turn_identity(
        value.context
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"actor_type": "system"},
        {"actor_id": "operator_" + "f" * 32},
        {"definition_sha256": "sha256:" + "f" * 64},
    ],
)
def test_fingerprint_does_not_let_other_actor_or_definition_borrow_origin(overrides):
    with pytest.raises(PrivateChatQuerySubmissionContextError):
        fingerprint(context_case(), **overrides)
