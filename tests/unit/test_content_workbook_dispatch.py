"""Catalog upload framing and API-peer gating using only synthetic local bytes."""

from __future__ import annotations

import json
import os
import socket
import stat
import threading
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_catalog_contracts.content_workbook_import import (
    CommitContentWorkbookRequest,
    ReadContentWorkbookRequest,
    parse_content_workbook_reply,
)
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_workbook_import_dispatch import dispatch_content_workbook
from eom_operator_identity import ActorSource, ActorType

from tests.api.test_content_workbook_client import identity, prepare
from tests.api.test_content_workbook_routes import KEY, imported, preview, proposal


def fake_service(tmp_path):
    staging = tmp_path / "uploads"
    staging.mkdir()

    def prepare_upload(path, request, actor):
        assert path.read_bytes() == b"testxlsx"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert actor.actor_type is ActorType.OPERATOR
        assert actor.source is ActorSource.APPLICATION_API
        assert not actor.permissions
        assert actor.operator_id == request.actor_id
        assert actor.authentication_time == request.authentication_time
        return preview()

    return SimpleNamespace(
        settings=SimpleNamespace(staging_root=staging),
        authorize_upload=Mock(),
        prepare=Mock(side_effect=prepare_upload),
        read=Mock(return_value=preview()),
        commit=Mock(return_value=imported()),
    )


def dispatched(service, command, body=b"testxlsx"):
    incoming, output = BytesIO(body), BytesIO()
    dispatch_content_workbook(service, command, incoming, output)
    assert output.getvalue().endswith(b"\n")
    assert len(output.getvalue().splitlines()) == 1
    parsed = json.loads(output.getvalue())
    parse_content_workbook_reply(parsed)
    return parsed, incoming.tell()


@pytest.mark.parametrize("case", ["success", "truncated", "exceeded", "hash", "denied"])
def test_framing_validates_before_artifact_commit_and_cleans_local_workspace(tmp_path, case):
    service = fake_service(tmp_path)
    command, body = prepare().model_dump(mode="json"), b"testxlsx"
    expected = None
    if case == "truncated":
        body, expected = body[:-1], "CONTENT_WORKBOOK_UPLOAD_TRUNCATED"
    elif case == "exceeded":
        body, expected = body + b"X", "CONTENT_WORKBOOK_UPLOAD_EXCEEDED"
    elif case == "hash":
        command["sha256"] = "sha256:" + "0" * 64
        expected = "CONTENT_WORKBOOK_UPLOAD_HASH_MISMATCH"
    elif case == "denied":
        expected = "CONTENT_PLANNING_PERMISSION_DENIED"
        service.authorize_upload.side_effect = ContentPlanningError(expected)
    result, read_bytes = dispatched(service, command, body)
    if expected is None:
        assert result == preview().model_dump(mode="json")
        service.prepare.assert_called_once()
    else:
        assert result["error_code"] == expected
        service.prepare.assert_not_called()
    if case == "denied":
        assert read_bytes == 0
    assert not list(service.settings.staging_root.iterdir())


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "RUN_SHELL"),
        ("roles", ["ADMIN"]),
        ("content_length", 8 * 1024 * 1024 + 1),
        ("actor_id", "operator_invalid"),
    ],
)
def test_invalid_schema_fails_before_reading_untrusted_bytes(tmp_path, field, value):
    service = fake_service(tmp_path)
    result, read_bytes = dispatched(service, {**prepare().model_dump(mode="json"), field: value})
    assert result["error_code"] == "CONTENT_WORKBOOK_REQUEST_INVALID"
    assert read_bytes == 0
    service.authorize_upload.assert_not_called()
    service.prepare.assert_not_called()
    assert not list(service.settings.staging_root.iterdir())


def test_disabled_service_returns_stable_unavailable_without_consuming_file():
    result, read_bytes = dispatched(None, prepare().model_dump(mode="json"))
    assert result["error_code"] == "CATALOG_APPLICATION_UNAVAILABLE"
    assert read_bytes == 0


