"""Bounded metadata + XLSX upload has one real actor and one authoritative Catalog owner."""

from __future__ import annotations

import hashlib
import json

import pytest
from eom_api.dependencies import get_authentication
from eom_catalog_contracts.material_learning_intake import MaterialLearningAcceptance
from eom_catalog_contracts.material_native_intake import CreateNativeMaterialLearningCommand
from eom_catalog_contracts.material_native_prepare import (
    MATERIAL_NATIVE_METADATA_MAX_BYTES,
    MATERIAL_NATIVE_UPLOAD_MAX_BYTES,
    MATERIAL_NATIVE_UPLOAD_MEDIA_TYPE,
    NativeMaterialExamUpload,
)
from fastapi import Request
from pydantic import ValidationError

from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.api.test_material_learning_routes import material_client as material_client
from tests.unit.test_material_native_intake import native_create

PATH = "/api/v1/material-learning/native-exams"
KEY = "material-native-exam-upload-test-1234"
XLSX = b"PK\x03\x04synthetic-workbook"


def metadata():
    value = native_create()
    for source in value["sources"]:
        source["source_upload"]["uploaded_by"] = OPERATOR_ID
    return dict(
        schema_version="material-native-exam-upload/1.0",
        upload=value["upload"],
        sources=value["sources"],
        source_namespace="native-exam-test",
        exam_key="시험 01",
        workbook_filename="문항 정보.xlsx",
    )


def acceptance():
    return MaterialLearningAcceptance(
        material_id="material_" + "1" * 32,
        material_revision_id="materialrev_" + "2" * 32,
        run_id="materialrun_" + "3" * 32,
        request_sha256="sha256:" + "4" * 64,
        replayed=False,
    )


def body(value=None, workbook=XLSX):
    return (
        json.dumps(metadata() if value is None else value, ensure_ascii=False).encode()
        + b"\n"
        + workbook
    )


def headers(**changes):
    return {"Content-Type": MATERIAL_NATIVE_UPLOAD_MEDIA_TYPE, "Idempotency-Key": KEY} | changes


def test_native_upload_stamps_actual_actor_hash_length_and_reuses_exact_key(material_client):
    from unittest.mock import Mock

    client, catalog, _, _ = material_client
    catalog.prepare_native_material_exam = Mock(return_value=acceptance())
    for _ in range(2):
        response = client.post(PATH, content=body(), headers=headers())
        assert response.status_code == 202, response.text
        assert response.json()["data"]["run_id"] == acceptance().run_id
    first, second = [call.args[0] for call in catalog.prepare_native_material_exam.call_args_list]
    assert first == second
    assert first.actor_id == OPERATOR_ID
    assert first.idempotency_key == KEY
    assert first.workbook_bytes == len(XLSX)
    assert first.workbook_sha256 == "sha256:" + hashlib.sha256(XLSX).hexdigest()
    assert catalog.prepare_native_material_exam.call_args.kwargs == {"content": XLSX}


@pytest.mark.parametrize(
    "field", ["actor_id", "operation", "workbook_sha256", "workbook_bytes", "permissions"]
)
def test_browser_cannot_supply_authority_or_workbook_identity(material_client, field):
    client, catalog, _, _ = material_client
    response = client.post(PATH, content=body(metadata() | {field: "forged"}), headers=headers())
    assert response.status_code == 422, response.text
    assert not hasattr(catalog, "prepare_native_material_exam")


