"""Additive export transport retains predecessor bytes and rejects mixed output meanings."""

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_delivery_rpc import parse_kakao_delivery_reply
from eom_catalog_contracts.kakao_export_store import (
    KakaoExport,
    KakaoExportMutation,
    KakaoExportPage,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_delivery_dispatch import dispatch_kakao_delivery
from eom_web_gui.kakao_delivery_contracts import ExportMutation, ExportPage, StudentExport
from jsonschema.exceptions import ValidationError as JsonSchemaError

from tests.unit.test_kakao_delivery_rpc import case, owner
from tests.unit.test_kakao_export_store_contracts import pending_export
from tests.unit.test_kakao_question_editing import identity, pointer


def study_export():
    value = pending_export().model_dump(mode="json")
    value["schema_version"] = "kakao-export/2.0"
    value["export_id"] = identity("kakaoexport", 2)
    value["profile"]["layout_policy"] = "student-study-a4/1.0"
    return KakaoExport.model_validate(value)


@pytest.mark.parametrize("name", ["kakao-export-store-v2", "catalog-kakao-delivery-v2"])
def test_new_schema_mirror_and_predecessor_hash_are_preserved(name):
    import hashlib

    root = Path(__file__).resolve().parents[2]
    for key in (name, name.replace("v2", "v1")):
        resource = CATALOG_SCHEMA_RESOURCES[key]
        raw = (root / resource.canonical_path).read_bytes()
        assert (
            raw
            == (
                root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
            ).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == resource.sha256


def test_study_export_mutation_and_mixed_history_reopen_in_api_and_web_models():
    old, new = pending_export(), study_export()
    mutation = KakaoExportMutation.for_export(new, replayed=True)
    page = KakaoExportPage.for_items((old, new), next_cursor=None)
    for value, web in ((new, StudentExport), (mutation, ExportMutation), (page, ExportPage)):
        raw = value.model_dump(mode="json")
        validate_contract("kakao-export-store-v2", raw)
        with pytest.raises(JsonSchemaError):
            validate_contract("kakao-export-store-v1", raw)
        assert web.model_validate(raw).model_dump(mode="json") == raw
    assert new.profile.export_schema_version == new.schema_version
    assert new.profile.layout_schema_ref.endswith("worker-study-layout/1.0")
    assert (
        KakaoExportPage.for_items((old,), next_cursor=None).schema_version
        == "kakao-export-page/1.0"
    )
    assert (
        KakaoExportMutation.for_export(old, replayed=False).schema_version
        == "kakao-export-mutation/1.0"
    )


@pytest.mark.parametrize("case", ["v1-tag", "v1-profile", "v1-mutation", "v1-page"])
def test_unmatched_version_and_profile_are_not_implicitly_upgraded(case):
    value = study_export().model_dump(mode="json")
    if case == "v1-tag":
        value["schema_version"] = "kakao-export/1.0"
        cls = KakaoExport
    elif case == "v1-profile":
        value["profile"]["layout_policy"] = "student-question-a4/1.0"
        cls = KakaoExport
    elif case == "v1-mutation":
        value = dict(schema_version="kakao-export-mutation/1.0", export=value, replayed=False)
        cls = KakaoExportMutation
    else:
        value = dict(schema_version="kakao-export-page/1.0", items=[value], next_cursor=None)
        cls = KakaoExportPage
    with pytest.raises(ValueError):
        cls.model_validate(value)
    web = {
        KakaoExport: StudentExport,
        KakaoExportMutation: ExportMutation,
        KakaoExportPage: ExportPage,
    }[cls]
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        web.model_validate(value)


def test_completed_study_requires_exact_study_layout_and_same_artifact_revision():
    value = study_export().model_dump(mode="json")
    pdf = pointer(
        "eom://schemas/kakao-archive/question-pdf/1.0", b"pdf", media="application/pdf"
    ).model_copy(update={"member_path": "report.pdf"})
    layout = pointer("eom://schemas/kakao-archive/worker-study-layout/1.0", b"layout").model_copy(
        update={"member_path": "layout.json"}
    )
    value.update(
        state="COMPLETED",
        completed_at="2026-11-16T00:01:00Z",
        export_revision_id=identity("kakaoexportrev", 1),
        page_count=3,
        pdf=pdf.model_dump(mode="json"),
        layout=layout.model_dump(mode="json"),
    )
    assert KakaoExport.model_validate(value).page_count == 3
    value["layout"]["schema_ref"] = "eom://schemas/kakao-archive/worker-question-layout/1.0"
    with pytest.raises(ValueError, match="STORED_EXPORT_INVALID"):
        KakaoExport.model_validate(value)


@pytest.mark.parametrize("name", ["create-export", "read-export", "list-exports"])
def test_unchanged_request_and_new_reply_pass_existing_correlated_dispatch(name):
    request, _ = case(name)
    new = study_export()
    if name == "read-export":
        new = new.model_copy(update={"export_id": request.export_id})
        result = new
    elif name == "create-export":
        result = KakaoExportMutation.for_export(new, replayed=False)
    else:
        result = KakaoExportPage.for_items((pending_export(), new), next_cursor=None)
    application, method = owner(name, result)
    out = io.BytesIO()
    payload = request.model_dump(mode="json")
    validate_contract("catalog-kakao-delivery-v1", payload)
    dispatch_kakao_delivery(application, payload, out)
    reply = parse_kakao_delivery_reply(json.loads(out.getvalue()))
    assert reply.status == "OK" and reply.result == result
    assert method.call_count == 1


@pytest.mark.parametrize("policy", [None, "student-study-a4/1.0", "unreleased"])
def test_composition_keeps_legacy_default_and_requires_explicit_known_policy(monkeypatch, policy):
    import grp
    import pwd

    import eom_catalog_service.kakao_export_service as exports
    from eom_catalog_service.kakao_delivery_composition import build_kakao_delivery_application

    factory = Mock()
    monkeypatch.setattr(exports, "KakaoExportService", factory)
    monkeypatch.setattr(pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.geteuid() + 1))
    monkeypatch.setattr(grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid() + 1))
    env = dict(
        EOM_KAKAO_PDF_MODE="ENABLED",
        EOM_KAKAO_PDF_RELEASE_SHA256="sha256:" + "a" * 64,
        EOM_KAKAO_PDF_TEMPLATE_SHA256="sha256:" + "b" * 64,
        EOM_KAKAO_PDF_FONT_SHA256="sha256:" + "c" * 64,
        EOM_KAKAO_PDF_FONT_SIZE="100",
    )
    if policy is not None:
        env["EOM_KAKAO_PDF_LAYOUT_POLICY"] = policy
    if policy == "unreleased":
        with pytest.raises(ValueError, match="CONFIGURATION_INVALID"):
            build_kakao_delivery_application(Mock(), Mock(), env)
        assert not factory.called
    else:
        result = build_kakao_delivery_application(Mock(), Mock(), env)
        assert result.coordinator is not None
        assert factory.call_args.kwargs["profile"].layout_policy == (
            policy or "student-question-a4/1.0"
        )
