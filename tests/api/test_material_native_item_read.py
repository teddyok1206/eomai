"""Native originals are read by authorized Item revision/hash, never invented legacy IDs."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.dependencies import get_authentication
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_MODE
from eom_catalog_contracts.material_native_item_read import (
    MaterialNativeItemReadRequest,
    MaterialNativeItemSource,
)
from eom_operator_identity import PermissionKey
from fastapi import Request

from tests.api.test_external_item_db_routes import _client
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.test_material_native_files import binding_data, metadata_data

REVISION = "itemrev_" + "2" * 32
MANIFEST = "sha256:" + "3" * 64
PATH = f"/api/v1/item-db/registrations/{REVISION}"
CONTENT = b"PK\x03\x04synthetic-native-hwpx"


def source():
    binding = binding_data()
    return MaterialNativeItemSource.model_validate(
        dict(
            material_title="예시 모의고사",
            metadata=metadata_data(),
            question=binding["question"]["document"],
            solution=binding["solution"]["document"],
            workbook=binding["workbook"],
        )
    )


def query(role=None):
    return MaterialNativeItemReadRequest(
        operation="GET_NATIVE_MATERIAL_ITEM_SOURCE"
        if role is None
        else "GET_NATIVE_MATERIAL_ITEM_DOCUMENT",
        actor_id=OPERATOR_ID,
        item_revision_id=REVISION,
        item_manifest_sha256=MANIFEST,
        source_role=role,
    )


def header(**changes):
    return (
        dict(
            operation="GET_NATIVE_MATERIAL_ITEM_DOCUMENT",
            status="OK",
            filename="EOM-원문-main.hwpx",
            media_type="application/vnd.hancom.hwpx",
            content_length=len(CONTENT),
            sha256="sha256:" + hashlib.sha256(CONTENT).hexdigest(),
        )
        | changes
    )


def api_client(*, allow_intake=True):
    client, services, _ = _client(allow_intake=allow_intake)
    catalog = SimpleNamespace(
        read_native_material_item_source=Mock(return_value=source()),
        download_native_material_item_document=Mock(
            return_value=SimpleNamespace(
                filename="EOM-원문-main.hwpx",
                media_type="application/vnd.hancom.hwpx",
                content_length=len(CONTENT),
                sha256="sha256:" + hashlib.sha256(CONTENT).hexdigest(),
                iter_chunks=lambda: iter([CONTENT]),
            )
        ),
    )
    services.catalog_application = catalog
    services.audit = Mock()
    return client, services, catalog


def test_public_native_source_uses_actual_operator_and_exact_revision_manifest():
    client, services, catalog = api_client()
    try:
        with client:
            response = client.get(PATH + "/native-source", params={"manifest_sha256": MANIFEST})
        assert response.status_code == 200, response.text
        assert response.json()["data"] == source().model_dump(mode="json")
        assert response.json()["data"]["metadata"]["original_unit"] == " 단원 원문 "
        catalog.read_native_material_item_source.assert_called_once_with(query())
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("role", ["MAIN", "SOLUTIONS"])
def test_public_download_streams_editable_hwpx_no_pdf_raster_or_arbitrary_member(role):
    client, services, catalog = api_client()
    try:
        with client:
            response = client.get(
                PATH + "/native-document", params={"manifest_sha256": MANIFEST, "source_role": role}
            )
        assert response.status_code == 200, response.text
        assert response.content == CONTENT
        assert response.headers["content-type"] == "application/vnd.hancom.hwpx"
        assert response.headers["content-length"] == str(len(CONTENT))
        assert response.headers["etag"] == '"sha256:' + hashlib.sha256(CONTENT).hexdigest() + '"'
        assert "attachment" in response.headers["content-disposition"]
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        assert response.headers["cache-control"] == "no-store"
        catalog.download_native_material_item_document.assert_called_once_with(query(role))
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("suffix", ["native-source", "native-document"])
@pytest.mark.parametrize("permission", ["intake", "item"])
def test_source_and_document_require_both_current_permissions_before_catalog(suffix, permission):
    client, services, catalog = api_client(allow_intake=permission != "intake")
    if permission == "item":

        def limited(request: Request):
            auth = _authentication()
            auth = replace(auth, permissions=auth.permissions - {PermissionKey.ITEM_READ})
            request.state.request_context.authentication = auth
            return auth

        client.app.dependency_overrides[get_authentication] = limited
    try:
        with client:
            response = client.get(
                PATH + "/" + suffix, params={"manifest_sha256": MANIFEST, "source_role": "MAIN"}
            )
        assert response.status_code == 403, response.text
        catalog.read_native_material_item_source.assert_not_called()
        catalog.download_native_material_item_document.assert_not_called()
    finally:
        services.engine.dispose()


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"manifest_sha256": "latest", "source_role": "MAIN"},
        {"manifest_sha256": MANIFEST, "source_role": "../source.hwpx"},
    ],
)
def test_native_document_requires_explicit_supported_role_and_hash(params):
    client, services, catalog = api_client()
    try:
        with client:
            response = client.get(PATH + "/native-document", params=params)
        assert response.status_code == 422
        catalog.download_native_material_item_document.assert_not_called()
    finally:
        services.engine.dispose()


@contextmanager
def private_server(tmp_path, reply, content=b""):
    path = tmp_path / "catalog.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    path.chmod(CATALOG_APPLICATION_SOCKET_MODE)
    server.listen(1)
    server.settimeout(5)
    captured, failures = {}, []

    def respond():
        try:
            with server.accept()[0] as connection:
                connection.settimeout(5)
                line = bytearray()
                while (chunk := connection.recv(1)) != b"\n":
                    assert chunk
                    line.extend(chunk)
                captured["query"] = json.loads(line)
                connection.sendall(json.dumps(reply, ensure_ascii=False).encode() + b"\n" + content)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=respond, daemon=True)
    thread.start()
    try:
        yield (
            CatalogApplicationClient(path, expected_uid=os.getuid(), expected_gid=os.getgid()),
            captured,
        )
    finally:
        thread.join(6)
        server.close()
        assert not thread.is_alive()
        if failures:
            raise failures[0]


def test_native_source_private_socket_returns_typed_pointer_only_result(tmp_path):
    reply = dict(operation=query().operation, status="OK", source=source().model_dump(mode="json"))
    with private_server(tmp_path, reply) as (client, captured):
        assert client.read_native_material_item_source(query()) == source()
    assert captured["query"] == query().model_dump(mode="json")


@pytest.mark.parametrize("media", ["application/vnd.hancom.hwpx", "application/hwp+zip"])
def test_native_document_private_stream_checks_exact_size_hash_and_closes(tmp_path, media):
    with private_server(tmp_path, header(media_type=media), CONTENT) as (client, captured):
        document = client.download_native_material_item_document(query("MAIN"))
        assert b"".join(document.iter_chunks()) == CONTENT
        assert document.connection.fileno() == -1
    assert captured["query"] == query("MAIN").model_dump(mode="json")


@pytest.mark.parametrize("content", [CONTENT[:-1], CONTENT + b"extra", b"X" * len(CONTENT)])
def test_native_document_stream_rejects_truncation_extra_bytes_and_hash_change(tmp_path, content):
    with private_server(tmp_path, header(), content) as (client, _):
        document = client.download_native_material_item_document(query("MAIN"))
        with pytest.raises(RuntimeError):
            b"".join(document.iter_chunks())
        assert document.connection.fileno() == -1


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "GET_NATIVE_MATERIAL_ITEM_SOURCE"},
        {"filename": "../secret.hwpx"},
        {"content_length": 50 * 1024 * 1024 + 1},
        {"media_type": "application/pdf"},
    ],
)
def test_native_document_invalid_header_rejected_before_stream(tmp_path, change):
    with (
        private_server(tmp_path, header(**change)) as (client, _),
        pytest.raises(CatalogApplicationClientError) as failure,
    ):
        client.download_native_material_item_document(query("MAIN"))
    assert failure.value.code == "MATERIAL_NATIVE_READ_UNAVAILABLE"


@pytest.mark.parametrize("kind", ["source", "document"])
def test_native_read_preserves_explicit_domain_errors_not_success_or_latest(tmp_path, kind):
    selected = query(None if kind == "source" else "MAIN")
    response = dict(
        operation=selected.operation, status="ERROR", error_code="MATERIAL_NATIVE_ITEM_SOURCE_STALE"
    )
    with private_server(tmp_path, response) as (client, _):
        read = (
            client.read_native_material_item_source
            if kind == "source"
            else client.download_native_material_item_document
        )
        with pytest.raises(CatalogApplicationClientError) as failure:
            read(selected)
    assert failure.value.code == "MATERIAL_NATIVE_ITEM_SOURCE_STALE"
