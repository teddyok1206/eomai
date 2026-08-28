from __future__ import annotations

import json
import os
import socket
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_api_contracts.control_plane import CodexAuthEnrollmentView, CodexDeviceChallengeView
from eom_orchestrator import auth_enrollment_processor as processor_module
from eom_orchestrator import codex_auth_broker_server as broker_module
from eom_orchestrator import worker_device_login_exec as login_module
from eom_orchestrator.auth_enrollment import build_codex_auth_enrollment_request
from eom_orchestrator.auth_enrollment_processor import CodexAuthEnrollmentProcessor
from eom_orchestrator.codex_auth_broker_client import (
    CodexAuthBrokerClient,
    CodexAuthBrokerError,
)
from eom_orchestrator.codex_auth_broker_server import CodexAuthBrokerServer
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow import CodexAuthEnrollmentRequest, CodexAuthEnrollmentStatus
from pydantic import ValidationError

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
ENROLLMENT_ID = "authflow_" + "1" * 32
BINDING_ID = "authbinding_" + "2" * 32


def test_enrollment_request_is_bounded_hashed_and_credential_free() -> None:
    document = build_codex_auth_enrollment_request(
        binding_id=BINDING_ID,
        expected_binding_resource_version=7,
        slot_key="slot05",
        requested_account_label="teacher-account-01",
        requested_by_operator_id="operator_" + "3" * 32,
        requested_by_api_session_id="apisession_" + "4" * 32,
        requested_at=NOW,
    )
    model = CodexAuthEnrollmentRequest.model_validate(document)
    assert model.expires_at - model.requested_at == timedelta(minutes=15)
    assert model.request_sha256.startswith("sha256:")
    serialized = json.dumps(document, sort_keys=True)
    for forbidden in ("password", "access_token", "refresh_token", "auth.json", "credential"):
        assert forbidden not in serialized


def test_enrollment_status_fails_closed_on_incoherent_challenge_and_terminal_state() -> None:
    waiting = {
        "schema_version": "codex-auth-enrollment-status/1.0",
        "enrollment_id": ENROLLMENT_ID,
        "binding_id": BINDING_ID,
        "slot_key": "slot05",
        "requested_account_label": "teacher-account-01",
        "state": "WAITING_FOR_USER",
        "challenge_available": True,
        "challenge_revealed_at": None,
        "assignment_revision_id": None,
        "error_code": None,
        "requested_at": NOW,
        "started_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "completed_at": None,
        "resource_version": 4,
    }
    CodexAuthEnrollmentStatus.model_validate(waiting)
    waiting["state"] = "DRAINING"
    with pytest.raises(ValidationError, match="challenge is available only"):
        CodexAuthEnrollmentStatus.model_validate(waiting)


def test_api_auth_views_reject_incoherent_lifecycle_and_unreviewed_origin() -> None:
    waiting = {
        "enrollment_id": ENROLLMENT_ID,
        "binding_id": BINDING_ID,
        "slot_key": "slot05",
        "requested_account_label": "teacher-account-01",
        "state": "WAITING_FOR_USER",
        "challenge_available": True,
        "challenge_revealed_at": None,
        "assignment_revision_id": None,
        "error_code": None,
        "requested_at": NOW,
        "started_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "completed_at": None,
        "resource_version": 4,
    }
    CodexAuthEnrollmentView.model_validate(waiting)
    waiting["completed_at"] = NOW + timedelta(minutes=1)
    with pytest.raises(ValidationError, match="terminal enrollment state"):
        CodexAuthEnrollmentView.model_validate(waiting)

    challenge = {
        "enrollment_id": ENROLLMENT_ID,
        "slot_key": "slot05",
        "verification_uri": "https://attacker.example/device",
        "user_code": "ABC1-DEF2",
        "expires_at": NOW + timedelta(minutes=10),
    }
    with pytest.raises(ValidationError, match="reviewed OpenAI origin"):
        CodexDeviceChallengeView.model_validate(challenge)
    waiting.update(
        state="SUCCEEDED",
        challenge_available=False,
        completed_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValidationError, match="assignment revision"):
        CodexAuthEnrollmentStatus.model_validate(waiting)


def _write_json(path: Path, value: dict[str, object], *, mode: int = 0o640) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(mode)


def _broker(tmp_path: Path) -> tuple[CodexAuthBrokerServer, Path]:
    runtime = tmp_path / "broker"
    runtime.mkdir(mode=0o750)
    handoff = tmp_path / "eom-codex-login-05"
    handoff.mkdir(mode=0o750)
    server = CodexAuthBrokerServer(
        socket_path=runtime / "broker.sock",
        allowed_uids=frozenset({os.geteuid()}),
        reveal_uids=frozenset({os.geteuid()}),
        expected_gid=os.getegid(),
        handoff_root=tmp_path,
        slot_identities={"05": (os.geteuid(), os.getegid())},
        now=lambda: NOW,
    )
    return server, handoff


