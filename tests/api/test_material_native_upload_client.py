"""Installed private protocol framing; hashes and bytes are checked before privileged I/O."""

from __future__ import annotations

import hashlib
from unittest.mock import Mock

import pytest
from eom_api.services import catalog_application_client as owner
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts.material_native_intake import (
    CreateNativeMaterialLearningCommand,
)
from eom_catalog_contracts.material_native_prepare import PrepareNativeMaterialExamCommand

from tests.api.test_content_workbook_client import socket_server
from tests.api.test_hwpx_endpoints import OPERATOR_ID
from tests.api.test_material_native_upload_routes import KEY, XLSX, acceptance, metadata
from tests.unit.test_material_native_intake import native_create


def command():
    value = metadata()
    value.pop("schema_version")
    return PrepareNativeMaterialExamCommand.model_validate(
        value
        | dict(
            actor_id=OPERATOR_ID,
            idempotency_key=KEY,
            workbook_bytes=len(XLSX),
            workbook_sha256="sha256:" + hashlib.sha256(XLSX).hexdigest(),
        )
    )


def test_native_workbook_uses_existing_socket_header_raw_binary_framing(tmp_path):
    with socket_server(tmp_path, acceptance().model_dump(mode="json")) as (client, captured):
        result = client.prepare_native_material_exam(command(), content=XLSX)
    assert result == acceptance()
    assert captured["body"] == XLSX
    assert captured["request"] == command().model_dump(mode="json")
    assert not {"content", "permissions", "roles", "path"} & captured["request"].keys()


@pytest.mark.parametrize("content", [b"", b"different", b"x" * len(XLSX)])
def test_wrong_hash_length_fails_before_socket_validation_or_connection(content):
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client._validate_socket = Mock()
    with pytest.raises(CatalogApplicationClientError) as failure:
        client.prepare_native_material_exam(command(), content=content)
    assert failure.value.code == "MATERIAL_LEARNING_UNAVAILABLE"
    client._validate_socket.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schema_version": "material-learning-error/1.0", "error_code": "unsafe /private/path"},
        acceptance().model_dump(mode="json") | {"unexpected": "value"},
        acceptance().model_dump(mode="json") | {"run_id": "invalid"},
    ],
)
def test_invalid_private_reply_fails_closed_without_leaking_details(monkeypatch, value):
    monkeypatch.setattr(owner, "send_native_exam_workbook_upload", Mock(return_value=value))
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    with pytest.raises(CatalogApplicationClientError) as failure:
        client.prepare_native_material_exam(command(), content=XLSX)
    assert failure.value.code == "MATERIAL_LEARNING_UNAVAILABLE"
    assert "/private/path" not in str(failure.value)


def test_native_prepare_domain_error_is_preserved(monkeypatch):
    monkeypatch.setattr(
        owner,
        "send_native_exam_workbook_upload",
        Mock(
            return_value=dict(
                schema_version="material-learning-error/1.0",
                error_code="MATERIAL_NATIVE_ORIGINAL_PAIR_REQUIRED",
            )
        ),
    )
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    with pytest.raises(CatalogApplicationClientError) as failure:
        client.prepare_native_material_exam(command(), content=XLSX)
    assert failure.value.code == "MATERIAL_NATIVE_ORIGINAL_PAIR_REQUIRED"


def test_only_native_prepare_uses_the_two_parser_300_second_window(monkeypatch):
    send = Mock(return_value=acceptance().model_dump(mode="json"))
    monkeypatch.setattr(owner, "send_native_exam_workbook_upload", send)
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client.prepare_native_material_exam(command(), content=XLSX)
    assert send.call_args.kwargs["response_timeout"] == 300
    assert owner.RESPONSE_TIMEOUT_SECONDS == 30
    assert owner.EVIDENCE_RESPONSE_TIMEOUT_SECONDS == 120


def test_native_create_client_preserves_declared_v2_bundle_and_actor():
    client = CatalogApplicationClient(expected_uid=0, expected_gid=0)
    client._raw_request = Mock(return_value=acceptance().model_dump(mode="json"))
    create = CreateNativeMaterialLearningCommand.model_validate(native_create())
    assert client.create_material_learning(create) == acceptance()
    assert client._raw_request.call_args.args[0] == create.model_dump(mode="json")
