"""Synthetic real HMAC/fixed socket FDs; no installed provider/peer or DB admission."""

from __future__ import annotations

import copy
import socket
import time
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from eom_identity_service import AuthenticatedOperatorSession
from eom_identity_service.owner_session_transport import (
    FixedIdentityProviderPin,
    IdentityOwnerSessionProviderAdmission,
    OwnerSessionTransportError,
    OwnerSessionTransportObservation,
    export_owner_session_capture,
    import_owner_session_capture,
    observe_owner_session_transport,
)
from eom_operator_identity.owner_session_capture import owner_session_capture_bytes

from tests.unit.test_authenticated_session_fence import SyntheticSession, verified_capture
from tests.unit.test_owner_session_capture_contracts import request

PIN = FixedIdentityProviderPin("a" * 40, "sha256:" + "b" * 64, "sha256:" + "c" * 64)


class SyntheticAdmission:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.fail = False

    def assert_current(
        self, *, source_commit: str, wheel_sha256: str, configuration_sha256: str
    ) -> None:
        self.calls.append(
            {
                "source_commit": source_commit,
                "wheel_sha256": wheel_sha256,
                "configuration_sha256": configuration_sha256,
            }
        )
        if self.fail:
            raise RuntimeError("synthetic bearer/key/digest must not escape")


class SyntheticSocket(socket.socket):
    """Real nonconnected AF_INET FD with source-only synthetic endpoints; no network."""

    def __init__(self) -> None:
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.peer = ("127.0.0.1", 8765)
        self.local = ("127.0.0.1", 40001)

    def getpeername(self) -> tuple[str, int]:
        return self.peer

    def getsockname(self) -> tuple[str, int]:
        return self.local


def synthetic_peer(_socket: socket.socket) -> None:
    """Fake port assertion proves source order, never actual API UID/provider admission."""


def observation(
    monkeypatch: pytest.MonkeyPatch, peer: socket.socket, admission: SyntheticAdmission
) -> OwnerSessionTransportObservation:
    source, capture = verified_capture(monkeypatch, SyntheticSession())
    assert source.raw_token not in repr(capture)
    started = datetime.now(UTC) - timedelta(seconds=1)
    reply = export_owner_session_capture(request(), capture)
    return observe_owner_session_transport(
        request=request(),
        response_raw=owner_session_capture_bytes(reply),
        connection=peer,
        pin=PIN,
        admission=admission,
        verify_peer=synthetic_peer,
        started_at=started,
        deadline=time.monotonic() + 9,
    )


def test_genuine_export_admitted_one_use_import_same_observed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SyntheticSocket() as peer:
        admission = SyntheticAdmission()
        observed = observation(monkeypatch, peer, admission)
        capture = import_owner_session_capture(observed)
        assert isinstance(capture, AuthenticatedOperatorSession)
        assert capture.operator_id == "operator_" + "a" * 32
        assert repr(observed) == "<OwnerSessionTransportObservation>"
        assert observed._origin.response.verifier_digest not in repr(observed._origin)
        assert all(
            call
            == {
                "source_commit": PIN.source_commit,
                "wheel_sha256": PIN.wheel_sha256,
                "configuration_sha256": PIN.configuration_sha256,
            }
            for call in admission.calls
        )
        with pytest.raises(OwnerSessionTransportError):
            import_owner_session_capture(observed)


