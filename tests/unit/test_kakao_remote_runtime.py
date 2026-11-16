"""Private runtime rules with synthetic principals and local sockets only."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from eom_kakao_archive_contracts.kakao_remote import (
    SCHEMA_SHA256,
    CurrentRemoteAuthority,
    GatewayLeaseGrant,
    GatewayRevocation,
    ProfileFence,
    ProfileStopReceipt,
    RemoteAuthorizationError,
    RemoteLease,
    RemoteRequest,
    RemoteRuntime,
    RemoteTransportPolicy,
    authorize_remote_request,
    end_remote_lease,
    gateway_grant,
    renew_remote_lease,
    validate_profile_handoff,
    validate_remote_contract,
)
from eom_kakao_archive_worker.remote_gateway_lifetime import (
    GatewayLifetimeState,
    RemoteGatewayLifetime,
)
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def identity(prefix: str, ordinal: int = 1) -> str:
    return f"{prefix}_{ordinal:032x}"


def change(model, **values):
    return type(model).model_validate({**model.model_dump(), **values})


@pytest.fixture
def values():
    lease = RemoteLease(
        schema_version="kakao-remote-lease/1.0",
        lease_id=identity("kakaoremotelease"),
        source_binding_id=identity("kakaobinding"),
        profile_id=identity("kakaoprofile"),
        fence_epoch=3,
        gateway_epoch=4,
        grant_revision=1,
        issued_at=NOW,
        authorized_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        absolute_expires_at=NOW + timedelta(minutes=20),
        operator_id=identity("operator"),
        identity_session_id=identity("apisession"),
        state="ACTIVE",
        ended_at=None,
    )
    authority = CurrentRemoteAuthority(
        schema_version="kakao-remote-authority/1.0",
        operator_id=lease.operator_id,
        identity_session_id=lease.identity_session_id,
        source_binding_id=lease.source_binding_id,
        binding_owner_operator_id=lease.operator_id,
        operator_active=True,
        session_active=True,
        is_admin=True,
        remote_permission=True,
        source_active=True,
        source_access=True,
        checked_at=NOW,
    )
    runtime = RemoteRuntime(
        schema_version="kakao-remote-runtime/1.0",
        source_binding_id=lease.source_binding_id,
        profile_id=lease.profile_id,
        mode="MANUAL",
        fence_epoch=3,
        gateway_epoch=4,
        browser_run_id=identity("kakaobrowserrun"),
        process_state="RUNNING",
        profile_locked=True,
        available=True,
    )
    request = RemoteRequest(
        schema_version="kakao-remote-request/1.0",
        method="GET",
        path="/studio/admin/remote/websockify",
        protocol="HTTP/1.1",
        origin="https://studio.invalid",
        upgrade="websocket",
        connection="keep-alive, Upgrade",
        websocket_version="13",
        websocket_key=base64.b64encode(b"0123456789abcdef").decode(),
    )
    policy = RemoteTransportPolicy(
        expected_origin="https://studio.invalid",
        static_paths=frozenset({"/studio/admin/remote/vnc.html", "/studio/admin/remote/app/ui.js"}),
    )
    return lease, authority, runtime, request, policy


def authorize(values, *, now=NOW, authority=None, runtime=None, request=None, lease=None):
    old_lease, old_authority, old_runtime, old_request, policy = values
    authorize_remote_request(
        lease or old_lease,
        authority or old_authority,
        runtime or old_runtime,
        request or old_request,
        policy,
        now=now,
    )


def revocation(grant, **updates):
    return GatewayRevocation.model_validate(
        {
            "schema_version": "kakao-remote-gateway-revocation/1.0",
            "lease_id": grant.lease_id,
            "fence_epoch": grant.fence_epoch,
            "gateway_epoch": grant.gateway_epoch,
            "grant_revision": grant.grant_revision,
            "reason": "LOGOUT",
            **updates,
        }
    )


def test_schema_first_exact_mirror_and_all_projection_values(values):
    canonical = Path("schemas/kakao-archive/private-remote-runtime-v1.schema.json").read_bytes()
    mirror = Path(
        "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas/private-remote-runtime-v1.schema.json"
    ).read_bytes()
    assert canonical == mirror and hashlib.sha256(canonical).hexdigest() == SCHEMA_SHA256
    schema = json.loads(canonical)
    Draft202012Validator.check_schema(schema)
    items = dict(zip(("lease", "authority", "runtime", "request"), values[:4], strict=True))
    items["grant"] = gateway_grant(values[0])
    items["revocation"] = revocation(items["grant"])
    for kind, value in items.items():
        payload = value.model_dump(mode="json")
        validate_remote_contract(kind, payload)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


@pytest.mark.parametrize(
    "extra", ["operator_id", "identity_session_id", "bearer", "profile_path", "upstream"]
)
def test_gateway_grant_cannot_carry_identity_credentials_or_locations(values, extra):
    payload = gateway_grant(values[0]).model_dump(mode="json")
    assert "operator_id" not in payload and "identity_session_id" not in payload
    payload[extra] = "not-a-credential"
    with pytest.raises(ValidationError):
        GatewayLeaseGrant.model_validate(payload)
    with pytest.raises(ValueError, match="KAKAO_REMOTE_SCHEMA_INVALID"):
        validate_remote_contract("grant", payload)


@pytest.mark.parametrize(
    "field,update",
    [
        ("fence_epoch", True),
        ("grant_revision", "1"),
        ("gateway_epoch", 0),
        ("issued_at", NOW.replace(tzinfo=None)),
        ("expires_at", NOW + timedelta(seconds=31)),
        ("absolute_expires_at", NOW + timedelta(minutes=21)),
        ("state", "EXPIRED"),
        ("identity_session_id", "websession_private-cookie"),
    ],
)
def test_private_lease_rejects_coercion_unbounded_time_and_cookie(values, field, update):
    with pytest.raises(ValidationError):
        change(values[0], **{field: update})


def test_exact_transport_admission_and_static_assets(values):
    authorize(values)
    static = change(
        values[3],
        path="/studio/admin/remote/vnc.html",
        origin=None,
        upgrade=None,
        connection="keep-alive",
        websocket_version=None,
        websocket_key=None,
    )
    authorize(values, request=static)
    assert values[0].grant_revision == 1, "authorization GET must not renew or create"


def test_static_asset_request_cannot_accept_a_cross_origin(values):
    request = change(
        values[3],
        path="/studio/admin/remote/vnc.html",
        origin="https://other.invalid",
        upgrade=None,
        connection="keep-alive",
        websocket_version=None,
        websocket_key=None,
    )
    with pytest.raises(RemoteAuthorizationError, match="TRANSPORT_DENIED"):
        authorize(values, request=request)


@pytest.mark.parametrize("field", ["connection", "upgrade", "websocket_key"])
def test_transport_rejects_control_characters_before_header_normalization(values, field):
    request = change(values[3], **{field: getattr(values[3], field) + "\r\n"})
    with pytest.raises(RemoteAuthorizationError, match="TRANSPORT_DENIED"):
        authorize(values, request=request)


@pytest.mark.parametrize(
    "origin",
    [
        "http://studio.invalid",
        "https://studio.invalid/",
        "https://user@studio.invalid",
        "https://studio.invalid?token=fake",
        "https://studio.invalid\n",
    ],
)
def test_transport_policy_requires_an_exact_https_origin(values, origin):
    with pytest.raises(ValidationError, match="ORIGIN_CONFIG_INVALID"):
        change(values[4], expected_origin=origin)


@pytest.mark.parametrize(
    "updates",
    [
        {"method": "POST"},
        {"method": "CONNECT"},
        {"protocol": "HTTP/2.0"},
        {"origin": None},
        {"origin": "https://other.invalid"},
        {"path": "/studio/admin/remote/websockify?token=fake"},
        {"path": "/studio/admin/remote/websockify#fragment"},
        {"path": "/studio/admin/remote/vnc.html"},
        {"path": "/studio/admin/remote/%77ebsockify"},
        {"upgrade": None},
        {"connection": "keep-alive"},
        {"websocket_version": "12"},
        {"websocket_key": "incorrect-key"},
    ],
)
def test_transport_cannot_select_other_paths_or_bypass_websocket_shape(values, updates):
    with pytest.raises(RemoteAuthorizationError) as error:
        authorize(values, request=change(values[3], **updates))
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "updates,status",
    [
        ({"operator_active": False}, 401),
        ({"session_active": False}, 401),
        ({"is_admin": False}, 403),
        ({"remote_permission": False}, 403),
        ({"source_active": False}, 403),
        ({"source_access": False}, 403),
        ({"operator_id": identity("operator", 2)}, 403),
        ({"binding_owner_operator_id": identity("operator", 2)}, 403),
        ({"identity_session_id": identity("apisession", 2)}, 403),
        ({"source_binding_id": identity("kakaobinding", 2)}, 403),
        ({"checked_at": NOW - timedelta(seconds=6)}, 503),
        ({"checked_at": NOW + timedelta(seconds=1)}, 503),
    ],
)
def test_current_operator_session_scope_role_and_freshness(values, updates, status):
    authority = change(values[1], **updates)
    with pytest.raises(RemoteAuthorizationError) as error:
        authorize(values, authority=authority)
    assert error.value.status_code == status
    with pytest.raises(RemoteAuthorizationError):
        renew_remote_lease(values[0], authority, values[2], now=NOW)


@pytest.mark.parametrize(
    "updates,status",
    [
        ({"available": False}, 503),
        ({"process_state": "UNKNOWN"}, 503),
        ({"process_state": "STOPPED"}, 403),
        ({"mode": "AUTO"}, 403),
        ({"mode": "PAUSING"}, 403),
        ({"profile_locked": False}, 403),
        ({"profile_id": identity("kakaoprofile", 2)}, 403),
        ({"fence_epoch": 2}, 403),
        ({"gateway_epoch": 3}, 403),
        ({"source_binding_id": identity("kakaobinding", 2)}, 403),
    ],
)
def test_runtime_must_be_current_exclusive_manual_execution(values, updates, status):
    with pytest.raises(RemoteAuthorizationError) as error:
        authorize(values, runtime=change(values[2], **updates))
    assert error.value.status_code == status


def test_expiration_is_exact_renewal_preserves_original_absolute_limit(values):
    lease, authority, runtime, _, _ = values
    now = NOW + timedelta(seconds=29)
    renewed = renew_remote_lease(lease, change(authority, checked_at=now), runtime, now=now)
    assert renewed.grant_revision == 2 and renewed.expires_at == now + timedelta(seconds=30)
    assert renewed.absolute_expires_at == lease.absolute_expires_at
    assert lease.grant_revision == 1, "previous immutable value changed"
    late = change(
        lease,
        authorized_at=NOW + timedelta(minutes=19, seconds=40),
        expires_at=lease.absolute_expires_at,
    )
    near_end = NOW + timedelta(minutes=19, seconds=59)
    final = renew_remote_lease(late, change(authority, checked_at=near_end), runtime, now=near_end)
    assert final.expires_at == lease.absolute_expires_at
    for expired in (lease, final):
        clock = expired.expires_at
        with pytest.raises(RemoteAuthorizationError):
            renew_remote_lease(expired, change(authority, checked_at=clock), runtime, now=clock)
        ended = end_remote_lease(expired, now=clock)
        assert ended.state == "EXPIRED" and ended.ended_at == clock
        assert end_remote_lease(ended, now=clock + timedelta(seconds=2)) is ended
        with pytest.raises(ValueError, match="LEASE_ENDED"):
            gateway_grant(ended)


def test_gateway_real_connected_streams_close_at_monotonic_expiry_despite_wall_rollback(values):
    sockets = [socket.socketpair() for _ in range(2)]
    closed = []
    try:

        def stop(grant):
            closed.append(grant.gateway_epoch)
            for upstream, _viewer in sockets:
                upstream.close()
            return True

        grant = gateway_grant(values[0])
        lifetime = RemoteGatewayLifetime(grant, now=NOW, monotonic_now=100, stop_gateway=stop)
        for upstream, viewer in sockets:
            upstream.sendall(b"synthetic-stream")
            assert viewer.recv(32) == b"synthetic-stream"
        assert lifetime.poll(now=NOW + timedelta(seconds=29), monotonic_now=129) == "ACTIVE"
        assert lifetime.poll(now=NOW - timedelta(hours=1), monotonic_now=130) == "STOPPED"
        for _, viewer in sockets:
            viewer.settimeout(0.5)
            assert viewer.recv(1) == b""
        assert closed == [4]
        assert lifetime.poll(now=NOW, monotonic_now=131) == "STOPPED"
        assert closed == [4]
    finally:
        for pair in sockets:
            for stream in pair:
                stream.close()


def test_gateway_renewal_replay_does_not_extend_and_logout_wins_heartbeat_race(values):
    grant = gateway_grant(values[0])
    stopped = []
    lifetime = RemoteGatewayLifetime(
        grant,
        now=NOW,
        monotonic_now=0,
        stop_gateway=lambda value: stopped.append(value.lease_id) or True,
    )
    assert not lifetime.accept_renewal(grant, now=NOW + timedelta(seconds=10), monotonic_now=10)
    newer = change(
        grant,
        grant_revision=2,
        authorized_at=NOW + timedelta(seconds=15),
        expires_at=NOW + timedelta(seconds=45),
    )
    assert lifetime.accept_renewal(newer, now=NOW + timedelta(seconds=15), monotonic_now=15)
    # Revocation issued against revision 1 still ends this same epoch after renewal 2.
    assert lifetime.revoke(revocation(grant)) == "STOPPED"
    with pytest.raises(ValueError, match="LEASE_ENDED"):
        lifetime.accept_renewal(newer, now=NOW + timedelta(seconds=16), monotonic_now=16)
    assert len(stopped) == 1


def test_higher_revision_cannot_prolong_same_expiry_after_wall_clock_rollback(values):
    grant = gateway_grant(values[0])
    lifetime = RemoteGatewayLifetime(grant, now=NOW, monotonic_now=0, stop_gateway=lambda _: True)
    assert lifetime.poll(now=NOW + timedelta(seconds=10), monotonic_now=10) == "ACTIVE"
    higher_revision = change(grant, grant_revision=2)
    assert lifetime.accept_renewal(higher_revision, now=NOW, monotonic_now=20)
    assert lifetime.poll(now=NOW + timedelta(seconds=10), monotonic_now=30) == "STOPPED"


@pytest.mark.parametrize("clock", [float("nan"), float("inf"), -1, True])
def test_invalid_monotonic_clock_stops_gateway_before_raising(values, clock):
    stopped = []
    lifetime = RemoteGatewayLifetime(
        gateway_grant(values[0]),
        now=NOW,
        monotonic_now=10,
        stop_gateway=lambda _: stopped.append(1) or True,
    )
    with pytest.raises(ValueError, match="CLOCK_INVALID"):
        lifetime.poll(now=NOW, monotonic_now=clock)
    assert lifetime.state == "STOPPED" and stopped == [1]


def test_naive_clock_or_regressed_monotonic_clock_stops_gateway(values):
    for now, clock, code in (
        (NOW.replace(tzinfo=None), 11, "CLOCK_INVALID"),
        (NOW, 9, "MONOTONIC_REGRESSED"),
    ):
        lifetime = RemoteGatewayLifetime(
            gateway_grant(values[0]), now=NOW, monotonic_now=10, stop_gateway=lambda _: True
        )
        with pytest.raises(ValueError, match=code):
            lifetime.poll(now=now, monotonic_now=clock)
        assert lifetime.state == "STOPPED"


def test_gateway_failed_stop_is_not_success_and_closes_admission(values):
    grant = gateway_grant(values[0])
    attempts = []

    def stop(_grant):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("private error is not exposed")
        return len(attempts) >= 3

    lifetime = RemoteGatewayLifetime(grant, now=NOW, monotonic_now=0, stop_gateway=stop)
    assert lifetime.revoke(revocation(grant)) == GatewayLifetimeState.STOPPING
    assert lifetime.last_error_code == "KAKAO_GATEWAY_STOP_UNCONFIRMED"
    assert lifetime.poll(now=NOW + timedelta(seconds=1), monotonic_now=1) == "STOPPING"
    assert lifetime.poll(now=NOW + timedelta(seconds=2), monotonic_now=2) == "STOPPED"
    assert lifetime.last_error_code is None


@pytest.mark.parametrize(
    "updates",
    [
        {"lease_id": identity("kakaoremotelease", 2)},
        {"fence_epoch": 2},
        {"gateway_epoch": 5},
        {"profile_id": identity("kakaoprofile", 2)},
        {"absolute_expires_at": NOW + timedelta(minutes=19)},
    ],
)
def test_gateway_new_identity_or_epoch_requires_new_execution(values, updates):
    grant = gateway_grant(values[0])
    lifetime = RemoteGatewayLifetime(grant, now=NOW, monotonic_now=0, stop_gateway=lambda _: True)
    with pytest.raises(ValueError, match="GRANT_STALE"):
        lifetime.accept_renewal(change(grant, **updates), now=NOW, monotonic_now=0)


def test_concurrent_renewal_and_revoke_never_resurrect_the_gateway(values):
    grant = gateway_grant(values[0])
    stopped = []
    barrier = Barrier(2)
    lifetime = RemoteGatewayLifetime(
        grant, now=NOW, monotonic_now=0, stop_gateway=lambda _: stopped.append(1) or True
    )
    newer = change(
        grant,
        grant_revision=2,
        authorized_at=NOW + timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=35),
    )

    def renew():
        barrier.wait()
        try:
            return lifetime.accept_renewal(newer, now=NOW + timedelta(seconds=5), monotonic_now=5)
        except ValueError as error:
            assert str(error) == "KAKAO_GATEWAY_LEASE_ENDED"
            return False

    def end():
        barrier.wait()
        return lifetime.revoke(revocation(grant))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(renew), pool.submit(end)]
        for future in futures:
            future.result(timeout=2)
    assert lifetime.state == "STOPPED" and len(stopped) == 1


def profile_values(mode="PAUSING"):
    prior = ProfileFence(
        schema_version="kakao-profile-fence/1.0",
        profile_id=identity("kakaoprofile"),
        browser_run_id=identity("kakaobrowserrun"),
        fence_epoch=4,
        mode=mode,
    )
    stopped = ProfileStopReceipt(
        schema_version="kakao-profile-stop-receipt/1.0",
        profile_id=prior.profile_id,
        browser_run_id=prior.browser_run_id,
        fence_epoch=4,
        process_stopped=True,
        profile_lock_released=True,
        gateway_stopped=True,
        checkpoint_committed=True,
        observed_at=NOW,
    )
    return prior, stopped


@pytest.mark.parametrize(
    "updates",
    [
        {"process_stopped": False},
        {"profile_lock_released": False},
        {"checkpoint_committed": False},
        {"fence_epoch": 3},
        {"browser_run_id": identity("kakaobrowserrun", 2)},
        {"profile_id": identity("kakaoprofile", 2)},
        {"observed_at": NOW + timedelta(seconds=1)},
    ],
)
def test_profile_reopen_needs_exact_prior_stop_not_just_expired_db_lease(updates):
    prior, stopped = profile_values()
    with pytest.raises(ValueError, match="PRIOR_STOP_UNCONFIRMED"):
        validate_profile_handoff(
            prior, change(stopped, **updates), target_mode="MANUAL", next_fence=5, now=NOW
        )


def test_profile_manual_gateway_closes_before_auto_and_new_fence_is_required():
    prior, stopped = profile_values("MANUAL")
    validate_remote_contract("profile", prior.model_dump(mode="json"))
    validate_remote_contract("stop", stopped.model_dump(mode="json"))
    validate_profile_handoff(prior, stopped, target_mode="AUTO", next_fence=5, now=NOW)
    with pytest.raises(ValueError, match="PRIOR_STOP_UNCONFIRMED"):
        validate_profile_handoff(
            prior, change(stopped, gateway_stopped=False), target_mode="AUTO", next_fence=5, now=NOW
        )
    for fence in (4, 3, True):
        with pytest.raises(ValueError, match="FENCE_INVALID"):
            validate_profile_handoff(prior, stopped, target_mode="AUTO", next_fence=fence, now=NOW)
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        validate_profile_handoff(
            change(prior, mode="AUTO"), stopped, target_mode="MANUAL", next_fence=5, now=NOW
        )
