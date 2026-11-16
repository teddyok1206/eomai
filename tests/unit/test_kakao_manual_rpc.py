"""Only current owner operations cross the API peer; no runtime assertions from clients."""

import json
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_manual import (
    KakaoManualEnd,
    KakaoManualMutation,
    KakaoManualRenew,
)
from eom_catalog_contracts.kakao_manual_rpc import (
    CommandKakaoManualRequest,
    ReadKakaoManualRequest,
    StartKakaoManualRequest,
    parse_kakao_manual_reply,
)
from eom_catalog_service.kakao_manual_dispatch import KakaoManualApplication, dispatch_kakao_manual
from eom_catalog_service.kakao_manual_service import KakaoManualService

from tests.unit.kakao_manual_fixtures import IDENTITY, KEY, LEASE, session, start


@pytest.mark.parametrize("action", ["start", "renew", "end", "read"])
def test_dispatch_uses_configured_probes_and_stored_intent_reply(action):
    owner = Mock(spec=KakaoManualService)
    profile, runtime = Mock(), Mock()
    application = KakaoManualApplication(owner, profile, runtime)
    if action == "start":
        request = StartKakaoManualRequest(**IDENTITY, command=start(), idempotency_key=KEY)
        method = owner.start_session
        method.return_value = KakaoManualMutation(session=session(), replayed=True)
    elif action == "read":
        request = ReadKakaoManualRequest(**IDENTITY, lease_id=LEASE)
        method = owner.get_session
        method.return_value = session("ACTIVE", 3, 1)
    else:
        command = (
            KakaoManualRenew(expected_grant_revision=1)
            if action == "renew"
            else KakaoManualEnd(expected_resource_version=3)
        )
        request = CommandKakaoManualRequest(
            **IDENTITY, lease_id=LEASE, command=command, idempotency_key=KEY
        )
        method = owner.renew_session if action == "renew" else owner.end_session
        method.return_value = KakaoManualMutation(
            session=session("ACTIVE", 4, 2) if action == "renew" else session("STOPPING", 4, 1),
            replayed=True,
        )
    reply = parse_kakao_manual_reply(
        json.loads(dispatch_kakao_manual(application, request.model_dump(mode="json")))
    )
    assert reply.status == "OK", reply
    actor = method.call_args.args[0]
    assert actor.operator_id == IDENTITY["actor_id"] and not actor.permissions
    if action == "start":
        assert method.call_args.kwargs["observe_profile"] is profile
    if action == "renew":
        assert method.call_args.kwargs["observe_runtime"] is runtime
    if action != "read":
        assert method.call_args.kwargs["idempotency_key"] == KEY
    profile.assert_not_called()
    runtime.assert_not_called()


@pytest.mark.parametrize("field", ["roles", "profile_path", "fence_epoch", "grant", "runtime"])
def test_public_payload_cannot_choose_runtime_or_authority(field):
    owner = Mock(spec=KakaoManualService)
    application = KakaoManualApplication(owner, Mock(), Mock())
    payload = StartKakaoManualRequest(**IDENTITY, command=start(), idempotency_key=KEY).model_dump(
        mode="json"
    )
    payload[field] = "untrusted"
    reply = json.loads(dispatch_kakao_manual(application, payload))
    assert reply["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert not owner.mock_calls


@pytest.mark.parametrize(
    "case", ["wrong-lease", "ready-start", "wrong-binding", "renew-grant", "end-version"]
)
def test_unrelated_or_false_ready_reply_never_reaches_client(case):
    owner = Mock(spec=KakaoManualService)
    application = KakaoManualApplication(owner, Mock(), Mock())
    if case == "wrong-lease":
        request = ReadKakaoManualRequest(**IDENTITY, lease_id="kakaoremotelease_" + "5" * 32)
        owner.get_session.return_value = session()
    elif case == "renew-grant":
        request = CommandKakaoManualRequest(
            **IDENTITY,
            lease_id=LEASE,
            idempotency_key=KEY,
            command=KakaoManualRenew(expected_grant_revision=1),
        )
        owner.renew_session.return_value = KakaoManualMutation(
            session=session("ACTIVE", 4, 1), replayed=True
        )
    elif case == "end-version":
        request = CommandKakaoManualRequest(
            **IDENTITY,
            lease_id=LEASE,
            idempotency_key=KEY,
            command=KakaoManualEnd(expected_resource_version=3),
        )
        owner.end_session.return_value = KakaoManualMutation(
            session=session("STOPPING", 5, 1), replayed=True
        )
    else:
        request = StartKakaoManualRequest(**IDENTITY, command=start(), idempotency_key=KEY)
        value = (
            session("ACTIVE", 3, 1)
            if case == "ready-start"
            else session().model_copy(update={"source_binding_id": "kakaobinding_" + "5" * 32})
        )
        owner.start_session.return_value = KakaoManualMutation(session=value, replayed=True)
    result = json.loads(dispatch_kakao_manual(application, request.model_dump(mode="json")))
    assert result["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID" and result["result"] is None


def test_missing_runtime_composition_and_unsafe_exception_are_explicit():
    request = ReadKakaoManualRequest(**IDENTITY, lease_id=LEASE).model_dump(mode="json")
    assert (
        json.loads(dispatch_kakao_manual(None, request))["error_code"]
        == "CATALOG_APPLICATION_UNAVAILABLE"
    )
    owner = Mock(spec=KakaoManualService)
    owner.get_session.side_effect = RuntimeError("private credentials")
    result = dispatch_kakao_manual(KakaoManualApplication(owner, Mock(), Mock()), request)
    assert b"private credentials" not in result
    assert json.loads(result)["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"