@pytest.mark.parametrize("kind", ["dto", "bare", "copy", "changed", "constructor"])
def test_export_requires_existing_genuine_capture_provenance(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _source, capture = verified_capture(monkeypatch, SyntheticSession())
    if kind == "dto":
        value: object = export_owner_session_capture(request(), capture)
    elif kind == "bare":
        value = object.__new__(AuthenticatedOperatorSession)
    elif kind == "copy":
        with pytest.raises(ValueError):
            copy.copy(capture)
        value = object.__new__(AuthenticatedOperatorSession)
        for name in ("_values", "_origin"):
            object.__setattr__(value, name, object.__getattribute__(capture, name))
    elif kind == "changed":
        value = capture
        object.__setattr__(capture, "_values", object())
    else:
        with pytest.raises(ValueError):
            AuthenticatedOperatorSession()
        return
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_EXPORT_INVALID$"):
        export_owner_session_capture(request(), cast(AuthenticatedOperatorSession, value))


@pytest.mark.parametrize("kind", ["dto", "bare", "copy", "closed", "peer", "admission", "bool"])
def test_import_rejects_dto_forgery_copy_epoch_and_current_admission(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    with SyntheticSocket() as peer:
        admission = SyntheticAdmission()
        observed = observation(monkeypatch, peer, admission)
        value: object = observed
        if kind == "dto":
            _source, capture = verified_capture(monkeypatch, SyntheticSession())
            value = export_owner_session_capture(request(), capture)
        elif kind == "bare":
            value = object.__new__(OwnerSessionTransportObservation)
        elif kind == "copy":
            with pytest.raises(AttributeError):
                copy.copy(observed)
            value = object.__new__(OwnerSessionTransportObservation)
            object.__setattr__(value, "_origin", observed._origin)
        elif kind == "closed":
            peer.close()
        elif kind == "peer":
            peer.peer = ("127.0.0.1", 8766)
        elif kind == "admission":
            admission.fail = True
        else:
            object.__setattr__(observed._origin.response, "refresh_generation", True)
        with pytest.raises(OwnerSessionTransportError) as caught:
            import_owner_session_capture(cast(OwnerSessionTransportObservation, value))
        assert "synthetic bearer" not in str(caught.value)
        assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "kind", ["missing", "wrong_pin", "old", "future", "deadline", "hash", "raw", "grant"]
)
def test_observation_requires_actual_configured_ports_and_current_request_clock(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _source, capture = verified_capture(monkeypatch, SyntheticSession())
    reply = export_owner_session_capture(request(), capture)
    admission: IdentityOwnerSessionProviderAdmission = SyntheticAdmission()
    pin, started, deadline = PIN, datetime.now(UTC) - timedelta(seconds=1), time.monotonic() + 9
    raw = owner_session_capture_bytes(reply)
    if kind == "missing":
        admission = cast(IdentityOwnerSessionProviderAdmission, None)
    elif kind == "wrong_pin":
        pin = copy.copy(PIN)
        object.__setattr__(pin, "source_commit", True)
    elif kind == "old":
        started -= timedelta(seconds=20)
    elif kind == "future":
        started += timedelta(seconds=20)
    elif kind == "deadline":
        deadline = time.monotonic() - 1
    elif kind == "hash":
        raw = owner_session_capture_bytes(
            reply.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
        )
    elif kind == "raw":
        raw = b" " + raw
    else:

        class ReturnsGrant:
            def assert_current(self, **_pins: str) -> object:
                return True

        admission = cast(IdentityOwnerSessionProviderAdmission, ReturnsGrant())
    with SyntheticSocket() as peer, pytest.raises(OwnerSessionTransportError):
        observe_owner_session_transport(
            request=request(),
            response_raw=raw,
            connection=peer,
            pin=pin,
            admission=admission,
            verify_peer=synthetic_peer,
            started_at=started,
            deadline=deadline,
        )


def test_transport_module_has_no_orchestrator_cli_catalog_backimport() -> None:
    import ast
    from pathlib import Path

    from eom_identity_service import owner_session_transport as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    names = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name.startswith(("eom_orchestrator", "eomctl", "eom_catalog_service", "eom_api"))
        for name in names
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", "a" * 39),
        ("source_commit", True),
        ("wheel_sha256", "b" * 64),
        ("configuration_sha256", "latest"),
    ],
)
def test_provider_pin_uses_only_exact_existing_release_config_values(
    field: str, value: object
) -> None:
    values: dict[str, object] = {
        "source_commit": PIN.source_commit,
        "wheel_sha256": PIN.wheel_sha256,
        "configuration_sha256": PIN.configuration_sha256,
    }
    values[field] = value
    with pytest.raises(OwnerSessionTransportError):
        FixedIdentityProviderPin(
            cast(str, values["source_commit"]),
            cast(str, values["wheel_sha256"]),
            cast(str, values["configuration_sha256"]),
        )


def test_observation_current_deadline_and_callback_mutation_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SyntheticSocket() as peer:
        observed = observation(monkeypatch, peer, SyntheticAdmission())
        observed._origin.deadline = time.monotonic() - 1
        with pytest.raises(OwnerSessionTransportError):
            import_owner_session_capture(observed)
    with SyntheticSocket() as peer:
        observed = observation(monkeypatch, peer, SyntheticAdmission())
        origin = observed._origin

        def mutate(_peer: socket.socket) -> None:
            object.__setattr__(origin.response, "refresh_generation", 2)

        origin.verify_peer = mutate
        with pytest.raises(OwnerSessionTransportError):
            import_owner_session_capture(observed)


def test_import_thread_change_never_reuses_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with SyntheticSocket() as peer:
        observed = observation(monkeypatch, peer, SyntheticAdmission())
        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(OwnerSessionTransportError):
            pool.submit(import_owner_session_capture, observed).result()
