"""Identity-carrying private RPC; source authorization remains in the application."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_archive_binding import (
    KakaoBindingCreate,
    KakaoBindingMutation,
    KakaoBindingPage,
    KakaoBindingRetire,
    KakaoBindingUpdatePolicy,
    KakaoCollectionPolicy,
    KakaoCollectionPolicyRevision,
    KakaoSourceBinding,
    collection_policy_sha256,
)
from eom_catalog_contracts.kakao_archive_rpc import (
    CommandKakaoBindingReply,
    CommandKakaoBindingRequest,
    CreateKakaoBindingReply,
    CreateKakaoBindingRequest,
    KakaoBindingFailure,
    ListKakaoBindingsReply,
    ListKakaoBindingsRequest,
    ReadKakaoBindingReply,
    ReadKakaoBindingRequest,
    check_kakao_binding_reply,
    parse_kakao_binding_reply,
    parse_kakao_binding_request,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_dispatch import dispatch_kakao_binding
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_operator_identity import ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, tzinfo=UTC)
BINDING = "kakaobinding_" + "1" * 32
POLICY = "kakaopolicyrev_" + "2" * 32
IDENTITY = {
    "actor_id": "operator_" + "3" * 32,
    "session_id": "apisession_" + "4" * 32,
    "request_id": "webreq_fixture",
    "authentication_time": NOW,
}
KEY = "fixture-idempotency-0001"


@pytest.fixture
def binding():
    policy = KakaoCollectionPolicy()
    return KakaoSourceBinding(
        source_binding_id=BINDING,
        display_name="fixture",
        state="DRAFT",
        resource_version=1,
        policy_revision=KakaoCollectionPolicyRevision(
            source_binding_id=BINDING,
            policy_revision_id=POLICY,
            previous_revision_id=None,
            revision_number=1,
            sha256=collection_policy_sha256(policy),
            policy=policy,
            created_at=NOW,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def create_request():
    return CreateKakaoBindingRequest(
        **IDENTITY,
        idempotency_key=KEY,
        command=KakaoBindingCreate(display_name="fixture", policy=KakaoCollectionPolicy()),
    )


@pytest.mark.parametrize("action", ["create", "read", "list", "retire", "policy"])
def test_dispatch_reuses_owner_application_and_actual_api_identity(binding, action):
    service = Mock(spec=KakaoArchiveService)
    if action == "create":
        request = create_request()
        service.create_binding.return_value = KakaoBindingMutation(binding=binding, replayed=False)
        method = service.create_binding
    elif action == "read":
        request = ReadKakaoBindingRequest(**IDENTITY, source_binding_id=BINDING)
        service.get_binding.return_value = binding
        method = service.get_binding
    elif action == "list":
        request = ListKakaoBindingsRequest(**IDENTITY)
        service.list_bindings.return_value = KakaoBindingPage(items=(binding,), next_cursor=None)
        method = service.list_bindings
    else:
        if action == "retire":
            command = KakaoBindingRetire(
                parent_policy_revision_id=POLICY, expected_resource_version=1
            )
            result_binding = binding.model_copy(update={"state": "RETIRED", "resource_version": 2})
        else:
            new_policy = KakaoCollectionPolicy(interval_minutes=120)
            command = KakaoBindingUpdatePolicy(
                parent_policy_revision_id=POLICY,
                expected_resource_version=1,
                policy=new_policy,
            )
            successor = KakaoCollectionPolicyRevision(
                source_binding_id=BINDING,
                policy_revision_id="kakaopolicyrev_" + "5" * 32,
                previous_revision_id=POLICY,
                revision_number=2,
                sha256=collection_policy_sha256(new_policy),
                policy=new_policy,
                created_at=NOW,
            )
            result_binding = binding.model_copy(
                update={"policy_revision": successor, "resource_version": 2}
            )
        request = CommandKakaoBindingRequest(
            **IDENTITY, source_binding_id=BINDING, idempotency_key=KEY, command=command
        )
        service.command_binding.return_value = KakaoBindingMutation(
            binding=result_binding, replayed=False
        )
        method = service.command_binding
    reply = parse_kakao_binding_reply(
        json.loads(dispatch_kakao_binding(service, request.model_dump(mode="json")))
    )
    assert reply.status == "OK" and reply.request_id == request.request_id
    check_kakao_binding_reply(request, reply)
    assert method.call_count == 1
    actor = method.call_args.args[0]
    assert actor.operator_id == IDENTITY["actor_id"] and actor.session_id == IDENTITY["session_id"]
    assert actor.request_id == IDENTITY["request_id"] and actor.authentication_time == NOW
    assert actor.permissions == frozenset()
    assert actor.actor_type is ActorType.OPERATOR and actor.source is ActorSource.APPLICATION_API
    if action in {"create", "retire", "policy"}:
        assert method.call_args.kwargs == {"idempotency_key": KEY}


@pytest.mark.parametrize(
    "field,value", [("roles", ["ADMIN"]), ("permissions", ["WRITE"]), ("path", "/secret")]
)
def test_caller_authority_and_unknown_fields_rejected_before_service(field, value):
    service = Mock(spec=KakaoArchiveService)
    raw = create_request().model_dump(mode="json")
    raw[field] = value
    reply = json.loads(dispatch_kakao_binding(service, raw))
    assert reply["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert service.mock_calls == []


@pytest.mark.parametrize("limit", [True, "10", 0, 101, -1])
def test_list_limit_wire_and_model_strict(limit):
    raw = ListKakaoBindingsRequest(**IDENTITY).model_dump(mode="json")
    raw["limit"] = limit
    with pytest.raises((ValidationError, SchemaError)):
        parse_kakao_binding_request(raw)


def test_unavailable_and_private_errors_are_stable_and_redacted():
    raw = create_request().model_dump(mode="json")
    reply = json.loads(dispatch_kakao_binding(None, raw))
    assert reply["error_code"] == "CATALOG_APPLICATION_UNAVAILABLE"
    service = Mock(spec=KakaoArchiveService)
    service.create_binding.side_effect = KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
    assert json.loads(dispatch_kakao_binding(service, raw))["error_code"] == (
        "KAKAO_ARCHIVE_PERMISSION_DENIED"
    )
    service.create_binding.side_effect = KakaoArchiveError("private-message-contents")
    encoded = dispatch_kakao_binding(service, raw)
    assert b"private-message" not in encoded
    assert json.loads(encoded)["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"
    service.create_binding.side_effect = RuntimeError("credential=private")
    encoded = dispatch_kakao_binding(service, raw)
    assert b"credential" not in encoded
    assert json.loads(encoded)["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"


def test_unrelated_read_result_is_not_exposed(binding):
    service = Mock(spec=KakaoArchiveService)
    service.get_binding.return_value = binding
    request = ReadKakaoBindingRequest(**IDENTITY, source_binding_id="kakaobinding_" + "9" * 32)
    encoded = dispatch_kakao_binding(service, request.model_dump(mode="json"))
    reply = json.loads(encoded)
    assert reply["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID" and reply["result"] is None
    assert binding.source_binding_id.encode() not in encoded


def test_request_correlation_and_operation_are_checked(binding):
    request = ReadKakaoBindingRequest(**IDENTITY, source_binding_id=BINDING)
    for reply in (
        ReadKakaoBindingReply(request_id="webreq_other", result=binding),
        CreateKakaoBindingReply(
            request_id=request.request_id,
            result=KakaoBindingMutation(binding=binding, replayed=False),
        ),
        KakaoBindingFailure(
            operation=request.operation,
            request_id="webreq_other",
            error_code="KAKAO_ARCHIVE_PERMISSION_DENIED",
        ),
    ):
        with pytest.raises(ValueError, match="RESULT_INVALID"):
            check_kakao_binding_reply(request, reply)


@pytest.mark.parametrize("case", ["duplicate", "past-cursor", "extra", "next-cursor"])
def test_list_result_cannot_escape_requested_page(binding, case):
    request = ListKakaoBindingsRequest(**IDENTITY, limit=1)
    values = (binding,)
    cursor = None
    if case in {"duplicate", "extra"}:
        values = (binding, binding)
    elif case == "past-cursor":
        request = request.model_copy(update={"cursor": BINDING})
    else:
        cursor = "kakaobinding_" + "9" * 32
    reply = ListKakaoBindingsReply(
        request_id=request.request_id, result=KakaoBindingPage(items=values, next_cursor=cursor)
    )
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_kakao_binding_reply(request, reply)


def test_retire_reply_must_reference_exact_policy(binding):
    request = CommandKakaoBindingRequest(
        **IDENTITY,
        source_binding_id=BINDING,
        idempotency_key=KEY,
        command=KakaoBindingRetire(
            parent_policy_revision_id="kakaopolicyrev_" + "9" * 32,
            expected_resource_version=1,
        ),
    )
    reply = CommandKakaoBindingReply(
        request_id=request.request_id,
        result=KakaoBindingMutation(
            binding=binding.model_copy(update={"state": "RETIRED", "resource_version": 2}),
            replayed=True,
        ),
    )
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_kakao_binding_reply(request, reply)


def test_discriminator_prevents_cross_operation_result(binding):
    value = ReadKakaoBindingReply(request_id="webreq_fixture", result=binding).model_dump(
        mode="json"
    )
    value["operation"] = "CREATE_KAKAO_BINDING"
    with pytest.raises((ValidationError, SchemaError)):
        parse_kakao_binding_reply(value)
