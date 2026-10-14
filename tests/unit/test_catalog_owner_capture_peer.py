"""Real temporary Unix FD/bytes and source HMAC; synthetic unit/UID/PID, not installed admission."""

from __future__ import annotations

import os
import socket
import struct
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_identity_service import installed_owner_session_provider as module
from eom_identity_service.owner_session_transport import (
    OwnerSessionTransportError,
    export_owner_session_capture,
    import_owner_session_capture,
)
from eom_operator_identity.owner_session_capture_v11 import (
    supported_owner_session_capture_bytes,
)

from tests.unit.test_authenticated_session_fence import assert_current, verified_capture
from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_owner_session_capture_contracts import request as seed_request
from tests.unit.test_owner_session_capture_v11_contracts import request_v11
from tests.unit.test_owner_session_transport import SyntheticSocket


class SyntheticApiPeer(socket.socket):
    """An actual accepted Unix FD; SO_PEERCRED values are explicitly simulated."""

    def __init__(self, descriptor):
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM, fileno=descriptor)
        self.peer_credentials = (12345, 1000, 1000)

    def getsockopt(self, level, name, buflen=0):
        if (level, name) == (socket.SOL_SOCKET, socket.SO_PEERCRED):
            return struct.pack("3i", *self.peer_credentials)
        return super().getsockopt(level, name, buflen)


@contextmanager
def connected_peer():
    # Use a short actual pathname, independent of pytest's long case directory.
    with (
        tempfile.TemporaryDirectory(prefix="eom-owner-peer-") as directory,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server,
    ):
        server.bind(str(Path(directory) / "catalog.sock"))
        server.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(server.getsockname())
            accepted, _address = server.accept()
            with SyntheticApiPeer(accepted.detach()) as peer:
                yield peer, client


def exchange(monkeypatch, installed, peer, client, *, request=None, fault=""):
    source, capture = verified_capture(monkeypatch)
    checked = request or request_v11()
    reply = export_owner_session_capture(checked, capture)
    if fault == "response_hash":
        reply = reply.model_copy(update={"request_sha256": "sha256:" + "0" * 64})
    elif fault == "response_purpose":
        reply = reply.model_copy(update={"purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK"})
    raw = supported_owner_session_capture_bytes(reply)
    if fault == "noncanonical":
        raw = b" " + raw
    client.sendall(raw)
    received = peer.recv(8193)
    started = datetime.now(UTC) - timedelta(seconds=1)
    deadline = time.monotonic() + 9
    if fault == "old":
        started -= timedelta(seconds=20)
    elif fault == "future":
        started += timedelta(seconds=20)
    elif fault == "deadline":
        deadline = time.monotonic() - 1
    elif fault == "closed":
        peer.close()
    value = installed.capture_catalog_request(
        request=checked,
        response_raw=received,
        connection=peer,
        started_at=started,
        deadline=deadline,
    )
    return source, value


def test_real_local_bytes_same_source_session_and_one_use_import(observation, monkeypatch):
    installed = module.ProtectedInstalledIdentityProviderAdmission(observation[0])
    observed = []

    def consume(value):
        observed.append(value)
        return import_owner_session_capture(value)

    monkeypatch.setattr(module, "import_owner_session_capture", consume)
    with connected_peer() as (peer, client):
        source, capture = exchange(monkeypatch, installed, peer, client)
        assert capture.operator_id == source.operator.operator_id
        assert_current(source, capture)
        assert len(observed) == 1
        assert source.raw_token not in repr(capture)
        assert source.token.verifier_hash not in repr(capture)
        with pytest.raises(OwnerSessionTransportError):
            import_owner_session_capture(observed[0])


@pytest.mark.parametrize("field", (0, 1, 2))
def test_current_api_uid_alone_never_admits_other_process_or_credentials(
    observation, monkeypatch, field
):
    installed = module.ProtectedInstalledIdentityProviderAdmission(observation[0])
    with connected_peer() as (peer, client):
        changed = list(peer.peer_credentials)
        changed[field] += 1
        peer.peer_credentials = tuple(changed)
        with pytest.raises(OwnerSessionTransportError):
            exchange(monkeypatch, installed, peer, client)


@pytest.mark.parametrize("field", ("MainPID", "InvocationID", "User", "ActiveState", "DropInPaths"))
def test_replaced_loaded_provider_denies_the_socket_even_with_the_old_api_pid(
    observation, monkeypatch, field
):
    value, properties, *_ = observation
    properties[field] = "foreign"
    installed = module.ProtectedInstalledIdentityProviderAdmission(value)
    with connected_peer() as (peer, client), pytest.raises(OwnerSessionTransportError):
        exchange(monkeypatch, installed, peer, client)


@pytest.mark.parametrize(
    "fault",
    ("response_hash", "response_purpose", "noncanonical", "old", "future", "deadline", "closed"),
)
def test_closed_capture_values_and_original_deadlines_never_gain_a_unix_fallback(
    observation, monkeypatch, fault
):
    installed = module.ProtectedInstalledIdentityProviderAdmission(observation[0])
    with connected_peer() as (peer, client), pytest.raises(OwnerSessionTransportError) as caught:
        exchange(monkeypatch, installed, peer, client, fault=fault)
    assert "synthetic" not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize(
    "purpose_request", (seed_request(), request_v11("LOCAL_EMBEDDING_DEVICE_BENCHMARK"))
)
def test_seed_or_benchmark_capture_cannot_authorize_item_reference_work(
    observation, monkeypatch, purpose_request
):
    installed = module.ProtectedInstalledIdentityProviderAdmission(observation[0])
    with connected_peer() as (peer, client), pytest.raises(OwnerSessionTransportError):
        exchange(monkeypatch, installed, peer, client, request=purpose_request)


def test_a_tcp_observation_cannot_be_mistaken_for_the_receiving_catalog_peer(
    observation, monkeypatch
):
    installed = module.ProtectedInstalledIdentityProviderAdmission(observation[0])
    _source, capture = verified_capture(monkeypatch)
    request = request_v11()
    raw = supported_owner_session_capture_bytes(export_owner_session_capture(request, capture))
    with SyntheticSocket() as tcp, pytest.raises(OwnerSessionTransportError):
        installed.capture_catalog_request(
            request=request,
            response_raw=raw,
            connection=tcp,
            started_at=datetime.now(UTC) - timedelta(seconds=1),
            deadline=time.monotonic() + 9,
        )


@pytest.mark.parametrize("fault", ("peer", "provider", "descriptor", "thread", "boolean"))
def test_actual_import_rechecks_late_peer_provider_thread_and_non_grant_admission(
    observation, monkeypatch, fault
):
    installed = module.ProtectedInstalledIdentityProviderAdmission(observation[0])
    with connected_peer() as (peer, client):

        def late(value):
            if fault == "peer":
                peer.peer_credentials = (12346, 1000, 1000)
            elif fault == "provider":
                observation[1]["InvocationID"] = "f" * 32
            elif fault == "boolean":
                monkeypatch.setattr(installed, "assert_current", lambda **_kwargs: True)
            elif fault == "descriptor":
                with connected_peer() as (replacement, _replacement_client):
                    os.dup2(replacement.fileno(), peer.fileno())
                    return import_owner_session_capture(value)
            else:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(import_owner_session_capture, value).result()
            return import_owner_session_capture(value)

        monkeypatch.setattr(module, "import_owner_session_capture", late)
        with pytest.raises(OwnerSessionTransportError):
            exchange(monkeypatch, installed, peer, client)