def test_broker_rejects_explicit_empty_reveal_identity_set(tmp_path: Path) -> None:
    runtime = tmp_path / "broker"
    runtime.mkdir(mode=0o750)
    with pytest.raises(ValueError, match="reveal identities"):
        CodexAuthBrokerServer(
            socket_path=runtime / "broker.sock",
            allowed_uids=frozenset({os.geteuid()}),
            reveal_uids=frozenset(),
            expected_gid=os.getegid(),
            handoff_root=tmp_path,
            slot_identities={"05": (os.geteuid(), os.getegid())},
        )


def test_broker_client_requires_exact_socket_owner_group_and_mode(tmp_path: Path) -> None:
    runtime = tmp_path / "broker"
    runtime.mkdir(mode=0o750)
    socket_path = runtime / "broker.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(socket_path))
        socket_path.chmod(0o666)
        client = CodexAuthBrokerClient(
            socket_path,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
        with pytest.raises(CodexAuthBrokerError) as wrong_socket_mode:
            client._validate_socket()
        assert wrong_socket_mode.value.code == "CODEX_AUTH_BROKER_INVALID"

        socket_path.chmod(0o660)
        client._validate_socket()
        runtime.chmod(0o755)
        with pytest.raises(CodexAuthBrokerError) as wrong_runtime_mode:
            client._validate_socket()
        assert wrong_runtime_mode.value.code == "CODEX_AUTH_BROKER_INVALID"
    finally:
        listener.close()


def test_device_login_log_cleanup_is_explicit_and_symlink_safe(tmp_path: Path) -> None:
    log_directory = tmp_path / "login.logs"
    log_directory.mkdir(mode=0o700)
    (log_directory / "codex.log").write_text("sensitive", encoding="utf-8")
    login_module._remove_log_directory(log_directory)
    assert not log_directory.exists()

    target = tmp_path / "outside"
    target.mkdir()
    log_directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        login_module._remove_log_directory(log_directory)
    assert target.is_dir()


def _status(*, state: str = "WAITING_FOR_USER") -> dict[str, object]:
    return {
        "schema_version": "codex-device-login-status/1.0",
        "enrollment_id": ENROLLMENT_ID,
        "slot_key": "slot05",
        "state": state,
        "reason_code": None,
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _challenge() -> dict[str, object]:
    return {
        "schema_version": "codex-device-challenge/1.0",
        "enrollment_id": ENROLLMENT_ID,
        "slot_key": "slot05",
        "verification_uri": "https://auth.openai.com/codex/device",
        "user_code": "ABC1-DEF2",
        "issued_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }


def test_broker_reveals_schema_valid_challenge_once_without_mutating_handoff(
    tmp_path: Path,
) -> None:
    server, handoff = _broker(tmp_path)
    try:
        _write_json(handoff / f"{ENROLLMENT_ID}.status.json", _status())
        challenge_path = handoff / f"{ENROLLMENT_ID}.challenge.json"
        _write_json(challenge_path, _challenge())
        request = broker_module.CodexAuthBrokerRequest(
            action="REVEAL", enrollment_id=ENROLLMENT_ID, slot_key="slot05"
        )
        first = server.execute(request)
        assert first.outcome == "OK"
        assert first.challenge is not None and first.challenge.user_code == "ABC1-DEF2"
        assert stat.S_IMODE(challenge_path.stat().st_mode) == 0o640
        second = server.execute(request)
        assert second.outcome == "FAILED"
        assert second.error_code == "CODEX_AUTH_CHALLENGE_ALREADY_REVEALED"
    finally:
        server.server_close()


def test_broker_rejects_expired_challenge(tmp_path: Path) -> None:
    server, handoff = _broker(tmp_path)
    try:
        _write_json(handoff / f"{ENROLLMENT_ID}.status.json", _status())
        challenge = _challenge()
        challenge["issued_at"] = (NOW - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        challenge["expires_at"] = (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        _write_json(handoff / f"{ENROLLMENT_ID}.challenge.json", challenge)
        response = server.execute(
            broker_module.CodexAuthBrokerRequest(
                action="REVEAL", enrollment_id=ENROLLMENT_ID, slot_key="slot05"
            )
        )
        assert response.outcome == "FAILED"
        assert response.error_code == "CODEX_AUTH_CHALLENGE_EXPIRED"
    finally:
        server.server_close()


def test_broker_allows_status_but_denies_reveal_to_runner_identity(tmp_path: Path) -> None:
    server, handoff = _broker(tmp_path)
    runner_uid = os.geteuid() + 1
    server.allowed_uids = frozenset({os.geteuid(), runner_uid})
    try:
        _write_json(handoff / f"{ENROLLMENT_ID}.status.json", _status())
        _write_json(handoff / f"{ENROLLMENT_ID}.challenge.json", _challenge())
        status = server.execute(
            broker_module.CodexAuthBrokerRequest(
                action="STATUS", enrollment_id=ENROLLMENT_ID, slot_key="slot05"
            ),
            caller_uid=runner_uid,
        )
        reveal = server.execute(
            broker_module.CodexAuthBrokerRequest(
                action="REVEAL", enrollment_id=ENROLLMENT_ID, slot_key="slot05"
            ),
            caller_uid=runner_uid,
        )
        assert status.outcome == "OK"
        assert reveal.outcome == "FAILED"
        assert reveal.error_code == "CODEX_AUTH_BROKER_REVEAL_DENIED"
    finally:
        server.server_close()


@pytest.mark.parametrize("unsafe", ["symlink", "wrong-mode"])
def test_broker_rejects_unsafe_handoff(tmp_path: Path, unsafe: str) -> None:
    server, handoff = _broker(tmp_path)
    try:
        status_path = handoff / f"{ENROLLMENT_ID}.status.json"
        if unsafe == "symlink":
            target = tmp_path / "outside.json"
            _write_json(target, _status())
            status_path.symlink_to(target)
        else:
            _write_json(status_path, _status(), mode=0o644)
        response = server.execute(
            broker_module.CodexAuthBrokerRequest(
                action="STATUS", enrollment_id=ENROLLMENT_ID, slot_key="slot05"
            )
        )
        assert response.outcome == "FAILED"
        assert response.error_code == "CODEX_AUTH_HANDOFF_INVALID"
    finally:
        server.server_close()


def _fake_codex(path: Path, *, valid: bool) -> None:
    output = (
        "printf '%s\\n' 'Open https://auth.openai.com/codex/device and enter ABC1-DEF2'"
        if valid
        else "printf '%s\\n' 'malformed output'"
    )
    path.write_text(f"#!/bin/sh\n{output}\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("valid", "expected"),
    [(True, 0), (False, login_module.DEVICE_LOGIN_INVALID_EXIT)],
)
def test_device_login_parser_materializes_only_typed_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
    expected: int,
) -> None:
    binary = tmp_path / "codex"
    _fake_codex(binary, valid=valid)
    monkeypatch.setattr(login_module, "CODEX_BINARY", binary)
    status_path = tmp_path / "status.json"
    challenge_path = tmp_path / "challenge.json"
    result = login_module._collect_device_login(
        environment={"PATH": "/usr/bin:/bin"},
        log_directory=tmp_path,
        enrollment_id=ENROLLMENT_ID,
        slot_id="05",
        status_path=status_path,
        challenge_path=challenge_path,
    )
    assert result == expected
    if valid:
        challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
        assert challenge["user_code"] == "ABC1-DEF2"
        assert challenge["verification_uri"].startswith("https://auth.openai.com/")
        assert stat.S_IMODE(challenge_path.stat().st_mode) == 0o640
        assert "Open " not in challenge_path.read_text(encoding="utf-8")
    else:
        assert not challenge_path.exists()


def test_reclaimed_login_start_marker_never_relaunches_fixed_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = object.__new__(CodexAuthEnrollmentProcessor)
    observed: list[tuple[str, str]] = []
    processor._observe_login = (  # type: ignore[method-assign]
        lambda target, _at, *, expected_state: observed.append(
            (target.enrollment_id, expected_state)
        )
    )
    launches: list[str] = []
    monkeypatch.setattr(
        processor_module,
        "launch_device_login_unit",
        lambda _slot, enrollment_id: launches.append(enrollment_id),
    )
    target = processor_module._EnrollmentTarget(
        enrollment_id=ENROLLMENT_ID,
        state="READY_FOR_LOGIN",
        binding_id=BINDING_ID,
        slot=WorkerSlot(
            slot_id="05",
            linux_user="eom-cdx-05",
            role="support",
            enabled=True,
            gpu=False,
        ),
        slot_key="slot05",
        account_label="teacher-account-01",
        expires_at=NOW + timedelta(minutes=15),
        login_unit_started_at=NOW - timedelta(seconds=1),
    )

    processor._start_or_observe_login(target, NOW)

    assert launches == []
    assert observed == [(ENROLLMENT_ID, "READY_FOR_LOGIN")]
