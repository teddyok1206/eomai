"""Actual private-socket framing and fail-closed workbook reply correlation."""

from __future__ import annotations

import json
import os
import socket
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_MODE
from eom_catalog_contracts.content_workbook_import import (
    CommitContentWorkbookRequest,
    ContentWorkbookError,
    PrepareContentWorkbookRequest,
    ReadContentWorkbookRequest,
)

from tests.api.test_content_workbook_routes import KEY, imported, preview, proposal
from tests.unit.content_planning_fixtures import identifier


def identity():
    return dict(
        actor_id=identifier("operator"),
        session_id=identifier("apisession"),
        request_id="req_workbook_upload_test",
        authentication_time=datetime(2026, 11, 12, tzinfo=UTC),
    )


def prepare():
    value = preview()
    return PrepareContentWorkbookRequest(
        **identity(),
        original_filename=value.original_filename,
        content_length=8,
        sha256=value.workbook_sha256,
        idempotency_key=KEY,
    )


@contextmanager
def socket_server(tmp_path, response):
    path = tmp_path / "catalog.sock"
    observed = {}
    failures = []
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    path.chmod(CATALOG_APPLICATION_SOCKET_MODE)
    server.listen(1)
    server.settimeout(5)

    def handle():
        try:
            with server.accept()[0] as connection:
                connection.settimeout(5)
                header = bytearray()
                while (chunk := connection.recv(1)) != b"\n":
                    if not chunk:
                        raise AssertionError("missing request header terminator")
                    header.extend(chunk)
                observed["request"] = json.loads(header)
                if observed["request"]["operation"] == "PREPARE_CONTENT_WORKBOOK":
                    body = bytearray()
                    while chunk := connection.recv(65536):
                        body.extend(chunk)
                    observed["body"] = bytes(body)
                connection.sendall(json.dumps(response).encode() + b"\n")
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=handle, daemon=True)
    thread.start()
    try:
        yield (
            CatalogApplicationClient(path, expected_uid=os.getuid(), expected_gid=os.getgid()),
            observed,
        )
    finally:
        thread.join(timeout=6)
        server.close()
        assert not thread.is_alive()
        if failures:
            raise failures[0]


def test_prepare_streams_one_json_header_then_exact_raw_bytes(tmp_path):
    with socket_server(tmp_path, preview().model_dump(mode="json")) as (client, captured):
        result = client.content_workbook(prepare(), content=b"testxlsx")
    assert result == preview()
    assert captured["body"] == b"testxlsx"
    assert captured["request"] == prepare().model_dump(mode="json")
    assert not {"content", "roles", "permissions"} & captured["request"].keys()


@pytest.mark.parametrize("content", [None, b"different", b"testxlsy"])
def test_prepare_rejects_missing_length_or_hash_mismatch_before_socket(content):
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client._validate_socket = Mock()
    with pytest.raises(CatalogApplicationClientError) as failure:
        client.content_workbook(prepare(), content=content)
    assert failure.value.code == "CONTENT_IMPORT_UNAVAILABLE"
    client._validate_socket.assert_not_called()


def test_read_is_small_json_and_same_pinned_proposal(tmp_path):
    request = ReadContentWorkbookRequest(**identity(), proposal=proposal(), limit=1)
    with socket_server(tmp_path, preview().model_dump(mode="json")) as (client, captured):
        assert client.content_workbook(request) == preview()
    assert captured["request"] == request.model_dump(mode="json")
    assert "body" not in captured


def test_commit_parses_result_and_preserves_idempotency(tmp_path):
    request = CommitContentWorkbookRequest(**identity(), proposal=proposal(), idempotency_key=KEY)
    with socket_server(tmp_path, imported().model_dump(mode="json")) as (client, captured):
        assert client.content_workbook(request) == imported()
    assert captured["request"]["idempotency_key"] == KEY


@pytest.mark.parametrize("change", ["proposal", "offset", "operation", "unknown", "unsafe_error"])
def test_invalid_or_uncorrelated_reply_is_rejected(change):
    value = preview().model_dump(mode="json")
    if change == "proposal":
        value["proposal"]["artifact_revision_id"] = identifier("rev", 2)
    elif change == "offset":
        value["offset"] = 1
        value["rows"] = []
    elif change == "operation":
        value = imported().model_dump(mode="json")
    elif change == "unknown":
        value["unexpected"] = "field"
    else:
        value = dict(schema_version="content-workbook-error/1.0", error_code="bad /private/path")
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client._raw_request = Mock(return_value=value)
    with pytest.raises(CatalogApplicationClientError) as failure:
        client.content_workbook(ReadContentWorkbookRequest(**identity(), proposal=proposal()))
    assert failure.value.code == "CONTENT_IMPORT_UNAVAILABLE"


def test_catalog_domain_error_code_is_preserved():
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client._raw_request = Mock(
        return_value=ContentWorkbookError(error_code="CONTENT_WORKBOOK_REPLAY_CONFLICT").model_dump(
            mode="json"
        )
    )
    with pytest.raises(CatalogApplicationClientError) as failure:
        client.content_workbook(ReadContentWorkbookRequest(**identity(), proposal=proposal()))
    assert failure.value.code == "CONTENT_WORKBOOK_REPLAY_CONFLICT"


def test_metadata_operation_cannot_carry_file_bytes():
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client._raw_request = Mock()
    with pytest.raises(CatalogApplicationClientError):
        client.content_workbook(
            ReadContentWorkbookRequest(**identity(), proposal=proposal()), content=b"testxlsx"
        )
    client._raw_request.assert_not_called()