@pytest.mark.parametrize("change", ["owner", "role", "format", "version"])
def test_invalid_native_pair_or_explicit_version_fails_before_catalog(material_client, change):
    client, catalog, _, _ = material_client
    value = metadata()
    if change == "owner":
        value["sources"][1]["source_upload"]["uploaded_by"] = "operator_" + "f" * 32
    elif change == "role":
        value["sources"].reverse()
    elif change == "format":
        from tests.unit.test_material_learning_intake import source_receipt

        value["sources"][0]["source_upload"] = source_receipt("PDF", OPERATOR_ID)
    else:
        value.pop("schema_version")
    response = client.post(PATH, content=body(value), headers=headers())
    assert response.status_code == 422, response.text
    assert not hasattr(catalog, "prepare_native_material_exam")


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"{}\n",
        b'{"schema_version":"material-native-exam-upload/1.0","schema_version":"material-native-exam-upload/1.0"}\n'
        + XLSX,
        b"[]\n" + XLSX,
        b"\xff\n" + XLSX,
        b"x" * (MATERIAL_NATIVE_METADATA_MAX_BYTES + 1) + b"\n" + XLSX,
        b'{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}\n" + XLSX,
    ],
)
def test_malformed_metadata_is_bounded_sanitized_and_never_reaches_catalog(
    material_client, payload
):
    client, catalog, _, _ = material_client
    response = client.post(PATH, content=payload, headers=headers())
    assert response.status_code == 422, response.text
    expected = "API_REQUEST_INVALID" if len(payload) < 9 else "MATERIAL_NATIVE_UPLOAD_INVALID"
    assert expected in response.text
    assert not hasattr(catalog, "prepare_native_material_exam")


@pytest.mark.parametrize("delta", [-1, 1])
def test_declared_total_length_must_match_received_body(material_client, delta):
    client, _, _, _ = material_client
    payload = body()
    response = client.post(
        PATH,
        content=payload,
        headers=headers(**{"Content-Length": str(len(payload) + delta)}),
    )
    assert response.status_code == 422, response.text


def test_native_upload_media_and_size_are_not_a_global_json_limit_exception(material_client):
    client, _, _, _ = material_client
    response = client.post(
        PATH, content=body(), headers=headers(**{"Content-Type": "application/json"})
    )
    assert response.status_code == 415
    response = client.post(
        PATH,
        content=body(),
        headers=headers(**{"Content-Length": str(MATERIAL_NATIVE_UPLOAD_MAX_BYTES + 1)}),
    )
    assert response.status_code == 413
    response = client.post(
        PATH, content=body(), headers=headers(**{"Transfer-Encoding": "chunked"})
    )
    assert response.status_code == 400


def test_native_upload_permission_denied_before_body_or_catalog(material_client):
    client, catalog, app, _ = material_client

    def limited(request: Request):
        auth = _authentication(admin=False)
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = limited
    response = client.post(PATH, content=body(), headers=headers())
    assert response.status_code == 403, response.text
    assert not hasattr(catalog, "prepare_native_material_exam")


def test_native_upload_contract_is_frozen_and_rejects_unversioned_metadata():
    upload = NativeMaterialExamUpload.model_validate(metadata())
    with pytest.raises(ValidationError):
        upload.exam_key = "changed"
    value = metadata()
    value.pop("schema_version")
    with pytest.raises(ValidationError):
        NativeMaterialExamUpload.model_validate(value)


def test_public_create_accepts_explicit_additive_native_v2_not_actor_from_browser(material_client):
    client, catalog, _, _ = material_client
    raw = native_create()
    for source in raw["sources"]:
        source["source_upload"]["uploaded_by"] = OPERATOR_ID
    value = {key: item for key, item in raw.items() if key not in {"actor_id", "idempotency_key"}}
    catalog.create_material_learning.return_value = acceptance()
    response = client.post(
        "/api/v1/material-learning", json=value, headers={"Idempotency-Key": KEY}
    )
    assert response.status_code == 202, response.text
    command = catalog.create_material_learning.call_args.args[0]
    assert isinstance(command, CreateNativeMaterialLearningCommand)
    assert command.actor_id == OPERATOR_ID
    assert command.native_bundle.model_dump(mode="json") == value["native_bundle"]
    rejected = client.post(
        "/api/v1/material-learning",
        json=value | {"actor_id": "operator_" + "f" * 32},
        headers={"Idempotency-Key": KEY},
    )
    assert rejected.status_code == 422