def test_read_and_commit_do_not_consume_binary_input(tmp_path):
    service = fake_service(tmp_path)
    request = ReadContentWorkbookRequest(**identity(), proposal=proposal(), offset=0, limit=1)
    result, read_bytes = dispatched(service, request.model_dump(mode="json"))
    assert result == preview().model_dump(mode="json") and read_bytes == 0
    assert service.read.call_args.kwargs["limit"] == 1
    assert service.read.call_args.kwargs["actor"].operator_id == identity()["actor_id"]
    command = CommitContentWorkbookRequest(**identity(), proposal=proposal(), idempotency_key=KEY)
    result, read_bytes = dispatched(service, command.model_dump(mode="json"))
    assert result == imported().model_dump(mode="json") and read_bytes == 0
    assert service.commit.call_args.kwargs["idempotency_key"] == KEY
    service.authorize_upload.assert_not_called()


def test_timeout_cleans_partial_file_and_has_stable_error(tmp_path):
    service = fake_service(tmp_path)
    incoming = Mock()
    incoming.read.side_effect = [b"test", TimeoutError("private transport timeout")]
    output = BytesIO()
    dispatch_content_workbook(service, prepare().model_dump(mode="json"), incoming, output)
    assert json.loads(output.getvalue())["error_code"] == "CONTENT_WORKBOOK_UPLOAD_TIMEOUT"
    assert not list(service.settings.staging_root.iterdir())
    service.prepare.assert_not_called()


def test_internal_failure_does_not_expose_content_paths_or_exception_text(tmp_path, caplog):
    service = fake_service(tmp_path)
    service.prepare.side_effect = RuntimeError("PRIVATE_PAYLOAD /private/file.xlsx")
    result, _ = dispatched(service, prepare().model_dump(mode="json"))
    assert result["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"
    assert "PRIVATE_PAYLOAD" not in json.dumps(result) + caplog.text
    assert "/private/file.xlsx" not in caplog.text
    assert not list(service.settings.staging_root.iterdir())


@contextmanager
def actual_server(tmp_path, *, api_peer=True):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    service = fake_service(tmp_path)
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        content_workbook_import=service,
        socket_path=runtime / "manager.sock",
        allowed_uid=os.getuid() if api_peer else os.getuid() + 100000,
        chat_owner_uid=os.getuid() + 200000 if api_peer else os.getuid(),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server, service
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_actual_private_socket_routes_upload_read_and_commit(tmp_path):
    with actual_server(tmp_path) as (server, service):
        client = CatalogApplicationClient(
            server.socket_path, expected_uid=os.getuid(), expected_gid=os.getgid()
        )
        assert client.content_workbook(prepare(), content=b"testxlsx") == preview()
        assert (
            client.content_workbook(ReadContentWorkbookRequest(**identity(), proposal=proposal()))
            == preview()
        )
        assert (
            client.content_workbook(
                CommitContentWorkbookRequest(**identity(), proposal=proposal(), idempotency_key=KEY)
            )
            == imported()
        )
        service.prepare.assert_called_once()
        service.read.assert_called_once()
        service.commit.assert_called_once()
        assert not list(service.settings.staging_root.iterdir())


@pytest.mark.parametrize(
    "operation", ["PREPARE_CONTENT_WORKBOOK", "READ_CONTENT_WORKBOOK", "COMMIT_CONTENT_WORKBOOK"]
)
def test_non_api_peer_cannot_use_workbook_operations_even_if_chat_peer_is_allowed(
    tmp_path, operation
):
    with actual_server(tmp_path, api_peer=False) as (server, service):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(json.dumps({"operation": operation}).encode() + b"\n")
            assert connection.recv(1) == b""
        service.authorize_upload.assert_not_called()
        service.prepare.assert_not_called()
        service.read.assert_not_called()
        service.commit.assert_not_called()
